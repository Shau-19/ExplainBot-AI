"""Routing: does the DecisionAgent pick the right output format (text / audio / video)?"""
import time

from common import combined_corpus, latency_stats, load_items, mean, pmap

LABELS = ["text", "audio", "video"]


def run(ctx) -> dict:
    from agents.decision_agent import DecisionAgent
    agent = DecisionAgent()
    items = load_items("routing.jsonl", ctx.docs)
    if ctx.quick:
        items = items[::2]

    repeats = 1 if ctx.quick else 3

    def one(item):
        preds, lat = [], []
        for _ in range(repeats):
            t0 = time.time()
            d = agent.analyze_and_decide(item["query"], ctx.docs[item["doc"]], "auto")
            lat.append((time.time() - t0) * 1000)
            preds.append((d["format"], d.get("reasoning", "").startswith("Fallback")))
        return {**item, "predicted": preds[0][0], "all_predictions": [p for p, _ in preds],
                "fallback": any(f for _, f in preds), "latency_ms": mean(lat)}

    rows = [r for r in pmap(one, items, ctx.workers) if "error" not in r]
    labelled = [r for r in rows if r["expected"]]
    ambiguous = [r for r in rows if not r["expected"]]

    confusion = {a: {p: 0 for p in LABELS} for a in LABELS}
    for r in labelled:
        confusion[r["expected"]][r["predicted"]] += 1

    metrics = {"accuracy": mean(r["expected"] == r["predicted"] for r in labelled),
               "fallback_rate": mean(r["fallback"] for r in rows),
               "stability": mean(len(set(r["all_predictions"])) == 1 for r in rows)}
    f1s = []
    for label in LABELS:
        tp = confusion[label][label]
        fp = sum(confusion[o][label] for o in LABELS if o != label)
        fn = sum(confusion[label][o] for o in LABELS if o != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics[f"{label}_precision"], metrics[f"{label}_recall"] = precision, recall
        f1s.append(f1)
    metrics["macro_f1"] = mean(f1s)
    non_en = [r for r in labelled if not r["query"].isascii()]
    metrics["accuracy_non_english"] = mean(r["expected"] == r["predicted"] for r in non_en) if non_en else None
    metrics["stability_ambiguous"] = mean(len(set(r["all_predictions"])) == 1 for r in ambiguous) if ambiguous else None

    return {
        "metrics": metrics,
        "confusion": confusion,
        "latency": latency_stats([r["latency_ms"] for r in rows]),
        "failures": [{"query": r["query"], "expected": r["expected"], "predicted": r["predicted"]}
                     for r in labelled if r["expected"] != r["predicted"]],
        "notes": [f"Stability = same format across {repeats} repeated calls. Ambiguous queries (no gold label, "
                  f"cues conflict) are excluded from accuracy; their picks: " +
                  ", ".join(f"'{r['query'][:32]}'->{'/'.join(sorted(set(r['all_predictions'])))}" for r in ambiguous)],
        "n": len(rows),
    }
