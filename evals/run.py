"""ExplainBot eval runner.

    cd backend && ./venv/Scripts/python.exe ../evals/run.py                  # everything
    ... run.py --suites guardrails,retrieval                                 # free, deterministic suites
    ... run.py --quick                                                       # ~1/3 of the data, fast smoke run
    ... run.py --gate                                                        # exit 1 if any threshold is violated

Writes evals/results/latest.{json,md} (+ a timestamped copy) and diffs against the previous latest.json.
"""
import argparse
import importlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

SUITES = {
    "guardrails": "suites.guardrails_suite",
    "routing": "suites.routing_suite",
    "retrieval": "suites.retrieval_suite",
    "answers": "suites.answers_suite",
    "video_plan": "suites.video_plan_suite",
    "tts": "suites.tts_suite",
}
FREE = {"guardrails", "retrieval"}


class Ctx:
    def __init__(self, quick: bool, workers: int, needs_llm: bool):
        self.quick, self.workers = quick, workers
        self.docs = common.load_docs()
        self.combined = common.combined_corpus(self.docs)
        self.judge = None
        if needs_llm:
            from judge import Judge
            self.judge = Judge()


def aggregate(runs: list[dict]) -> dict:
    """Mean of numeric metrics over repeated runs (+ std); details come from the last run."""
    res = dict(runs[-1])
    if len(runs) == 1 or runs[-1].get("skipped"):
        return res
    res["metrics"], res["metrics_std"] = {}, {}
    for m in runs[-1]["metrics"]:
        vals = [r["metrics"][m] for r in runs if isinstance(r["metrics"].get(m), (int, float))]
        if vals:
            mu = sum(vals) / len(vals)
            res["metrics"][m] = mu
            res["metrics_std"][m] = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5
        else:
            res["metrics"][m] = runs[-1]["metrics"][m]
    res["repeats"] = len(runs)
    return res


def git_rev() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=common.ROOT,
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def check(value, rule: dict) -> bool:
    if value is None:
        return True
    return value >= rule["min"] if "min" in rule else value <= rule["max"]


