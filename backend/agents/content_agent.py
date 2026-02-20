
from groq import Groq
import os


LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "default": "English"
}


class ContentAgent:
    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = "llama-3.1-8b-instant"

    def generate_explanation(
        self,
        query: str,
        context: str,
        format_type: str,
        language: str = "en"
    ) -> dict:
        lang_name = LANGUAGE_NAMES.get(language, LANGUAGE_NAMES["default"])

        if format_type in ['audio', 'video']:
            system_msg = f"You write natural narration scripts for audio explanations. Use conversational language, short sentences. No bullet points. Always respond in {lang_name}."
            format_instruction = f"Write as a spoken narration script in {lang_name}. Conversational, clear, 100-150 words."
        else:
            system_msg = f"You are a helpful technical explainer. Be clear and concise. Always respond in {lang_name}."
            format_instruction = f"Write a clear technical explanation in {lang_name}."

        prompt = f"""Based on this content:
{context[:2000]}

Answer this question:
{query}

{format_instruction}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )

            text = response.choices[0].message.content

            return {
                'text': text,
                'script': text if format_type in ['audio', 'video'] else None
            }

        except Exception as e:
            print(f"Content agent error: {e}")
            return {
                'text': f"Error generating explanation: {e}",
                'script': None
            }