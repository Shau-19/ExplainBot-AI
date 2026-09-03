
import time
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, concatenate_audioclips

WIDTH, HEIGHT = 1280, 720
FPS = 24

COLORS = {
    'bg_dark':    '#0f172a',
    'bg_card':    '#1e293b',
    'accent':     '#3b82f6',
    'text_white': '#f8fafc',
    'text_gray':  '#94a3b8',
}

# Font paths — Liberation Sans ships with fonts-liberation on Debian/Ubuntu
# Falls back through options until one works
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "arial.ttf",  # Windows fallback
]
FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "arialbd.ttf",
]

def _find_font(candidates: list, size: int) -> ImageFont.ImageFont:
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except:
            continue
    return ImageFont.load_default()

def get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    return _find_font(FONT_BOLD_CANDIDATES if bold else FONT_CANDIDATES, size)


class VideoService:
    def __init__(self):
        self.output_dir = Path("outputs/video")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path("outputs/video/temp")
        self.temp_dir.mkdir(exist_ok=True)

    def create_video(self, scenes: list, audio_clips: list, diagram_path: str) -> str:
        print("🎬 Creating synced video...")

        audio_map = {clip['scene_id']: clip for clip in audio_clips}
        video_clips = []
        audio_parts = []

        for i, scene in enumerate(scenes):
            scene_id = scene['id']
            print(f"   Scene {i+1}/{len(scenes)}: {scene['type']}")

            scene_audio = audio_map.get(scene_id)

            if scene_audio:
                scene_duration = scene_audio['duration']
                print(f"      Audio: {scene_duration:.1f}s")
            else:
                scene_duration = scene.get('duration', 5)
                print(f"      ⚠️ No audio, using planned {scene_duration:.1f}s")

            scene['duration'] = scene_duration

            if scene['type'] == 'title':
                clip = self._make_title_scene(scene)
            elif scene['type'] == 'diagram':
                clip = self._make_diagram_scene(scene, diagram_path)
            elif scene['type'] == 'text':
                clip = self._make_text_scene(scene)
            elif scene['type'] == 'summary':
                clip = self._make_summary_scene(scene)
            else:
                clip = self._make_title_scene(scene)

            clip = clip.fadein(0.3).fadeout(0.3)
            video_clips.append(clip)

            if scene_audio:
                audio_parts.append(AudioFileClip(scene_audio['audio_path']))

        print(f"   Combining {len(video_clips)} scenes...")
        final_video = concatenate_videoclips(video_clips, method="compose")

        if audio_parts:
            print(f"   Combining {len(audio_parts)} audio clips...")
            combined_audio = concatenate_audioclips(audio_parts)

            if abs(final_video.duration - combined_audio.duration) > 0.1:
                print(f"   Adjusting sync: video={final_video.duration:.1f}s, audio={combined_audio.duration:.1f}s")
                final_video = final_video.set_duration(combined_audio.duration)

            final_video = final_video.set_audio(combined_audio)

        timestamp = int(time.time())
        output_path = self.output_dir / f"video_{timestamp}.mp4"

        print("   Exporting MP4...")
        final_video.write_videofile(
            str(output_path),
            fps=FPS,
            codec='libx264',
            audio_codec='aac',
            bitrate='3000k',
            preset='ultrafast',
            verbose=False,
            logger=None,
            threads=4,
            temp_audiofile=str(self.temp_dir / "temp_audio.m4a"),
            remove_temp=True
        )

        print(f"✅ Synced video: {output_path.name}")
        return str(output_path)

    # ── Scene Creators ───────────────────────────────────────

    def _make_title_scene(self, scene: dict) -> ImageClip:
        img = Image.new('RGB', (WIDTH, HEIGHT), self._hex(COLORS['bg_dark']))
        draw = ImageDraw.Draw(img)

        draw.rectangle([(0, 0), (WIDTH, 10)], fill=self._hex(COLORS['accent']))

        title = scene.get('text', 'Explanation')
        lines = self._wrap_text(title, max_chars=35)

        y_start = HEIGHT // 2 - (len(lines) * 40)
        for i, line in enumerate(lines[:3]):
            self._draw_centered_text(draw, line, y_start + (i * 75),
                                     size=52, color=COLORS['text_white'], bold=True)

        self._draw_centered_text(draw, "AI Generated Explanation",
                                 HEIGHT // 2 + 130, size=28, color=COLORS['text_gray'])

        draw.rectangle([(0, HEIGHT-10), (WIDTH, HEIGHT)], fill=self._hex(COLORS['accent']))

        cx = WIDTH // 2
        cy = HEIGHT // 2 + 185
        draw.ellipse([(cx-15, cy-15), (cx+15, cy+15)], fill=self._hex(COLORS['accent']))

        return self._img_to_clip(img, scene['duration'])

    def _make_diagram_scene(self, scene: dict, diagram_path: str) -> ImageClip:
        img = Image.new('RGB', (WIDTH, HEIGHT), self._hex(COLORS['bg_dark']))
        draw = ImageDraw.Draw(img)

        draw.rectangle([(0, 0), (WIDTH, 90)], fill=self._hex(COLORS['bg_card']))
        draw.rectangle([(0, 88), (WIDTH, 90)], fill=self._hex(COLORS['accent']))
        self._draw_centered_text(draw, "System Architecture", 28,
                                 size=38, color=COLORS['accent'], bold=True)

        try:
            diagram = Image.open(diagram_path)
            max_size = (WIDTH - 80, HEIGHT - 220)
            diagram.thumbnail(max_size, Image.Resampling.LANCZOS)
            x = (WIDTH - diagram.width) // 2
            img.paste(diagram, (x, 100))
        except Exception as e:
            print(f"⚠️ Diagram error: {e}")
            self._draw_centered_text(draw, "[ Process Diagram ]", HEIGHT // 2,
                                     size=48, color=COLORS['text_gray'])

        caption = scene.get('caption', 'Flow Overview')
        caption_lines = self._wrap_text(caption, max_chars=70)
        draw.rectangle([(0, HEIGHT-100), (WIDTH, HEIGHT)], fill=self._hex(COLORS['bg_card']))
        draw.rectangle([(0, HEIGHT-102), (WIDTH, HEIGHT-100)], fill=self._hex(COLORS['accent']))
        self._draw_centered_text(draw, caption_lines[0], HEIGHT-70, size=28, color=COLORS['text_white'])

        return self._img_to_clip(img, scene['duration'])

    def _make_text_scene(self, scene: dict) -> ImageClip:
        img = Image.new('RGB', (WIDTH, HEIGHT), self._hex(COLORS['bg_dark']))
        draw = ImageDraw.Draw(img)

        heading = scene.get('heading', 'Key Points')
        draw.rectangle([(0, 0), (WIDTH, 110)], fill=self._hex(COLORS['bg_card']))
        draw.rectangle([(0, 108), (WIDTH, 110)], fill=self._hex(COLORS['accent']))
        self._draw_centered_text(draw, heading, 32, size=44, color=COLORS['accent'], bold=True)

        points = scene.get('points', [])[:3]
        y_start = 160
        point_spacing = 155

        for i, point in enumerate(points):
            y = y_start + (i * point_spacing)

            bx, by = 80, y
            draw.ellipse([(bx, by), (bx+55, by+55)], fill=self._hex(COLORS['accent']))

            num_font = get_font(32, bold=True)
            num = str(i+1)
            bbox = draw.textbbox((0, 0), num, font=num_font)
            draw.text((bx + 27 - (bbox[2]-bbox[0])//2, by + 10), num,
                      fill=self._hex(COLORS['text_white']), font=num_font)

            lines = self._wrap_text(point, max_chars=52)
            tf = get_font(28)
            for j, line in enumerate(lines[:2]):
                draw.text((155, y + 5 + j * 35), line,
                          fill=self._hex(COLORS['text_white']), font=tf)

        return self._img_to_clip(img, scene['duration'])

    def _make_summary_scene(self, scene: dict) -> ImageClip:
        img = Image.new('RGB', (WIDTH, HEIGHT), self._hex(COLORS['bg_dark']))
        draw = ImageDraw.Draw(img)

        draw.rectangle([(0, 0), (WIDTH, 10)], fill=self._hex(COLORS['accent']))
        draw.rectangle([(0, HEIGHT-10), (WIDTH, HEIGHT)], fill=self._hex(COLORS['accent']))

        padding = 100
        draw.rectangle(
            [(padding, HEIGHT//2-130), (WIDTH-padding, HEIGHT//2+100)],
            fill=self._hex(COLORS['bg_card']),
            outline=self._hex(COLORS['accent']),
            width=3
        )

        text = scene.get('text', 'Summary')
        lines = self._wrap_text(text, max_chars=45)
        y_start = HEIGHT//2 - (len(lines) * 25)
        for i, line in enumerate(lines[:3]):
            self._draw_centered_text(draw, line, y_start + i * 52,
                                     size=36, color=COLORS['text_white'])

        draw.rectangle([(0, HEIGHT-75), (WIDTH, HEIGHT)], fill=self._hex(COLORS['bg_card']))
        self._draw_centered_text(draw, "ExplainBot AI • Powered by Groq + ElevenLabs",
                                 HEIGHT-48, size=22, color=COLORS['text_gray'])

        return self._img_to_clip(img, scene['duration'])

    # ── Helpers ──────────────────────────────────────────────

    def _wrap_text(self, text: str, max_chars: int = 40) -> list:
        if len(text) <= max_chars:
            return [text]
        words = text.split()
        lines, current = [], []
        for word in words:
            current.append(word)
            if len(' '.join(current)) > max_chars:
                if len(current) > 1:
                    current.pop()
                    lines.append(' '.join(current))
                    current = [word]
        if current:
            lines.append(' '.join(current))
        return lines

    def _hex(self, hex_color: str):
        h = hex_color.lstrip('#')
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def _draw_centered_text(self, draw, text: str, y: int, size: int, color: str, bold: bool = False):
        font = get_font(size, bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        x = max(20, (WIDTH - text_width) // 2)
        draw.text((x, y), text, fill=self._hex(color), font=font)

    def _img_to_clip(self, img: Image.Image, duration: float) -> ImageClip:
        return ImageClip(np.array(img)).set_duration(duration)
