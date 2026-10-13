"""Answer quality for the ContentAgent: correctness, faithfulness, abstention, language."""
import time

from common import detect_lang, latency_stats, load_items, mean, pmap


def run(ctx) -> dict:
    from agents.content_agent import ContentAgent
    agent = ContentAgent()
    items = load_items("qa.jsonl", ctx.docs)
    if ctx.quick:
        items = items[::3]

    def one(item):
        t0 = time.time()
        out = agent.generate_explanation(item["question"], ctx.combined, "text", item["lang"])
        latency = (time.time() - t0) * 1000
        answer = out["text"]
        retrieved = agent._retrieve(item["question"], ctx.combined, top_k=4, language=item["lang"])

        row = {"id": item["id"], "category": item["category"], "lang": item["lang"], "answerable": item["answerable"],
               "question": item["question"], "answer": answer, "latency_ms": latency}
        row["abstained"] = ctx.judge.abstained(answer)
        if item["answerable"]:
            covered = ctx.judge.fact_coverage(answer, item["gold_facts"])
            row["fact_coverage"] = mean(covered)
            row["missing_facts"] = [f for f, c in zip(item["gold_facts"], covered) if not c]
            low = answer.lower()
            row["must_include_ok"] = all(m.lower() in low for m in item["must_include"]) if item["must_include"] else None
            if not row["abstained"]:
                faith = ctx.judge.faithfulness(answer, retrieved)
                row["faithfulness"], row["unsupported"] = faith["score"], faith["unsupported"]
                row["lang_ok"] = detect_lang(answer) == item["lang"]
        return row

    rows = [r for r in pmap(one, items, ctx.workers)]
    errors = [r for r in rows if "error" in r]
    rows = [r for r in rows if "error" not in r]

    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    given = [r for r in ans if not r["abstained"]]

    def by_cat(cat):
        sel = [r["fact_coverage"] for r in ans if r["category"] == cat]
        return mean(sel) if sel else None

    metrics = {
        "fact_coverage": mean(r["fact_coverage"] for r in ans),
        "full_correct_rate": mean(r["fact_coverage"] == 1.0 for r in ans),
        "must_include_rate": mean(r["must_include_ok"] for r in ans if r["must_include_ok"] is not None),
        "faithfulness": mean(r["faithfulness"] for r in given),
        "false_abstention_rate": mean(r["abstained"] for r in ans),
        "abstention_rate_unanswerable": mean(r["abstained"] for r in unans),
        "hallucination_rate_unanswerable": mean(not r["abstained"] for r in unans),
        "language_match_rate": mean(r["lang_ok"] for r in given),
        "language_match_rate_non_english": mean(r["lang_ok"] for r in given if r["lang"] != "en") if any(r["lang"] != "en" for r in given) else None,
        "coverage_non_english": mean(r["fact_coverage"] for r in ans if r["lang"] != "en") if any(r["lang"] != "en" for r in ans) else None,
        "coverage_multi_hop": by_cat("multi_hop"),
        "coverage_list": by_cat("list"),
    }
    return {
        "metrics": metrics,
        "latency": latency_stats([r["latency_ms"] for r in rows]),
        "failures": [{"id": r["id"], "question": r["question"], "answer": r["answer"][:300],
                      "missing": r.get("missing_facts"), "unsupported": r.get("unsupported"),
                      "abstained": r["abstained"], "answerable": r["answerable"]}
                     for r in rows
                     if (r["answerable"] and (r["fact_coverage"] < 1.0 or r.get("faithfulness", 1) < 1.0))
                     or (not r["answerable"] and not r["abstained"])],
        "errors": errors,
        "n": len(rows),
    }
