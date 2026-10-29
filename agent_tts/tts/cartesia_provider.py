"""Cartesia text-to-speech adapter.

POST https://api.cartesia.ai/tts/bytes with a Cartesia-Version header returns
audio bytes. Voices come from GET /voices, paginated with has_more and
next_page (passed back as starting_after). Sonic-3 understands [laughter] and
<break time="1s"/>; other bracket or wrapping tags are stripped so they are
not read aloud. Emotion is set per speaker through generation_config.
"""
from typing import Any
import time

import requests

from agent_tts.tts.base import Provider, SettingSpec, Voice, strip_tags, CatalogLimitError

API_URL = "https://api.cartesia.ai/tts/bytes"
VOICES_URL = "https://api.cartesia.ai/voices"
API_VERSION = "2026-08-14"
MODELS = ("sonic-3.6", "sonic-3.5", "sonic-3", "sonic-latest")
KEEP_TAGS = ("[laughter]",)
_MAX_VOICE_PAGES = 100


class CartesiaProvider(Provider):
    name = "cartesia"
    env_var = "CARTESIA_API_KEY"
    audio_codecs = ("mp3", "wav")
    settings_schema = {
        "model_id": SettingSpec("choice", "sonic-3.6", choices=MODELS),
        "language": SettingSpec("str", "en"),
        "speed": SettingSpec("float", 1.0, 0.6, 1.5),
        "volume": SettingSpec("float", 1.0, 0.5, 2.0),
        "emotion": SettingSpec("str", ""),
    }

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Cartesia-Version": API_VERSION}

    def prepare_text(self, text: str, settings: dict[str, Any]) -> str:
        # <break .../> self-closing tags are valid Sonic-3 markup and are
        # not matched by the wrapping-tag pattern's name-only form.
        return strip_tags(text, keep=KEEP_TAGS)

    def _output_format(self) -> dict[str, Any]:
        if self.codec == "wav":
            return {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100}
        return {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000}

    def build_request(self, text: str, voice_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        gen: dict[str, Any] = {"speed": settings["speed"], "volume": settings["volume"]}
        if settings["emotion"]:
            gen["emotion"] = settings["emotion"]
        return {
            "model_id": settings["model_id"],
            "transcript": text,
            "voice": {"id": voice_id},
            "language": settings["language"],
            "output_format": self._output_format(),
            "generation_config": gen,
        }

    def _request(self, text: str, voice_id: str, settings: dict[str, Any]) -> bytes:
        resp = requests.post(
            API_URL,
            headers={**self._headers(), "Content-Type": "application/json"},
            json=self.build_request(text, voice_id, settings),
            timeout=(5, 30),
        )
        resp.raise_for_status()
        return resp.content

    def list_voices(self) -> list[Voice]:
        out: list[Voice] = []
        deadline = time.monotonic() + 35
        seen_cursors = set()
        cursor = None
        for _ in range(_MAX_VOICE_PAGES):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise requests.Timeout()
            params: dict[str, Any] = {"limit": 100}
            if cursor:
                params["starting_after"] = cursor
            resp = requests.get(VOICES_URL, headers=self._headers(), params=params, timeout=(min(5, remaining), min(25, remaining)))
            resp.raise_for_status()
            payload = resp.json()
            for raw in payload.get("data", []):
                vid, name = raw.get("id"), raw.get("name")
                if not vid or not name:
                    continue
                labels = {
                    k: str(raw[k])
                    for k in ("description", "gender", "language")
                    if raw.get(k)
                }
                if raw.get("country"):
                    labels["accent"] = str(raw["country"])
                if raw.get("tagline"):
                    labels["use_case"] = str(raw["tagline"])
                out.append(Voice(str(vid), str(name), "", labels, ""))
            cursor = payload.get("next_page")
            if not payload.get("has_more"):
                break
            if not cursor or cursor in seen_cursors:
                raise CatalogLimitError()
            seen_cursors.add(cursor)
        else:
            raise CatalogLimitError()
        return out

