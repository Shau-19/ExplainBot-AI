import re
import time
from collections import defaultdict


# ── Config ────────────────────────────────────────────────────────────────────

QUERY_MIN_CHARS = 5
QUERY_MAX_CHARS = 400          # beyond this it's prompt injection, not a question
CONTEXT_MAX_CHARS = 50_000     # ~12k tokens — hard cap before chunking
MAX_REQUESTS_PER_IP = 20       # per rolling window
RATE_WINDOW_SECONDS = 3600     # 1 hour
MAX_UPLOAD_BYTES = 5 * 1024 * 1024   # 5 MB per file

# Patterns that signal prompt injection or jailbreak attempts
INJECTION_PATTERNS = [
    r"ignore (all |previous |above |prior )?instructions",
    r"you are now",
    r"pretend (you are|to be)",
    r"act as (a|an|if)",
    r"disregard (your|all|the)",
    r"forget (everything|your|all)",
    r"new (persona|role|instructions|system)",
    r"do anything now",
    r"dan mode",
    r"jailbreak",
    r"bypass (your|the|all)",
    r"reveal (your|the) (system|prompt|instructions|api key)",
    r"print (your|the) (system|prompt|instructions|api key)",
    r"what is your (api|groq|openai|elevenlabs) key",
    r"override",
    r"sudo",
    r"<\s*script",          # HTML/JS injection
    r"\{\{.*\}\}",          # template injection
    r"system\s*:",          # fake system message
    r"assistant\s*:",       # fake assistant turn
]

# Queries that are clearly off-topic and waste tokens
OFF_TOPIC_PATTERNS = [
    r"write (me )?(a |an )?(poem|song|story|essay|code|script)",
    r"generate (an? )?(image|picture|photo|video of)",
    r"(tell me |give me )?(a )?joke",
    r"what (is |are )?(your|the) (opinion|thoughts) on (politics|religion|sex)",
    r"who (should |do |would )?i vote",
    r"make me (a )?(website|app|game)",
    r"translate (this |the )?(entire |whole )?(document|text|file)",
]

_COMPILED_INJECTION = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
_COMPILED_OFF_TOPIC = [re.compile(p, re.IGNORECASE) for p in OFF_TOPIC_PATTERNS]

# ── IP-based rate tracker (in-memory, resets on restart) ─────────────────────

_ip_requests: dict[str, list[float]] = defaultdict(list)


def check_ip_rate(ip: str) -> tuple[bool, str]:
    """
    Sliding window rate limiter per IP.
    Returns (allowed: bool, reason: str).
    """
    now = time.time()
    window_start = now - RATE_WINDOW_SECONDS

    # Prune old entries
    _ip_requests[ip] = [t for t in _ip_requests[ip] if t > window_start]

    if len(_ip_requests[ip]) >= MAX_REQUESTS_PER_IP:
        wait_minutes = int((RATE_WINDOW_SECONDS - (now - _ip_requests[ip][0])) / 60) + 1
        return False, f"Too many requests. Try again in ~{wait_minutes} minute(s)."

    _ip_requests[ip].append(now)
    return True, ""


# ── Query validation ──────────────────────────────────────────────────────────

def validate_query(query: str) -> tuple[bool, str]:
    """
    Returns (valid: bool, reason: str).
    Runs before any LLM call.
    """
    if not query or not query.strip():
        return False, "Query cannot be empty."

    q = query.strip()

    if len(q) < QUERY_MIN_CHARS:
        return False, f"Query too short (min {QUERY_MIN_CHARS} characters)."

    if len(q) > QUERY_MAX_CHARS:
        return False, (
            f"Query too long ({len(q)} chars). "
            f"Please keep questions under {QUERY_MAX_CHARS} characters."
        )

    # Repetitive character spam — e.g. "aaaaaaaaaa" or "???????????"
    if _is_gibberish(q):
        return False, "Query appears to be gibberish. Please ask a real question."

    # Prompt injection
    for pattern in _COMPILED_INJECTION:
        if pattern.search(q):
            return False, "Query contains disallowed content."

    # Off-topic
    for pattern in _COMPILED_OFF_TOPIC:
        if pattern.search(q):
            return False, (
                "ExplainBot answers questions about uploaded documents only. "
                "Please ask something specific to your document."
            )

    return True, ""


def _is_gibberish(text: str) -> bool:
    """
    Heuristic: if >60% of chars are the same character, or the text is
    all non-alphanumeric, it's probably spam.
    """
    stripped = text.replace(" ", "")
    if not stripped:
        return True

    # All same character
    most_common_ratio = max(stripped.count(c) for c in set(stripped)) / len(stripped)
    if most_common_ratio > 0.6 and len(stripped) > 8:
        return True

    # No alphanumeric characters at all
    if not any(c.isalnum() for c in stripped):
        return True

    return False


# ── Context / upload guards ───────────────────────────────────────────────────

def validate_context(context: str) -> tuple[bool, str]:
    """
    Guard against feeding absurdly large documents into the LLM directly.
    The retrieval pipeline handles large docs, but we still cap the raw input.
    """
    if not context or not context.strip():
        return False, "Document appears to be empty or unreadable."

    if len(context) > CONTEXT_MAX_CHARS:
        # Don't reject — just warn caller to truncate before passing to LLM
        # Retrieval chunking in ContentAgent handles this correctly
        return True, f"Large document ({len(context)} chars) — retrieval will chunk it."

    return True, ""


def validate_upload_size(file_size_bytes: int) -> tuple[bool, str]:
    if file_size_bytes > MAX_UPLOAD_BYTES:
        mb = file_size_bytes / (1024 * 1024)
        return False, f"File too large ({mb:.1f} MB). Maximum is 5 MB."
    return True, ""


# ── Token estimation ──────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough estimate: ~4 chars per token (GPT/Llama rule of thumb)."""
    return len(text) // 4


def log_token_estimate(stage: str, text: str):
    """
    Prints a token usage estimate at each LLM call stage.
    Useful for debugging runaway token consumption.
    """
    tokens = estimate_tokens(text)
    print(f"[TOKEN GUARD] {stage}: ~{tokens} tokens ({len(text)} chars)")
    if tokens > 3000:
        print(f"[TOKEN GUARD] ⚠️  High token count at '{stage}' — check chunking.")
