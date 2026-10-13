"""Retrieval: does the ranker surface the chunk that contains the gold evidence?
Calls the production ContentAgent.rank_chunks (not a copy), so what is measured is what ships.
Compares lexical BM25 against hybrid (BM25 + embeddings, rank-fused), with/without query translation,
across chunk sizes. Costs a handful of cheap embedding/translation calls (cached after the first run)."""
from common import load_items, mean, norm_ws, pmap

PROD = {"size": 300, "overlap": 50, "mode": "hybrid", "translate": True}   # must match ContentAgent._retrieve
SIZES = [(100, 20), (200, 40), (300, 50)]                                  # (chunk words, overlap)
MODES = [("bm25", False), ("bm25", True), ("hybrid", False), ("hybrid", True)]
KS = (1, 2, 4)


def _evaluate(agent, ctx, items, size, overlap, mode, translate) -> dict:
    chunks = agent._chunk(ctx.combined, size=size, overlap=overlap)
    norm_chunks = [norm_ws(c) for c in chunks]
    hits = {k: [] for k in KS}
    full = {k: [] for k in KS}
    rr, split = [], []
    by_lang = {"en": [], "non_en": []}
    for item in items:
        order = agent.rank_chunks(item["question"], chunks, language=item["lang"], mode=mode, translate=translate)
        evid = [norm_ws(e) for e in item["evidence"]]
        holders = [{pos for pos, ci in enumerate(order) if e in norm_chunks[ci]} for e in evid]
        if any(not h for h in holders):
            split.append(item["id"])                    # evidence straddles a chunk boundary
        first = min((min(h) for h in holders if h), default=None)
        rr.append(1 / (first + 1) if first is not None else 0.0)
        for k in KS:
            top = set(range(min(k, len(order))))
            hits[k].append(any(h & top for h in holders))
            full[k].append(all(h & top for h in holders))
        by_lang["en" if item["lang"] == "en" else "non_en"].append(any(h & set(range(4)) for h in holders))

    row = {"chunk_words": size, "mode": mode + ("+translate" if translate else ""), "mrr": mean(rr)}
    for k in KS:
        row[f"hit@{k}"], row[f"full@{k}"] = mean(hits[k]), mean(full[k])
    row["hit@4_en"] = mean(by_lang["en"]) if by_lang["en"] else None
    row["hit@4_non_en"] = mean(by_lang["non_en"]) if by_lang["non_en"] else None
    row["_split"] = split
    return row


def run(ctx) -> dict:
    from agents.content_agent import ContentAgent
    agent = ContentAgent()
    items = [i for i in load_items("qa.jsonl", ctx.docs) if i["answerable"] and i["evidence"]]

    # warm the embedding/translation caches in parallel so the sequential sweep below is fast
    warm_chunks = agent._chunk(ctx.combined, size=PROD["size"], overlap=PROD["overlap"])
    pmap(lambda it: agent.rank_chunks(it["question"], warm_chunks, language=it["lang"]), items, ctx.workers)

    table = [_evaluate(agent, ctx, items, size, overlap, mode, translate)
             for size, overlap in SIZES for mode, translate in MODES]

    prod_label = PROD["mode"] + ("+translate" if PROD["translate"] else "")
    prod = next(r for r in table if r["chunk_words"] == PROD["size"] and r["mode"] == prod_label)
    bm25 = next(r for r in table if r["chunk_words"] == PROD["size"] and r["mode"] == "bm25")   # the old pipeline

    metrics = {
        "prod_hit@1": prod["hit@1"], "prod_hit@2": prod["hit@2"], "prod_hit@4": prod["hit@4"],
        "prod_full@4": prod["full@4"], "prod_mrr": prod["mrr"],
        "prod_hit@4_en": prod["hit@4_en"], "prod_hit@4_non_english": prod["hit@4_non_en"],
        "bm25_only_hit@4": bm25["hit@4"], "bm25_only_hit@4_non_english": bm25["hit@4_non_en"],
        "hybrid_gain_hit@4": prod["hit@4"] - bm25["hit@4"],
    }
    split = sorted({i for r in table for i in r["_split"]})
    ablation = [{k: v for k, v in r.items() if not k.startswith("_")} for r in table]
    n_chunks = len(warm_chunks)
    return {
        "metrics": metrics,
        "ablation": ablation,
        "notes": [f"Corpus = {len(ctx.combined.split())} words -> {n_chunks} chunks at {PROD['size']} words. "
                  + ("top_k=4 can saturate on a corpus this small; hit@1/@2 and MRR are the discriminating numbers."
                     if n_chunks <= 6 else "hit@4 below 1.0 means the answer passage never reaches the LLM."),
                  f"Production = {prod_label}, {PROD['size']}-word chunks, top_k=4. Evidence straddling a chunk boundary: {split or 'none'}"],
        "n": len(items),
    }
