"""LLM-as-judge helpers. Judge model/effort are configurable so the system under test
is not marked by itself (set EVAL_JUDGE_MODEL to a different model for a cleaner signal)."""
import json
import os
import re

from llm import get_client, get_model, reasoning_kwargs

ABSTAIN_PATTERN = re.compile(
    r"not in the uploaded document|ask something relevant|not (found )?in (the|your) (uploaded )?document",
    re.IGNORECASE,
)


class Judge:
    def __init__(self):
        self.client = get_client()
        self.model = os.getenv("EVAL_JUDGE_MODEL", get_model())
        self.effort = os.getenv("EVAL_JUDGE_REASONING", "low")

    def _ask(self, system: str, user: str) -> dict:
        resp = self.client.chat.completions.create(
            model=self.model,
            **reasoning_kwargs(self.effort),
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_completion_tokens=2500,
        )
        return json.loads(resp.choices[0].message.content)

    def fact_coverage(self, answer: str, facts: list[str]) -> list[bool]:
        """Which gold facts does the answer state (paraphrase / any language allowed)?"""
        out = self._ask(
            "You are a strict grader. Respond only with JSON.",
            "For each FACT, decide whether the ANSWER states it, explicitly or by clear paraphrase. "
            "The answer may be in any language. Do not give credit for related-but-different information.\n\n"
            f"ANSWER:\n{answer}\n\nFACTS:\n" + "\n".join(f"{i+1}. {f}" for i, f in enumerate(facts)) +
            '\n\nReturn {"covered": [true|false, ...]} with exactly one entry per fact, in order.',
        )
        covered = [bool(x) for x in out.get("covered", [])]
        return (covered + [False] * len(facts))[: len(facts)]

    def faithfulness(self, answer: str, context: str) -> dict:
        """Fraction of the answer's factual claims that the context supports."""
        out = self._ask(
            "You are a strict fact-checker. Respond only with JSON.",
            "Break the ANSWER into its distinct factual claims (ignore filler and refusals). "
            "For each claim decide if the CONTEXT supports it. Outside knowledge does not count as support.\n\n"
            f"CONTEXT:\n{context}\n\nANSWER:\n{answer}\n\n"
            'Return {"claims": [{"claim": "...", "supported": true|false}, ...]}.',
        )
        claims = out.get("claims", [])
        supported = sum(1 for c in claims if c.get("supported"))
        return {
            "score": supported / len(claims) if claims else 1.0,
            "claims": len(claims),
            "unsupported": [c.get("claim") for c in claims if not c.get("supported")],
        }

    def abstained(self, answer: str) -> bool:
        """Did the system decline to answer (not in document / off-topic)?"""
        if ABSTAIN_PATTERN.search(answer):
            return True
        out = self._ask(
            "You classify responses. Respond only with JSON.",
            "Does the RESPONSE decline to answer, say the information is not available in the document, "
            "or ask the user to stay on topic - rather than giving a substantive answer?\n\n"
            f"RESPONSE:\n{answer}\n\nReturn {{\"abstained\": true|false}}.",
        )
        return bool(out.get("abstained"))
