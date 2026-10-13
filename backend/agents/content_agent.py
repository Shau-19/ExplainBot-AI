import hashlib
import os
import string

import numpy as np
from rank_bm25 import BM25Okapi

from llm import get_client, get_model, reasoning_kwargs
from guardrails import log_token_estimate

LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "default": "English"
}

EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
RRF_K = 60                      # reciprocal-rank-fusion constant
_PUNCT = string.punctuation + "“”‘’–—¿¡।"   # incl. Devanagari danda


def _tokens(text: str) -> list[str]:
    """Whitespace tokens with surrounding punctuation stripped ('flow?' must match 'flow')."""
    return [t for t in (w.strip(_PUNCT) for w in text.lower().split()) if t]


class ContentAgent:

    # Process-wide caches: chunk embeddings are reused across requests, translations across calls.
    _embed_cache: dict[str, np.ndarray] = {}
    _translation_cache: dict[str, str] = {}

    def __init__(self):
        self.client = get_client()
        self.model = get_model()

    # ── Public ───────────────────────────────────────────────

    def generate_explanation(
        self,
        query: str,
        context: str,
        format_type: str,
        language: str = "en"
    ) -> dict:
        lang_name = LANGUAGE_NAMES.get(language, LANGUAGE_NAMES["default"])

        # Retrieve only relevant chunks — never dump the whole doc into the LLM
        retrieved_context = self._retrieve(query, context, top_k=4, language=language)
        query_en = self.to_english_query(query, language)

        # One consistent grounding policy for every format. (The previous prompt told the
        # model both to fall back to general knowledge AND to refuse - the eval suite showed
        # this causing intermittent false refusals on questions the context answers.)
        system_msg = (
            "You answer questions about the user's uploaded document using only the provided context. "
            "If the context contains the answer, give it - even when the question is phrased differently "
            "or written in another language than the document. "
            "State only what the context says: do not add background, examples, definitions or "
            "consequences from your own knowledge, even if they are correct. "
            "Reply with exactly 'This information is not in the uploaded document.' only when the "
            "context truly does not contain the answer. "
            "For off-topic requests (jokes, code generation, opinions, general trivia) reply with exactly "
            "'Please ask something relevant to your uploaded document.'"
        )
        if format_type in ['audio', 'video']:
            format_instruction = (
                f"Write as a spoken narration script in {lang_name}. "
                f"Conversational, clear, 100-150 words."
            )
        else:
            format_instruction = f"Write a clear technical explanation in {lang_name}."

        question_block = f"QUESTION: {query}"
        if query_en != query:
            # The context is usually English: give the model the English form to match against,
            # while still answering in the user's language.
            question_block += (
                f"\nENGLISH VERSION OF THE QUESTION (use it to find the answer in the context): {query_en}"
            )

        prompt = (
            f"CONTEXT:\n{retrieved_context}\n\n"
            f"{question_block}\n\n"
            f"{format_instruction}"
        )

        # Log estimated tokens before the call
        log_token_estimate("ContentAgent prompt", system_msg + prompt)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                **reasoning_kwargs(),
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=2000  # includes reasoning tokens; answer itself is short
            )
            text = response.choices[0].message.content
            return {
                'text': text,
                'script': text if format_type in ['audio', 'video'] else None,
                'retrieved_chunks': len(retrieved_context.split('\n\n'))
            }

        except Exception as e:
            print(f"Content agent error: {e}")
            return {
                'text': f"Error generating explanation: {e}",
                'script': None,
                'retrieved_chunks': 0
            }

    def retrieve_for_video(self, query: str, context: str, top_k: int = 5, language: str = "en") -> str:
        """
        Public method so VideoAgent can get grounded context directly
        without going through generate_explanation.
        """
        return self._retrieve(query, context, top_k=top_k, language=language)

    def to_english_query(self, query: str, language: str = "en") -> str:
        """Translate a non-English question to English so it can match an English document.
        BM25 is purely lexical, so a Hindi/Spanish question shares no tokens with English text."""
        if language == "en" and query.isascii():
            return query
        if query in self._translation_cache:
            return self._translation_cache[query]
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                **reasoning_kwargs("none"),
                messages=[
                    {"role": "system", "content": "Translate the user's question into English. "
                                                  "Output only the translation, nothing else."},
                    {"role": "user", "content": query},
                ],
                max_completion_tokens=200,
            )
            translated = (resp.choices[0].message.content or "").strip() or query
        except Exception as e:  # noqa: BLE001 - retrieval must degrade, not fail
            print(f"[ContentAgent] translation failed, using original query: {e}")
            translated = query
        self._translation_cache[query] = translated
        return translated

    def rank_chunks(self, query: str, chunks: list[str], language: str = "en",
                    mode: str | None = None, translate: bool = True) -> list[int]:
        """Chunk indices, best first. mode: 'hybrid' (BM25 + embeddings, rank-fused) or 'bm25'."""
        mode = mode or os.getenv("RETRIEVAL_MODE", "hybrid")
        q = self.to_english_query(query, language) if translate else query

        bm25_scores = BM25Okapi([_tokens(c) for c in chunks]).get_scores(_tokens(q))
        bm25_rank = sorted(range(len(chunks)), key=lambda i: -bm25_scores[i])
        if mode == "bm25":
            return bm25_rank

        try:
            chunk_vecs = self._embed(chunks)
            q_vec = self._embed([q])[0]
            sims = chunk_vecs @ q_vec
        except Exception as e:  # noqa: BLE001
            print(f"[ContentAgent] embeddings unavailable, falling back to BM25: {e}")
            return bm25_rank
        dense_rank = sorted(range(len(chunks)), key=lambda i: -sims[i])

        fused = {i: 0.0 for i in range(len(chunks))}
        for ranking in (bm25_rank, dense_rank):
            for pos, i in enumerate(ranking):
                fused[i] += 1.0 / (RRF_K + pos + 1)
        return sorted(fused, key=lambda i: -fused[i])

    # ── Private ──────────────────────────────────────────────

    def _chunk(self, text: str, size: int = 300, overlap: int = 50) -> list[str]:
        """
        Word-level overlapping chunks.
        Overlap ensures answers near chunk boundaries aren't missed.
        """
        words = text.split()
        chunks = []
        step = size - overlap
        for i in range(0, len(words), step):
            chunk = " ".join(words[i:i + size])
            if chunk.strip():
                chunks.append(chunk)
        return chunks

    def _embed(self, texts: list[str]) -> np.ndarray:
        """Unit-normalised embeddings; only texts missing from the cache hit the API."""
        keys = [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in texts]
        missing = [(k, t) for k, t in dict(zip(keys, texts)).items() if k not in self._embed_cache]
        for start in range(0, len(missing), 256):
            batch = missing[start:start + 256]
            resp = self.client.embeddings.create(model=EMBED_MODEL, input=[t for _, t in batch])
            for (k, _), item in zip(batch, resp.data):
                v = np.asarray(item.embedding, dtype=np.float32)
                self._embed_cache[k] = v / (np.linalg.norm(v) or 1.0)
        return np.stack([self._embed_cache[k] for k in keys])

    def _retrieve(self, query: str, context: str, top_k: int = 4, language: str = "en") -> str:
        """
        Hybrid retrieval (BM25 + embeddings, reciprocal-rank-fused) over document chunks,
        with non-English questions translated to English first.
        Returns the top_k most relevant chunks joined for the prompt.
        Falls back to first 2000 chars only if chunking fails entirely.
        """
        chunks = self._chunk(context, size=300, overlap=50)

        if not chunks:
            print("[ContentAgent] ⚠️ Chunking returned nothing — falling back to slice")
            return context[:2000]

        order = self.rank_chunks(query, chunks, language=language)[:min(top_k, len(chunks))]
        top_chunks = [chunks[i] for i in order]

        retrieved = "\n\n".join(top_chunks)
        print(f"[ContentAgent] Retrieved {len(top_chunks)} chunks "
              f"({len(retrieved)} chars) for query: '{query[:60]}'")
        return retrieved
