"""Video plans: valid, grounded, well-sized - plus a geometry check on the diagram renderer."""
import re
import time

from common import content_tokens, detect_lang, latency_stats, load_items, mean, pmap

GENERIC_LABELS = {"start", "end", "process", "result", "input", "output", "step", "step 1", "step 2", "step 3", "node", "a", "b", "c"}
SPEECH_WPS = 2.4            # measured TTS speech rate (words/second); the tts suite re-measures it
DURATION_RANGE = (25, 50)   # seconds, from the 30-40s product target with tolerance


def _grounded(text: str, doc_tokens: set, threshold: float) -> bool:
    toks = content_tokens(text)
    return bool(toks) and sum(t in doc_tokens for t in toks) / len(toks) >= threshold


def _geometry(ctx) -> dict:
    """Layouts for 2..8 nodes must stay on canvas without overlapping; worst-case render must not crash."""
    from services.video_service import VideoService, WIDTH, HEIGHT
    svc = VideoService()
    bad = []
    for n in range(2, 9):
        pts = svc._layout(n)
        boxes = [(x - svc.NODE_W / 2, y - svc.NODE_H / 2, x + svc.NODE_W / 2, y + svc.NODE_H / 2) for x, y in pts]
        if any(b[0] < 0 or b[1] < 110 or b[2] > WIDTH or b[3] > HEIGHT - 100 for b in boxes):
            bad.append(f"n={n}: node off canvas / over header-footer")
        for i in range(n):
            for j in range(i + 1, n):
                a, b = boxes[i], boxes[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    bad.append(f"n={n}: nodes {i} and {j} overlap")
    render_ok = True
    try:
        nodes = [{"id": str(i), "label": f"A deliberately very long node label number {i}"} for i in range(8)]
        edges = [{"from": str(i), "to": str(i + 1), "label": "an edge label"} for i in range(7)]
        clip = svc._make_diagram_scene({"caption": "x" * 90, "duration": 6, "_idx": 1, "_total": 4},
                                       {"nodes": nodes, "edges": edges})
        render_ok = clip.get_frame(5.5).shape == (HEIGHT, WIDTH, 3)
    except Exception as e:  # noqa: BLE001
        bad.append(f"render crashed: {e}")
        render_ok = False
    return {"layout_ok": 1.0 if not bad else 0.0, "render_ok": 1.0 if render_ok else 0.0, "problems": bad}


def run(ctx) -> dict:
    from agents.content_agent import ContentAgent
    from agents.video_agent import VideoAgent
    content, video = ContentAgent(), VideoAgent()
    items = load_items("video_queries.jsonl", ctx.docs)
    if ctx.quick:
        items = items[::2]
    doc_tokens = set(content_tokens(ctx.combined))

    def one(item):
        grounded = content.retrieve_for_video(item["query"], ctx.combined, top_k=5)
        t0 = time.time()
        try:
            plan = video.plan_scenes(item["query"], grounded, item["lang"], grounded)
        except Exception as e:  # noqa: BLE001
            return {"id": item["id"], "query": item["query"], "ok": False, "error": str(e)[:200]}
        latency = (time.time() - t0) * 1000
        labels = [n["label"] for n in plan["diagram"]["nodes"]]
        points = plan["scenes"][2]["points"]
        narration = " ".join(s["narration"] for s in plan["scenes"])
        words = len(narration.split())
        est = words / SPEECH_WPS
        faith = ctx.judge.faithfulness(narration, grounded)
        return {
            "id": item["id"], "query": item["query"], "ok": True, "latency_ms": latency,
            "nodes": len(labels), "edges": len(plan["diagram"]["edges"]),
            "generic_label_rate": mean(l.strip().lower() in GENERIC_LABELS for l in labels),
            "label_grounding": mean(_grounded(l, doc_tokens, 0.5) for l in labels),
            "point_grounding": mean(_grounded(p, doc_tokens, 0.6) for p in points),
            "est_duration_s": est, "duration_ok": DURATION_RANGE[0] <= est <= DURATION_RANGE[1],
            "lang_ok": detect_lang(narration) == item["lang"],
            "narration_faithfulness": faith["score"], "unsupported": faith["unsupported"],
            "labels": labels,
        }

    rows = pmap(one, items, ctx.workers)
    errors = [r for r in rows if "error" in r and "ok" not in r]
    rows = [r for r in rows if "ok" in r]
    good = [r for r in rows if r["ok"]]
    geo = _geometry(ctx)

    metrics = {
        "plan_success_rate": mean(r["ok"] for r in rows),
        "label_grounding": mean(r["label_grounding"] for r in good),
        "point_grounding": mean(r["point_grounding"] for r in good),
        "generic_label_rate": mean(r["generic_label_rate"] for r in good),
        "narration_faithfulness": mean(r["narration_faithfulness"] for r in good),
        "duration_in_range_rate": mean(r["duration_ok"] for r in good),
        "est_duration_mean_s": mean(r["est_duration_s"] for r in good),
        "narration_language_match": mean(r["lang_ok"] for r in good),
        "avg_nodes": mean(r["nodes"] for r in good),
        "layout_ok": geo["layout_ok"],
        "render_ok": geo["render_ok"],
    }
    return {
        "metrics": metrics,
        "latency": latency_stats([r["latency_ms"] for r in good]),
        "plans": [{k: r[k] for k in ("id", "query", "labels", "est_duration_s", "unsupported")} for r in good],
        "failures": [{"id": r["id"], "query": r["query"], "error": r["error"]} for r in rows if not r["ok"]] + geo["problems"],
        "errors": errors,
        "n": len(rows),
    }
