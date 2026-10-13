import os
import time
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from moviepy.editor import AudioFileClip

OPENAI_VOICE_BY_LANG = {
    "en": "fable",    # warm, natural, storytelling
    "hi": "alloy",     # evals: alloy ~= nova on Hindi CER (0.28), slightly better WER; onyx/shimmer worse (evals/README.md)
    "es": "alloy",
    "de": "onyx",
    "fr": "shimmer",
    "default": "fable"
}


class HybridTTSService:

    VOICE_ID = "pNInz6obpgDQGcFmaJgB"
    FILE_MAX_AGE_SECONDS = 3600

    def __init__(self):
        self.output_dir = Path("outputs/audio")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.el_char_limit = 10000
        self.state_file = Path("outputs/.tts_state.json")

        self._load_state()
        self._init_elevenlabs()
        self._init_openai()

    def _load_state(self):
        if self.state_file.exists():
            try:
                state = json.loads(self.state_file.read_text())
                self.el_chars_used = state.get("el_chars_used", 0)
                self.el_quota_exhausted = state.get("el_quota_exhausted", False)
                return
            except Exception:
                pass
        self.el_chars_used = 0
        self.el_quota_exhausted = False

    def _save_state(self):
        try:
            self.state_file.write_text(json.dumps({
                "el_chars_used": self.el_chars_used,
                "el_quota_exhausted": self.el_quota_exhausted
            }))
        except Exception as e:
            print(f"⚠️ Could not save TTS state: {e}")

    def _init_elevenlabs(self):
        key = os.getenv("ELEVENLABS_API_KEY")
        if key:
            try:
                from elevenlabs.client import ElevenLabs
                self.el_client = ElevenLabs(api_key=key)
                print("✅ ElevenLabs TTS ready")
            except Exception as e:
                self.el_client = None
                print(f"⚠️ ElevenLabs init failed: {e}")
        else:
            self.el_client = None
            print("⚠️ No ElevenLabs key found")

    def _init_openai(self):
        key = os.getenv("OPENAI_API_KEY")
        if key:
            try:
                from openai import OpenAI
                self.oai_client = OpenAI(api_key=key)
                print("✅ OpenAI TTS ready (fallback)")
            except Exception as e:
                self.oai_client = None
                print(f"⚠️ OpenAI init failed: {e}")
        else:
            self.oai_client = None
            print("⚠️ No OpenAI key found")

    # ── Public ──────────────────────────────────────────────

    def generate_audio(self, text: str, language: str = "en") -> dict:
        char_count = len(text)
        timestamp = int(time.time())

        print(f"🎤 Generating audio ({char_count} chars, lang: {language})")

        if self._should_use_elevenlabs(char_count):
            try:
                result = self._generate_elevenlabs(text, timestamp)
                result.update({"provider": "elevenlabs", "characters": char_count, "language": language})
                self.el_chars_used += char_count
                self._save_state()
                print("✅ ElevenLabs audio generated")
                return result
            except Exception as e:
                error_str = str(e)
                print(f"⚠️ ElevenLabs failed: {error_str}, trying OpenAI...")
                if "quota_exceeded" in error_str or "401" in error_str:
                    self.el_quota_exhausted = True
                    self._save_state()
                    print("⚠️ ElevenLabs blocked — switching to OpenAI permanently")

        if self.oai_client:
            try:
                result = self._generate_openai(text, timestamp, language)
                result.update({"provider": "openai", "characters": char_count, "language": language})
                print("✅ OpenAI audio generated")
                return result
            except Exception as e:
                print(f"❌ OpenAI also failed: {e}")

        raise Exception("Both TTS providers failed. Check API keys and quotas.")

    def generate_audio_batch(self, scenes: list, language: str = "en") -> list:
        print(f"🎤 Generating {len(scenes)} audio clips...")
        self._cleanup_old_files()

        def synth(scene):
            narration = scene.get("narration", "").strip()
            if len(narration) < 5:
                print(f"   ⚠️ Scene {scene['id']}: No narration, skipping")
                return None
            try:
                result = self.generate_audio(text=narration, language=language)
                print(f"   ✅ Scene {scene['id']}: {result['duration_actual']:.1f}s via {result['provider']}")
                return {
                    "scene_id": scene["id"],
                    "audio_path": result["audio_path"],
                    "filename": result["filename"],
                    "duration": result["duration_actual"],
                    "provider": result["provider"]
                }
            except Exception as e:
                print(f"   ❌ Scene {scene['id']} audio failed: {e}")
                return None

        # Scenes are independent, so synthesise them concurrently (map keeps scene order)
        with ThreadPoolExecutor(max_workers=max(1, min(len(scenes), 6))) as pool:
            return [r for r in pool.map(synth, scenes) if r]

    def get_status(self) -> dict:
        el_available = self.el_client is not None and not self.el_quota_exhausted
        return {
            "elevenlabs": {
                "available": el_available,
                "quota_exhausted": self.el_quota_exhausted,
                "chars_used": self.el_chars_used,
                "chars_remaining": max(0, self.el_char_limit - self.el_chars_used)
            },
            "openai": {"available": self.oai_client is not None},
            "active_provider": "elevenlabs" if el_available else "openai"
        }

    # ── Private ─────────────────────────────────────────────

    def _should_use_elevenlabs(self, char_count: int) -> bool:
        if not self.el_client or self.el_quota_exhausted:
            return False
        remaining = self.el_char_limit - self.el_chars_used
        if remaining < char_count:
            print(f"⚠️ ElevenLabs quota low: {remaining} chars remaining")
            return False
        return True

    def _get_actual_duration(self, path: str) -> float:
        try:
            clip = AudioFileClip(path)
            duration = clip.duration
            clip.close()
            return duration
        except Exception:
            return 0.0

    def _generate_elevenlabs(self, text: str, timestamp: int) -> dict:
        audio_bytes = b"".join(self.el_client.text_to_speech.convert(
            text=text,
            voice_id=self.VOICE_ID,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128"
        ))
        if not audio_bytes:
            raise Exception("ElevenLabs returned empty audio")

        filename = f"el_{timestamp}_{uuid.uuid4().hex[:6]}.mp3"
        output_path = self.output_dir / filename
        output_path.write_bytes(audio_bytes)

        actual = self._get_actual_duration(str(output_path))
        return {
            "audio_path": str(output_path),
            "filename": filename,
            "duration_estimate": len(text.split()) / 2.5,
            "duration_actual": actual
        }

    def _generate_openai(self, text: str, timestamp: int, language: str = "en") -> dict:
        voice = OPENAI_VOICE_BY_LANG.get(language, OPENAI_VOICE_BY_LANG["default"])
        response = self.oai_client.audio.speech.create(
            model="tts-1-hd", voice=voice, input=text, speed=1.0
        )
        filename = f"oai_{timestamp}_{uuid.uuid4().hex[:6]}.mp3"
        output_path = self.output_dir / filename
        response.stream_to_file(str(output_path))

        actual = self._get_actual_duration(str(output_path))
        return {
            "audio_path": str(output_path),
            "filename": filename,
            "duration_estimate": len(text.split()) / 2.5,
            "duration_actual": actual
        }

    def _cleanup_old_files(self):
        now = time.time()
        deleted = 0
        for f in self.output_dir.glob("*.mp3"):
            if now - f.stat().st_mtime > self.FILE_MAX_AGE_SECONDS:
                try:
                    f.unlink()
                    deleted += 1
                except Exception:
                    pass
        if deleted:
            print(f"🧹 Cleaned up {deleted} old audio file(s)")
