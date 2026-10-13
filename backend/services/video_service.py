
import time
import math
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, VideoClip, AudioFileClip, concatenate_videoclips, concatenate_audioclips

WIDTH, HEIGHT = 1280, 720
FPS = 12

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

    def create_video(self, scenes: list, audio_clips: list, diagram: dict) -> str:
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
            scene['_idx'], scene['_total'] = i, len(scenes)

            if scene['type'] == 'title':
                clip = self._make_title_scene(scene)
            elif scene['type'] == 'diagram':
                clip = self._make_diagram_scene(scene, diagram)
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

    def _make_diagram_scene(self, scene: dict, diagram: dict) -> VideoClip:
        """Native diagram: nodes + edges drawn with Pillow, revealed step by step
        so the picture builds up in the order the narration describes it."""
        nodes = diagram['nodes']
        edges = diagram['edges']
        positions = self._layout(len(nodes))
        index = {n['id']: i for i, n in enumerate(nodes)}
        caption = self._wrap_text(scene.get('caption', 'Flow Overview'), max_chars=70)[0]

        states = []
        for k in range(len(nodes)):
            img = Image.new('RGB', (WIDTH, HEIGHT), self._hex(COLORS['bg_dark']))
            draw = ImageDraw.Draw(img)
            self._header(draw, "How It Works")

            for e in edges:
                i, j = index[e['from']], index[e['to']]
                if max(i, j) <= k:
                    self._draw_arrow(draw, positions[i], positions[j], e.get('label'))
            for i in range(k + 1):
                self._draw_node(draw, positions[i], nodes[i]['label'], active=(i == k))

            draw.rectangle([(0, HEIGHT-100), (WIDTH, HEIGHT)], fill=self._hex(COLORS['bg_card']))
            draw.rectangle([(0, HEIGHT-102), (WIDTH, HEIGHT-100)], fill=self._hex(COLORS['accent']))
            self._draw_centered_text(draw, caption, HEIGHT-70, size=28, color=COLORS['text_white'])
            self._decorate(draw, scene)
            states.append(np.array(img))

        return self._reveal_clip(states, scene['duration'])

    def _make_text_scene(self, scene: dict) -> VideoClip:
        heading = scene.get('heading', 'Key Points')
        points = scene.get('points', [])[:4]
        row = 120

        states = []
        for k in range(len(points)):
            img = Image.new('RGB', (WIDTH, HEIGHT), self._hex(COLORS['bg_dark']))
            draw = ImageDraw.Draw(img)
            self._header(draw, heading)

            for i in range(k + 1):
                y = 170 + i * row
                current = (i == k)
                fill = COLORS['accent'] if current else COLORS['bg_card']
                draw.ellipse([(90, y), (150, y + 60)], fill=self._hex(fill),
                             outline=self._hex(COLORS['accent']), width=3)
                num_font = get_font(32, bold=True)
                bbox = draw.textbbox((0, 0), str(i + 1), font=num_font)
                draw.text((120 - (bbox[2]-bbox[0])//2, y + 8), str(i + 1),
                          fill=self._hex(COLORS['text_white']), font=num_font)
                color = COLORS['text_white'] if current else COLORS['text_gray']
                for j, line in enumerate(self._wrap_text(points[i], max_chars=58)[:2]):
                    draw.text((185, y + 2 + j * 34), line, fill=self._hex(color), font=get_font(30))
            self._decorate(draw, scene)
            states.append(np.array(img))

        return self._reveal_clip(states, scene['duration'])

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
        self._draw_centered_text(draw, "ExplainBot AI • Powered by GPT-5.6 Luna",
                                 HEIGHT-48, size=22, color=COLORS['text_gray'])

        self._decorate(draw, scene)
        return self._img_to_clip(img, scene['duration'])

    # ── Diagram / animation helpers ────────────────────────────

    NODE_W, NODE_H = 250, 100

    def _reveal_clip(self, states: list, duration: float) -> VideoClip:
        """Show states[k] from t = 0.8 * duration * k / n; the last one holds to the end."""
        n = len(states)
        starts = [0.8 * duration * k / n for k in range(n)]

        def make_frame(t):
            k = max(i for i, st in enumerate(starts) if st <= t)
            return states[k]

        return VideoClip(make_frame, duration=duration)

    def _layout(self, n: int) -> list:
        """Centre points for n nodes: one row up to 4, otherwise two snaking rows
        so consecutive nodes are always neighbours."""
        cols = n if n <= 4 else math.ceil(n / 2)
        rows = math.ceil(n / cols)
        x0, x1 = 60 + self.NODE_W // 2, WIDTH - 60 - self.NODE_W // 2
        y_mid = (110 + HEIGHT - 110) // 2
        row_gap = 190
        pts = []
        for i in range(n):
            r, c = divmod(i, cols)
            if r % 2 == 1:
                c = cols - 1 - c
            x = (x0 + x1) // 2 if cols == 1 else x0 + (x1 - x0) * c // (cols - 1)
            y = y_mid + int((r - (rows - 1) / 2) * row_gap)
            pts.append((x, y))
        return pts

    def _draw_node(self, draw, center: tuple, label: str, active: bool):
        cx, cy = center
        w, h = self.NODE_W, self.NODE_H
        box = [(cx - w // 2, cy - h // 2), (cx + w // 2, cy + h // 2)]
        draw.rounded_rectangle(
            box, radius=16,
            fill=self._hex(COLORS['accent'] if active else COLORS['bg_card']),
            outline=self._hex(COLORS['accent']), width=3
        )
        lines = self._wrap_text(label, max_chars=16)[:2]
        font = get_font(26, bold=True)
        total_h = len(lines) * 32
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            draw.text((cx - (bbox[2] - bbox[0]) // 2, cy - total_h // 2 + i * 32),
                      line, fill=self._hex(COLORS['text_white']), font=font)

    def _edge_point(self, src: tuple, dst: tuple) -> tuple:
        """Point where the line from src's centre toward dst leaves src's box."""
        dx, dy = dst[0] - src[0], dst[1] - src[1]
        if dx == 0 and dy == 0:
            return src
        sx = (self.NODE_W / 2) / abs(dx) if dx else float('inf')
        sy = (self.NODE_H / 2) / abs(dy) if dy else float('inf')
        t = min(sx, sy)
        return (src[0] + dx * t, src[1] + dy * t)

    def _draw_arrow(self, draw, src: tuple, dst: tuple, label):
        a, b = self._edge_point(src, dst), self._edge_point(dst, src)
        color = self._hex(COLORS['text_gray'])
        draw.line([a, b], fill=color, width=4)

        angle = math.atan2(b[1] - a[1], b[0] - a[0])
        size = 16
        head = [
            b,
            (b[0] - size * math.cos(angle - 0.4), b[1] - size * math.sin(angle - 0.4)),
            (b[0] - size * math.cos(angle + 0.4), b[1] - size * math.sin(angle + 0.4)),
        ]
        draw.polygon(head, fill=color)

        if label:
            font = get_font(22)
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.rectangle([(mx - tw/2 - 6, my - th/2 - 24), (mx + tw/2 + 6, my + th/2 - 6)],
                           fill=self._hex(COLORS['bg_dark']))
            draw.text((mx - tw/2, my - th/2 - 26), label,
                      fill=self._hex(COLORS['accent']), font=font)

    def _header(self, draw, text: str):
        draw.rectangle([(0, 0), (WIDTH, 110)], fill=self._hex(COLORS['bg_card']))
        draw.rectangle([(0, 108), (WIDTH, 110)], fill=self._hex(COLORS['accent']))
        self._draw_centered_text(draw, text, 32, size=44, color=COLORS['accent'], bold=True)

    def _decorate(self, draw, scene: dict):
        """Scene-progress dots, bottom-right."""
        total = scene.get('_total')
        if not total:
            return
        y = HEIGHT - 28
        for i in range(total):
            x = WIDTH - 40 - (total - 1 - i) * 26
            on = (i <= scene.get('_idx', 0))
            draw.ellipse([(x - 7, y - 7), (x + 7, y + 7)],
                         fill=self._hex(COLORS['accent'] if on else COLORS['text_gray']))

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
