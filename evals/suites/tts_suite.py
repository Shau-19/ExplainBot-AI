"""Voice quality via a round trip: synthesize -> transcribe (STT) -> compare with the script.
WER/CER measure intelligibility, not naturalness - so the suite also writes a MOS sheet
for human raters (accent / naturalness 1-5), the metric that matters for Indian-accent voices."""
import csv
import os
import time

from common import RESULTS, cer, latency_stats, load_jsonl, mean, pmap, wer

# voices to A/B per language; the first is whatever production currently uses (filled at runtime)
CANDIDATE_VOICES = {
    "en": ["fable", "alloy", "nova"],
    "hi": ["nova", "alloy", "shimmer", "onyx"],
    "es": ["alloy", "nova"],
}
STT_MODEL = os.getenv("EVAL_STT_MODEL", "whisper-1")


def _synthesize(tts, text: str, voice: str, path):
    t0 = time.time()
    resp = tts.oai_client.audio.speech.create(model="tts-1-hd", voice=voice, input=text, speed=1.0)
    resp.stream_to_file(str(path))
    return (time.time() - t0) * 1000


def _transcribe(client, path, lang: str) -> str:
    with open(path, "rb") as f:
        return client.audio.transcriptions.create(model=STT_MODEL, file=f, language=lang).text


def run(ctx) -> dict:
    from services.tts_service import HybridTTSService, OPENAI_VOICE_BY_LANG
    tts = HybridTTSService()
    if not tts.oai_client:
        return {"metrics": {}, "notes": ["OPENAI_API_KEY missing - TTS suite skipped"], "skipped": True}

    audio_dir = RESULTS / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    samples = load_jsonl("tts_samples.jsonl")
    if ctx.quick:
        samples = samples[::2]

    jobs = []
    for s in samples:
        prod_voice = OPENAI_VOICE_BY_LANG.get(s["lang"], OPENAI_VOICE_BY_LANG["default"])
        voices = [prod_voice] + [v for v in CANDIDATE_VOICES.get(s["lang"], []) if v != prod_voice]
        if ctx.quick:
            voices = voices[:2]
        jobs += [(s, v, v == prod_voice) for v in voices]

    def one(job):
        s, voice, is_prod = job
        path = audio_dir / f"{s['id']}_{voice}.mp3"
        try:
            synth_ms = _synthesize(tts, s["text"], voice, path)
            duration = tts._get_actual_duration(str(path))
            hyp = _transcribe(tts.oai_client, path, s["lang"])
        except Exception as e:  # noqa: BLE001
            return {"id": s["id"], "lang": s["lang"], "voice": voice, "error": str(e)[:150]}
        words = len(s["text"].split())
        return {
            "id": s["id"], "lang": s["lang"], "voice": voice, "prod": is_prod,
            "wer": wer(s["text"], hyp), "cer": cer(s["text"], hyp), "transcript": hyp,
            "duration_s": duration, "wpm": words / duration * 60 if duration else 0,
            "synth_ms": synth_ms, "rtf": (synth_ms / 1000) / duration if duration else 0,
        }

    rows = pmap(one, jobs, ctx.workers)

    ok = [r for r in rows if "error" not in r]
    prod = [r for r in ok if r["prod"]]

    def agg(rows_, key, lang):
        sel = [r[key] for r in rows_ if r["lang"] == lang]
        return mean(sel) if sel else None

    metrics = {
        "wer_en_prod": agg(prod, "wer", "en"),
        "wer_es_prod": agg(prod, "wer", "es"),
        "cer_hi_prod": agg(prod, "cer", "hi"),
        "wer_hi_prod": agg(prod, "wer", "hi"),
        "speech_rate_wpm_en": agg(prod, "wpm", "en"),
        "synth_latency_p50_ms": latency_stats([r["synth_ms"] for r in prod])["p50_ms"],
        "realtime_factor": mean(r["rtf"] for r in prod),
        "synthesis_success_rate": len(ok) / len(rows) if rows else 0.0,
    }

    # voice ablation table: mean error per (lang, voice)
    ablation = []
    for lang in sorted({r["lang"] for r in ok}):
        for voice in sorted({r["voice"] for r in ok if r["lang"] == lang}):
            sel = [r for r in ok if r["lang"] == lang and r["voice"] == voice]
            ablation.append({"lang": lang, "voice": voice, "prod": any(r["prod"] for r in sel),
                             "wer": mean(r["wer"] for r in sel), "cer": mean(r["cer"] for r in sel),
                             "wpm": mean(r["wpm"] for r in sel)})

    with open(RESULTS / "mos_sheet.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["audio_file", "lang", "voice", "naturalness_1to5", "accent_1to5", "notes"])
        for r in ok:
            w.writerow([f"audio/{r['id']}_{r['voice']}.mp3", r["lang"], r["voice"], "", "", ""])

    el = tts.get_status()["elevenlabs"]
    notes = [f"STT model: {STT_MODEL}. Elevenlabs available: {el['available']} "
             f"({'skipped - quota exhausted or no key' if not el['available'] else 'not benchmarked yet'}).",
             "Human MOS sheet written to evals/results/mos_sheet.csv (rate naturalness + Indian-accent fit 1-5)."]
    return {
        "metrics": metrics, "ablation": ablation, "notes": notes,
        "failures": [r for r in rows if "error" in r] + [
            {"id": r["id"], "voice": r["voice"], "wer": round(r["wer"], 2), "heard": r["transcript"]}
            for r in prod if r["wer"] > 0.2],
        "n": len(rows),
    }
