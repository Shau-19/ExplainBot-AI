import os
import json
from llm import get_client, get_model, reasoning_kwargs
from guardrails import log_token_estimate

LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "default": "English"
}

MAX_NODES = 8
MAX_ATTEMPTS = 2


class VideoPlanError(Exception):
    """Raised when the model cannot produce a valid scene plan."""


class VideoAgent:

    def __init__(self):
        self.client = get_client()
        self.model = get_model()

    def plan_scenes(
        self,
        query: str,
        explanation: str,
        language: str = "en",
        grounded_context: str = ""
    ) -> dict:
        """
        Plan 4 scenes for a video explanation.

        `grounded_context` — retrieved chunks from ContentAgent.
        When provided, scene narration is grounded in the actual document
        rather than the LLM-generated explanation (which may hallucinate).
        Falls back to explanation if grounded_context is empty.

        Raises VideoPlanError if no valid plan after MAX_ATTEMPTS — we never
        return a placeholder plan, because a fake video is worse than an error.
        """
        lang_name = LANGUAGE_NAMES.get(language, LANGUAGE_NAMES["default"])
        source_text = (grounded_context or explanation)[:3500]
        prompt = self._build_prompt(query, source_text, lang_name)

        log_token_estimate("VideoAgent prompt", prompt)

        last_error = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    # "none" is ~2x faster with the structured prompt; set VIDEO_REASONING_EFFORT=low for more detail
                    **reasoning_kwargs(os.getenv("VIDEO_REASONING_EFFORT", "none")),
                    response_format={"type": "json_object"},
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                f"You create video scripts strictly from provided source content. "
                                f"Visual text in English, narration in {lang_name}. "
                                f"Never invent facts not present in the source. "
                                f"Respond only with valid JSON."
                            )
                        },
                        {"role": "user", "content": prompt}
                    ],
                    max_completion_tokens=4000
                )
                plan = json.loads(response.choices[0].message.content)
                return self._validate(plan)

            except Exception as e:
                last_error = e
                print(f"⚠️ Video plan attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")

        raise VideoPlanError(f"Could not plan video: {last_error}")

    # ── Private ──────────────────────────────────────────────

    def _build_prompt(self, query: str, source_text: str, lang_name: str) -> str:
        return f"""You are creating a video explanation plan with scene-by-scene narration.

TOPIC: {query}

SOURCE CONTENT (use ONLY this — do not add outside knowledge):
{source_text}

Create a 4-scene video plan: title, diagram, text, summary. Each scene has its OWN narration
that matches what is shown. All narration and labels must come from the source content.

LANGUAGE RULE:
- All narration fields must be written in {lang_name}.
- All visual text (title, labels, points, caption, summary) must be in English.

DIAGRAM RULE:
The diagram shows the real components/steps from the source, in the order they happen.
- 3 to {MAX_NODES} nodes. Labels are short (max 22 chars), specific names from the source
  (e.g. "API Gateway", "Redis Rate Limiter") — never generic words like "Start" or "Process".
- Edges follow the flow; an optional edge label (max 16 chars) names the action.
- The scene 2 narration should mention the nodes in the same order they appear.

Respond ONLY with JSON in exactly this shape:
{{
    "title": "Short punchy title (max 50 chars)",
    "diagram": {{
        "nodes": [{{"id": "A", "label": "Client"}}, {{"id": "B", "label": "API Gateway"}}],
        "edges": [{{"from": "A", "to": "B", "label": "request"}}]
    }},
    "scenes": [
        {{"id": 1, "type": "title", "text": "Title shown on screen",
          "narration": "Opening narration in {lang_name} (12-16 words)"}},
        {{"id": 2, "type": "diagram", "caption": "Caption under diagram",
          "narration": "Walk through the diagram in {lang_name} (35-45 words)"}},
        {{"id": 3, "type": "text", "heading": "Key Points",
          "points": ["Specific fact from source", "Another fact", "A third fact"],
          "narration": "Explain the points in order in {lang_name} (30-40 words)"}},
        {{"id": 4, "type": "summary", "text": "One-line takeaway",
          "narration": "Wrap up in {lang_name} (12-16 words)"}}
    ]
}}

Rules:
1. Narration must meet the word counts above (about 2.5 words/second of video).
2. Points are concrete facts or numbers from the source, max 12 words each.
3. Nothing may be invented that is not in the SOURCE CONTENT."""

    def _validate(self, plan: dict) -> dict:
        scenes = plan.get("scenes")
        if not isinstance(scenes, list) or len(scenes) != 4:
            raise ValueError("plan must contain exactly 4 scenes")

        expected = ["title", "diagram", "text", "summary"]
        for i, (scene, kind) in enumerate(zip(scenes, expected), start=1):
            if scene.get("type") != kind:
                raise ValueError(f"scene {i} must be type '{kind}'")
            scene["id"] = i
            if len((scene.get("narration") or "").split()) < 8:
                raise ValueError(f"scene {i} narration too short")

        diagram = plan.get("diagram") or {}
        nodes = diagram.get("nodes") or []
        ids = {n.get("id") for n in nodes}
        if not (2 <= len(nodes) <= MAX_NODES) or len(ids) != len(nodes):
            raise ValueError(f"diagram needs 2-{MAX_NODES} uniquely-identified nodes")
        diagram["edges"] = [
            e for e in (diagram.get("edges") or [])
            if e.get("from") in ids and e.get("to") in ids
        ]
        if not diagram["edges"]:
            raise ValueError("diagram has no valid edges")
        plan["diagram"] = diagram

        points = [p for p in scenes[2].get("points", []) if str(p).strip()]
        if not points:
            raise ValueError("text scene has no points")
        scenes[2]["points"] = [str(p) for p in points[:4]]

        plan["total_duration"] = 0  # real duration comes from the audio clips
        return plan
