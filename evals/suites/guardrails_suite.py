"""Guardrails: does validate_query block attacks without blocking legitimate questions?
Pure regex logic - free and deterministic, so it runs on every commit."""
from common import load_jsonl, mean


def run(ctx) -> dict:
    from guardrails import validate_query

    rows = []
    for item in load_jsonl("guardrails.jsonl"):
        ok, msg = validate_query(item["query"])
        blocked = not ok
        rows.append({**item, "blocked": blocked, "correct": blocked == item["should_block"], "message": msg})

    def rate(kinds, want_blocked):
        sel = [r for r in rows if r["kind"] in kinds and r.get("split") != "heldout"]
        return mean(r["blocked"] == want_blocked for r in sel) if sel else None

    benign = [r for r in rows if not r["should_block"] and r.get("split") != "heldout"]
    metrics = {
        "accuracy_dev": mean(r["correct"] for r in rows if r.get("split") != "heldout"),
        "injection_block_rate": rate({"injection"}, True),
        "multilingual_injection_block_rate": rate({"injection_multilingual"}, True),
        "off_topic_block_rate": rate({"off_topic"}, True),
        "false_positive_rate": mean(r["blocked"] for r in benign),
        "false_positive_rate_tricky": mean(r["blocked"] for r in benign if r["kind"] == "benign_tricky"),
    }
    held = [r for r in rows if r.get("split") == "heldout"]
    held_attacks = [r for r in held if r["should_block"]]
    held_benign = [r for r in held if not r["should_block"]]
    metrics["heldout_block_rate"] = mean(r["blocked"] for r in held_attacks) if held_attacks else None
    metrics["heldout_false_positive_rate"] = mean(r["blocked"] for r in held_benign) if held_benign else None
    failures = [{"query": r["query"], "kind": r["kind"], "blocked": r["blocked"], "heldout": r.get("split") == "heldout"} for r in rows if not r["correct"]]
    return {"metrics": metrics, "failures": failures, "n": len(rows),
            "notes": ["Dev-set metrics were used while tuning the regexes, so they are optimistic. "
                      "heldout_* are fresh cases never tuned against - the honest generalisation numbers."]}
