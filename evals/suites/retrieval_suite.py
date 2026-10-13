"""Retrieval: does BM25 surface the chunk that contains the gold evidence?
No LLM calls - deterministic and free. Runs over the combined corpus (all documents
merged, exactly as production does) with a chunk-size ablation."""
from rank_bm25 import BM25Okapi

from common import load_items, mean, norm_ws

PROD_SIZE = 300          # must match ContentAgent._retrieve
CONFIGS = [(100, 20), (200, 40), (300, 50)]   # (chunk words, overlap)
KS = (1, 2, 4)


def _rank(agent, corpus: str, query: str, size: int, overlap: int):
    chunks = agent._chunk(corpus, size=size, overlap=overlap)
    scores = BM25Okapi([c.lower().split() for c in chunks]).get_scores(query.lower().split())
    order = sorted(range(len(chunks)), key=lambda i: -scores[i])
    return [norm_ws(chunks[i]) for i in order]


def run(ctx) -> dict:
    from agents.content_agent import ContentAgent
    agent = ContentAgent()
    items = [i for i in load_items("qa.jsonl", ctx.docs) if i["answerable"] and i["evidence"]]

    metrics, table = {}, []
    split_items = set()
    for size, overlap in CONFIGS:
        hits = {k: [] for k in KS}
        full = {k: [] for k in KS}
        rr = []
        by_lang = {"en": [], "non_en": []}
        for item in items:
            ranked = _rank(agent, ctx.combined, item["question"], size, overlap)
            evid = [norm_ws(e) for e in item["evidence"]]
            holders = [{i for i, ch in enumerate(ranked) if e in ch} for e in evid]
            if any(not h for h in holders):
                split_items.add(item["id"])           # evidence straddles a chunk boundary
            first = min((min(h) for h in holders if h), default=None)
            rr.append(1 / (first + 1) if first is not None else 0.0)
            for k in KS:
                top = set(range(min(k, len(ranked))))
                hits[k].append(any(h & top for h in holders))
                full[k].append(all(h & top for h in holders))
            by_lang["en" if item["lang"] == "en" else "non_en"].append(any(h & set(range(4)) for h in holders))

        tag = f"c{size}"
        row = {"chunk_words": size, "overlap": overlap, "mrr": mean(rr)}
        for k in KS:
            row[f"hit@{k}"], row[f"full@{k}"] = mean(hits[k]), mean(full[k])
        row["hit@4_en"] = mean(by_lang["en"]) if by_lang["en"] else None
        row["hit@4_non_en"] = mean(by_lang["non_en"]) if by_lang["non_en"] else None
        table.append(row)
        if size == PROD_SIZE:
            metrics.update({"prod_hit@1": row["hit@1"], "prod_hit@2": row["hit@2"], "prod_hit@4": row["hit@4"],
                            "prod_full@4": row["full@4"], "prod_mrr": row["mrr"],
                            "prod_hit@4_non_english": row["hit@4_non_en"]})
        metrics[f"{tag}_hit@1"] = row["hit@1"]
        metrics[f"{tag}_mrr"] = row["mrr"]

    n_chunks = len(agent._chunk(ctx.combined, size=PROD_SIZE, overlap=50))
    return {
        "metrics": metrics,
        "ablation": table,
        "notes": [f"Corpus = {len(ctx.combined.split())} words -> {n_chunks} chunks at {PROD_SIZE} words. " +
                  ("top_k=4 can saturate on a corpus this small; hit@1/@2, MRR and smaller chunks are the discriminating numbers."
                   if n_chunks <= 6 else "hit@4 below 1.0 means the answer passage never reaches the LLM."),
                  f"Evidence straddling a chunk boundary: {sorted(split_items) or 'none'}"],
        "n": len(items),
    }
