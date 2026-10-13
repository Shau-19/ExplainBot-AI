import os
from openai import OpenAI

# Single place to configure the LLM used by all agents.
# "openai/gpt-luna" (OpenRouter-style slug) is GPT-5.6 Luna; the OpenAI API id has no prefix.
DEFAULT_MODEL = "gpt-5.6-luna"


def get_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_MODEL)


def get_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def reasoning_kwargs(effort: str | None = None) -> dict:
    # Routing and grounded Q&A don't need chain-of-thought; "none" cuts per-call latency
    # roughly in half. Override globally with OPENAI_REASONING_EFFORT=low|medium, or pass
    # an explicit effort for a call that benefits from it (e.g. video planning).
    return {"reasoning_effort": effort or os.getenv("OPENAI_REASONING_EFFORT", "none")}
