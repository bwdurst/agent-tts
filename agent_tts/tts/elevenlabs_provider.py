"""ElevenLabs text-to-speech adapter.

POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=...
returns audio bytes. Voices come from GET /v2/voices (paginated by
next_page_token). Only eleven_v3 understands inline audio tags such as
[whispers]; other models would read them aloud, so tags are stripped for
those. Voice listing needs the voices_read key permission; synthesis needs
text_to_speech.
"""
from typing import Any
import time

import requests

from agent_tts.tts.base import Provider, SettingSpec, Voice, strip_tags, CatalogLimitError

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
VOICES_URL = "https://api.elevenlabs.io/v2/voices"
MODELS = ("eleven_multilingual_v2", "eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_v3")
TAG_MODELS = ("eleven_v3",)
V3_STABILITY = (0.0, 0.5, 1.0)
_MAX_VOICE_PAGES = 100

_FORMATS = {"mp3": "mp3_44100_128", "wav": "wav_24000"}


class ElevenLabsProvider(Provider):
    name = "elevenlabs"
    env_var = "ELEVENLABS_API_KEY"
    audio_codecs = ("mp3", "wav")
    settings_schema = {
        "model_id": SettingSpec("choice", "eleven_multilingual_v2", choices=MODELS),
        "stability": SettingSpec("float", 0.5, 0.0, 1.0),
        "similarity_boost": SettingSpec("float", 0.75, 0.0, 1.0),
        "style": SettingSpec("float", 0.0, 0.0, 1.0),
        "speed": SettingSpec("float", 1.0, 0.7, 1.2),
        "use_speaker_boost": SettingSpec("bool", True),
    }

    def resolve_settings(self, settings):
        eff = super().resolve_settings(settings)
        if eff["model_id"] in TAG_MODELS:
            # v3 accepts stability only at 0.0, 0.5 or 1.0.
            eff["stability"] = min(V3_STABILITY, key=lambda v: abs(v - eff["stability"]))
        return eff

    def _api_format(self) -> str:
        # A full ElevenLabs format string is passed through untouched.
        fmt = self.output_format.lower()
        return fmt if "_" in fmt else _FORMATS[self.codec]

    def prepare_text(self, text: str, settings: dict[str, Any]) -> str:
        if settings["model_id"] in TAG_MODELS:
            return text
        return strip_tags(text)

    def build_request(self, text: str, voice_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "url": API_URL.format(voice_id=voice_id),
            "params": {"output_format": self._api_format()},
            "json": {
                "text": text,
                "model_id": settings["model_id"],
                "voice_settings": {
                    "stability": settings["stability"],
                    "similarity_boost": settings["similarity_boost"],
                    "style": settings["style"],
                    "speed": settings["speed"],
                    "use_speaker_boost": settings["use_speaker_boost"],
                },
            },
        }

    def _request(self, text: str, voice_id: str, settings: dict[str, Any]) -> bytes:
        req = self.build_request(text, voice_id, settings)
        resp = requests.post(
            req["url"],
            headers={
                "xi-api-key": self.api_key,
                "accept": "audio/mpeg" if self.codec == "mp3" else "audio/*",
                "content-type": "application/json",
            },
            params=req["params"],
            json=req["json"],
            timeout=(5, 30),
        )
        resp.raise_for_status()
        return resp.content

    def list_voices(self) -> list[Voice]:
        out: list[Voice] = []
        deadline = time.monotonic() + 35
        seen_cursors = set()
        token = None
        for _ in range(_MAX_VOICE_PAGES):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise requests.Timeout()
            params: dict[str, Any] = {"page_size": 100}
            if token:
                params["next_page_token"] = token
            resp = requests.get(
                VOICES_URL, headers={"xi-api-key": self.api_key}, params=params, timeout=(min(5, remaining), min(25, remaining))
            )
            resp.raise_for_status()
            payload = resp.json()
            for raw in payload.get("voices", []):
                vid, name = raw.get("voice_id"), raw.get("name")
                if not vid or not name:
                    continue
                labels = {
                    str(k): str(v) for k, v in (raw.get("labels") or {}).items() if v
                }
                if raw.get("description"):
                    labels.setdefault("description", str(raw["description"]))
                out.append(
                    Voice(
                        str(vid),
                        str(name),
                        str(raw.get("category") or ""),
                        labels,
                        str(raw.get("preview_url") or ""),
                    )
                )
            token = payload.get("next_page_token")
            if not payload.get("has_more"):
                break
            if not token or token in seen_cursors:
                raise CatalogLimitError()
            seen_cursors.add(token)
        else:
            raise CatalogLimitError()
        return out

