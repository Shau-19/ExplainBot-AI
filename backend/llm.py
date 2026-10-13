import os
from openai import OpenAI

# Single place to configure the LLM used by all agents.
# "openai/gpt-luna" (OpenRouter-style slug) is GPT-5.6 Luna; the OpenAI API id has no prefix.
DEFAULT_MODEL = "gpt-5.6-luna"


def get_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_MODEL)


def get_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
