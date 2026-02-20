

from groq import Groq
import os
import json


STRICT_PROMPT = """You decide the best format to explain content to a user.

USER QUERY: {query}

DOCUMENT CONTEXT (first 500 chars):
{context}

Choose format based on these criteria:

text  → query asks for a single fact, definition, or concept. Low information density needed.
audio → query asks for a process, summary, or narrative explanation. Medium density, no visuals needed.
video → query involves multiple interconnected components, a flow across systems, or explicitly asks to "walk through" or "visualize". High density, benefits from diagram.

Key signals:
- "what is" or "define" → text
- "how does", "explain", "summarize", "ELI5" → audio
- "walk through", "architecture", "flow", "step by step across components" → video

requires_diagram is true only when format is video.

Respond ONLY with valid JSON, no markdown:
{{
    "format": "text",
    "reasoning": "one line reason",
    "complexity": "simple",
    "requires_diagram": false
}}"""


class DecisionAgent:

    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = "llama-3.1-8b-instant"

    def analyze_and_decide(self, user_query: str, content_context: str, format_hint: str = "auto") -> dict:
        # User explicitly chose a format — respect it, skip AI
        if format_hint and format_hint != "auto":
            return {
                "format": format_hint,
                "reasoning": f"User selected {format_hint} explicitly",
                "complexity": "user-defined",
                "requires_diagram": format_hint == "video"
            }

        # Auto mode — AI decides
        prompt = STRICT_PROMPT.format(query=user_query, context=content_context[:500])

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You respond only with valid JSON. No markdown, no extra text."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )

            raw = response.choices[0].message.content.strip()

            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            result = json.loads(raw)

            if result.get("format") not in ("text", "audio", "video"):
                result["format"] = "text"

            return result

        except Exception as e:
            print(f"Decision agent error: {e}")
            return {
                "format": "text",
                "reasoning": "Fallback — could not parse decision",
                "complexity": "simple",
                "requires_diagram": False
            }