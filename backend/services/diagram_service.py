
import requests
import base64
import time
from pathlib import Path


class DiagramService:
    def __init__(self):
        self.output_dir = Path("outputs/diagrams")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def mermaid_to_png(self, mermaid_code: str) -> str:
        

        # Clean the mermaid code
        clean_code = mermaid_code.strip()
        if not clean_code.startswith("graph") and not clean_code.startswith("sequenceDiagram"):
            clean_code = "graph TD;\n" + clean_code

        # Encode for URL
        encoded = base64.urlsafe_b64encode(clean_code.encode()).decode()

        url = f"https://mermaid.ink/img/{encoded}?bgColor=white&width=1200&height=600"

        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()

            timestamp = int(time.time())
            output_path = self.output_dir / f"diagram_{timestamp}.png"

            with open(output_path, 'wb') as f:
                f.write(response.content)

            print(f"✅ Diagram rendered: {output_path.name}")
            return str(output_path)

        except Exception as e:
            print(f"⚠️ Mermaid.ink failed: {e}, using fallback")
            return self._create_fallback_diagram(mermaid_code)

    def _create_fallback_diagram(self, mermaid_code: str) -> str:
        """
        Creates simple text-based diagram image if API fails
        """
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new('RGB', (1200, 600), color='#f8f9fa')
        draw = ImageDraw.Draw(img)

        # Draw border
        draw.rectangle([(20, 20), (1180, 580)], outline='#dee2e6', width=3)

        # Draw text
        draw.text((60, 50), "Diagram", fill='#495057')
        draw.text((60, 120), mermaid_code[:200], fill='#6c757d')

        timestamp = int(time.time())
        output_path = self.output_dir / f"diagram_{timestamp}.png"
        img.save(str(output_path))

        return str(output_path)