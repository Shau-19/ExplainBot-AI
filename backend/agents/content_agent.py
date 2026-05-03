from groq import Groq
import os
from rank_bm25 import BM25Okapi
from guardrails import log_token_estimate

LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "default": "English"
}


class ContentAgent:

    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = "llama-3.1-8b-instant"

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
        retrieved_context = self._retrieve(query, context, top_k=4)

        if format_type in ['audio', 'video']:
            system_msg = (
                f"You write natural narration scripts for audio explanations. "
                f"Use conversational language and short sentences. No bullet points. "
                f"Answer STRICTLY from the provided context — never use outside knowledge. "
                f"If the answer is not in the context, say exactly: "
                f"'This information is not in the uploaded document.' "
                f"Always respond in {lang_name}."
            )
            format_instruction = (
                f"Write as a spoken narration script in {lang_name}. "
                f"Conversational, clear, 100-150 words."
            )
        else:
            system_msg = (
                f"You are a helpful technical explainer. Be clear and concise. "
                f"Answer STRICTLY from the provided context — never use outside knowledge. "
                f"If the answer is not in the context, say exactly: "
                f"'This information is not in the uploaded document.' "
                f"Always respond in {lang_name}."
            )
            format_instruction = f"Write a clear technical explanation in {lang_name}."

        prompt = (
            f"Answer ONLY using the context below. Do not use any outside knowledge.\n"
            f"If the answer cannot be found in the context, respond with exactly:\n"
            f"\"This information is not in the uploaded document.\"\n\n"
            f"CONTEXT:\n{retrieved_context}\n\n"
            f"QUESTION: {query}\n\n"
            f"{format_instruction}"
        )

        # Log estimated tokens before the call
        log_token_estimate("ContentAgent prompt", system_msg + prompt)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,   # lower = more faithful to context
                max_tokens=600     # cap output — explanations don't need more
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

    def retrieve_for_video(self, query: str, context: str, top_k: int = 5) -> str:
        """
        Public method so VideoAgent can get grounded context directly
        without going through generate_explanation.
        """
        return self._retrieve(query, context, top_k=top_k)

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

    def _retrieve(self, query: str, context: str, top_k: int = 4) -> str:
        """
        BM25 retrieval over document chunks.
        Returns the top_k most relevant chunks joined for the prompt.
        Falls back to first 2000 chars only if chunking fails entirely.
        """
        chunks = self._chunk(context, size=300, overlap=50)

        if not chunks:
            print("[ContentAgent] ⚠️ Chunking returned nothing — falling back to slice")
            return context[:2000]

        tokenized_chunks = [c.lower().split() for c in chunks]
        tokenized_query = query.lower().split()

        bm25 = BM25Okapi(tokenized_chunks)
        top_chunks = bm25.get_top_n(
            tokenized_query, chunks, n=min(top_k, len(chunks))
        )

        retrieved = "\n\n".join(top_chunks)
        print(f"[ContentAgent] Retrieved {len(top_chunks)} chunks "
              f"({len(retrieved)} chars) for query: '{query[:60]}'")
        return retrieved
