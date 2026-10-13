"""Shared plumbing for the eval suites: env setup, data loading, metrics, parallel map."""
import json
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT.parent / "backend"
DATA = ROOT / "data"
RESULTS = ROOT / "results"


def setup_env() -> None:
    """Make the backend importable and load keys. Backend code uses cwd-relative output dirs."""
    from dotenv import load_dotenv
    for env in (ROOT.parent / ".env", BACKEND / ".env"):
        load_dotenv(env)
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ── Data ──────────────────────────────────────────────────────────────────────

def load_jsonl(name: str) -> list[dict]:
    with open(DATA / name, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


OPTIONAL_DOCS = {"scm_notes"}   # local-only PDFs (gitignored); their items are skipped when the file is absent


def _pdf_text(path: Path) -> str:
    """Same extraction as the product's /api/upload (pypdf, pages joined by newline), cached by mtime."""
    cache = RESULTS / ".cache" / f"{path.stem}-{int(path.stat().st_mtime)}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    from pypdf import PdfReader
    text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text


def load_docs() -> dict[str, str]:
    docs = {}
    for p in sorted((DATA / "docs").iterdir()):
        if p.suffix == ".txt":
            docs[p.stem] = p.read_text(encoding="utf-8")
        elif p.suffix == ".pdf":
            docs[p.stem] = _pdf_text(p)
    return docs


def load_items(name: str, docs: dict) -> list[dict]:
    """Dataset rows whose document is available (optional local PDFs may be missing)."""
    return [i for i in load_jsonl(name) if i["doc"] in docs or i["doc"] not in OPTIONAL_DOCS]


def combined_corpus(docs: dict[str, str]) -> str:
    """Same format main.combine_documents() feeds the agents in production."""
    return "\n\n---\n\n".join(f"[Document: {name}.txt]\n{text}" for name, text in docs.items())


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def validate_dataset(docs: dict[str, str]) -> list[str]:
    """Every evidence string must exist verbatim in its document, or the retrieval gold is wrong."""
    problems = []
    for item in load_items("qa.jsonl", docs):
        if item["doc"] not in docs:
            problems.append(f"{item['id']}: unknown doc {item['doc']}")
            continue
        text = norm_ws(docs[item["doc"]])
        for ev in item.get("evidence", []):
            if norm_ws(ev) not in text:
                problems.append(f"{item['id']}: evidence not found in doc: {ev!r}")
    for item in load_items("routing.jsonl", docs) + load_items("video_queries.jsonl", docs):
        if item["doc"] not in docs:
            problems.append(f"{item['id']}: unknown doc {item['doc']}")
    return problems


# ── Concurrency / stats ───────────────────────────────────────────────────────

def pmap(fn, items, workers: int = 6) -> list:
    """Order-preserving parallel map. Exceptions are captured as {'error': str}."""
    def safe(x):
        try:
            return fn(x)
        except Exception as e:  # noqa: BLE001 - eval must never crash on one bad item
            return {"error": f"{type(e).__name__}: {e}"}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(safe, items))


def mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def percentile(values, p: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    k = (len(values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def latency_stats(ms: list[float]) -> dict:
    return {"p50_ms": round(percentile(ms, 50)), "p95_ms": round(percentile(ms, 95)), "n": len(ms)}


# ── Text metrics ──────────────────────────────────────────────────────────────

def normalize_text(text: str) -> str:
    """Lowercase and drop punctuation/symbols but keep combining marks (Devanagari matras)."""
    text = unicodedata.normalize("NFC", text.lower())
    kept = [" " if unicodedata.category(ch)[0] in ("P", "S") else ch for ch in text]
    return re.sub(r"\s+", " ", "".join(kept)).strip()


def _edit_distance(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize_text(reference).split(), normalize_text(hypothesis).split()
    return _edit_distance(ref, hyp) / max(1, len(ref))


def cer(reference: str, hypothesis: str) -> float:
    ref, hyp = list(normalize_text(reference).replace(" ", "")), list(normalize_text(hypothesis).replace(" ", ""))
    return _edit_distance(ref, hyp) / max(1, len(ref))


STOPWORDS = set("""a an the of to in on for and or is are was were be been it its this that these those with by as at
from into than then so such not no can will may also has have had do does did their there which who whom how what when
where why you your we our they them he she his her i me my""".split())


def content_tokens(text: str) -> list[str]:
    return [t for t in normalize_text(text).split() if len(t) >= 3 and t not in STOPWORDS]


def detect_lang(text: str) -> str:
    from langdetect import detect, LangDetectException
    try:
        return detect(text)
    except LangDetectException:
        return "unknown"