def render_md(report: dict, thresholds: dict, prev: dict | None) -> str:
    meta = report["meta"]
    out = [f"# ExplainBot eval report",
           f"`{meta['timestamp']}` · commit `{meta['commit']}` · model `{meta['model']}` · judge `{meta['judge_model']}`"
           f" · {'quick' if meta['quick'] else 'full'} run · {meta['duration_s']}s", ""]
    for name, res in report["suites"].items():
        out.append(f"## {name}  (n={res.get('n', '-')}{', mean of ' + str(res['repeats']) + ' runs' if res.get('repeats') else ''})")
        if res.get("skipped"):
            out += [f"_skipped_: {'; '.join(res.get('notes', []))}", ""]
            continue
        out += ["| metric | value | threshold | status | Δ vs baseline |", "|---|---|---|---|---|"]
        for m, v in res["metrics"].items():
            rule = thresholds.get(name, {}).get(m)
            thr = "-" if not rule else (f"≥ {rule['min']}" if "min" in rule else f"≤ {rule['max']}")
            status = "-" if not rule else ("PASS" if check(v, rule) else "**FAIL**")
            pv = (prev or {}).get("suites", {}).get(name, {}).get("metrics", {}).get(m)
            delta = f"{v - pv:+.3f}" if isinstance(v, (int, float)) and isinstance(pv, (int, float)) else "-"
            sd = res.get("metrics_std", {}).get(m)
            shown = f"{fmt(v)} ± {sd:.3f}" if sd else fmt(v)
            out.append(f"| {m} | {shown} | {thr} | {status} | {delta} |")
        if "latency" in res:
            l = res["latency"]
            out.append(f"\nLatency p50 **{l['p50_ms']} ms**, p95 **{l['p95_ms']} ms** (n={l['n']})")
        if "confusion" in res:
            out += ["\n| expected \\ predicted | text | audio | video |", "|---|---|---|---|"]
            for a, row in res["confusion"].items():
                out.append(f"| {a} | {row['text']} | {row['audio']} | {row['video']} |")
        if res.get("ablation"):
            cols = list(res["ablation"][0].keys())
            out += ["\n| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
            out += ["| " + " | ".join(fmt(r[c]) for c in cols) + " |" for r in res["ablation"]]
        for note in res.get("notes", []):
            out.append(f"\n> {note}")
        fails = res.get("failures", [])
        if fails:
            out.append(f"\n<details><summary>{len(fails)} failure(s)</summary>\n")
            out += [f"- `{json.dumps(f, ensure_ascii=False)[:400]}`" for f in fails[:12]]
            out.append("\n</details>")
        if res.get("errors"):
            out.append(f"\n⚠️ {len(res['errors'])} item(s) crashed: `{res['errors'][0]}`")
        out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suites", default="all")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--gate", action="store_true", help="exit 1 if a threshold is violated")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--repeats", type=int, default=1, help="run each suite N times; report mean ± std (LLM output is stochastic)")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--set-baseline", action="store_true", help="pin this run as results/baseline.json (later runs diff against it)")
    args = ap.parse_args()

    common.setup_env()
    names = list(SUITES) if args.suites == "all" else [s.strip() for s in args.suites.split(",")]
    unknown = [n for n in names if n not in SUITES]
    if unknown:
        print(f"unknown suites: {unknown}; choose from {list(SUITES)}")
        return 2

    ctx = Ctx(args.quick, args.workers, needs_llm=any(n not in FREE for n in names))
    problems = common.validate_dataset(ctx.docs)
    if problems:
        print("DATASET INVALID:\n  " + "\n  ".join(problems))
        return 2

    from llm import get_model
    thresholds = json.loads((common.ROOT / "thresholds.json").read_text(encoding="utf-8"))
    latest = common.RESULTS / "latest.json"
    baseline = common.RESULTS / "baseline.json"
    ref = baseline if baseline.exists() else latest      # diff against the pinned baseline when there is one
    prev = json.loads(ref.read_text(encoding="utf-8")) if ref.exists() else None

    t_start = time.time()
    report = {"meta": {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "commit": git_rev(),
                       "model": get_model(), "judge_model": ctx.judge.model if ctx.judge else "-",
                       "quick": args.quick}, "suites": {}}
    for name in names:
        t0 = time.time()
        print(f"▶ {name} ...", flush=True)
        try:
            res = aggregate([importlib.import_module(SUITES[name]).run(ctx)
                             for _ in range(1 if name in FREE else args.repeats)])
        except Exception as e:  # noqa: BLE001
            res = {"metrics": {}, "errors": [f"{type(e).__name__}: {e}"], "n": 0}
        report["suites"][name] = res
        print(f"  done in {time.time() - t0:.1f}s", flush=True)
    report["meta"]["duration_s"] = round(time.time() - t_start)

    violations = []
    for name, res in report["suites"].items():
        if res.get("skipped"):
            continue
        for m, rule in thresholds.get(name, {}).items():
            v = res["metrics"].get(m)
            if v is not None and not check(v, rule):
                violations.append(f"{name}.{m} = {fmt(v)} violates {rule}")
        if res.get("errors") and not res["metrics"]:
            violations.append(f"{name}: suite crashed ({res['errors'][0]})")
    report["violations"] = violations

    md = render_md(report, thresholds, prev)
    if not args.no_save:
        common.RESULTS.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for path in (latest, common.RESULTS / f"run-{stamp}.json"):
            path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        (common.RESULTS / "latest.md").write_text(md, encoding="utf-8")
        if args.set_baseline:
            baseline.write_text(latest.read_text(encoding="utf-8"), encoding="utf-8")
            print("baseline pinned ->", baseline)

    print("\n" + md)
    print(f"\n{'VIOLATIONS' if violations else 'ALL THRESHOLDS MET'}")
    for v in violations:
        print("  ✗", v)
    return 1 if (args.gate and violations) else 0


if __name__ == "__main__":
    sys.exit(main())
