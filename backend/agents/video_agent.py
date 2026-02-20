
from groq import Groq
import os
import json


LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "default": "English"
}


class VideoAgent:

    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = "llama-3.1-8b-instant"

    def plan_scenes(self, query: str, explanation: str, language: str = "en") -> dict:
        lang_name = LANGUAGE_NAMES.get(language, LANGUAGE_NAMES["default"])

        prompt = f"""You are creating a video explanation plan with scene-by-scene narration.

TOPIC: {query}

FULL EXPLANATION:
{explanation[:1200]}

Create a 4-scene video plan. Each scene MUST have its OWN narration that matches what's shown.

LANGUAGE RULE: 
- All narration fields must be written in {lang_name}.
- All visual text fields (title text, heading, points, caption, summary text) must be in English.

Respond ONLY with valid JSON:
{{
    "title": "Short punchy title (max 50 chars, English)",
    "total_duration": 35,
    "mermaid_diagram": "graph TD; A[User]-->B[API]; B-->C[Auth]; C-->D[Token]",
    "scenes": [
        {{
            "id": 1,
            "type": "title",
            "text": "Title shown on screen (English)",
            "narration": "Opening narration in {lang_name} (15-20 words)",
            "duration": 4
        }},
        {{
            "id": 2,
            "type": "diagram",
            "caption": "Caption under diagram (English)",
            "narration": "Describe the diagram in {lang_name} (40-50 words)",
            "duration": 15
        }},
        {{
            "id": 3,
            "type": "text",
            "heading": "Key Points (English)",
            "points": ["Point 1 (English)", "Point 2", "Point 3"],
            "narration": "Explain the points in {lang_name} (35-45 words)",
            "duration": 12
        }},
        {{
            "id": 4,
            "type": "summary",
            "text": "One-line takeaway (English)",
            "narration": "Wrap up in {lang_name} (15-20 words)",
            "duration": 4
        }}
    ]
}}

Rules:
1. Narration word counts must fit the duration (2.5 words/second)
2. mermaid_diagram must be valid Mermaid syntax
3. total_duration should be 30-40 seconds
4. Each scene's narration must match what's visible in that scene"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"You create video scripts. Visual text in English, narration in {lang_name}. Respond only with valid JSON."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4
            )

            raw = response.choices[0].message.content.strip()

            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            plan = json.loads(raw)

            for scene in plan['scenes']:
                if 'narration' not in scene or not scene['narration']:
                    scene['narration'] = "Continuing with the explanation."

            return plan

        except Exception as e:
            print(f"❌ Video agent error: {e}")
            return self._fallback_plan(query, explanation)

    def _fallback_plan(self, query: str, explanation: str) -> dict:
        sentences = explanation.split('.')[:8]

        return {
            "title": query[:50],
            "total_duration": 35,
            "mermaid_diagram": "graph TD; A[Start] --> B[Process] --> C[Result]",
            "scenes": [
                {
                    "id": 1,
                    "type": "title",
                    "text": query[:50],
                    "narration": sentences[0] if sentences else "Let's explore this topic.",
                    "duration": 4
                },
                {
                    "id": 2,
                    "type": "diagram",
                    "caption": "Process Overview",
                    "narration": '. '.join(sentences[1:4]) if len(sentences) > 3 else "The system follows this flow.",
                    "duration": 15
                },
                {
                    "id": 3,
                    "type": "text",
                    "heading": "Key Points",
                    "points": ["Step 1", "Step 2", "Step 3"],
                    "narration": '. '.join(sentences[4:6]) if len(sentences) > 5 else "Here are the key aspects.",
                    "duration": 12
                },
                {
                    "id": 4,
                    "type": "summary",
                    "text": "Summary",
                    "narration": sentences[-1] if sentences else "That covers the main points.",
                    "duration": 4
                }
            ]
        }

