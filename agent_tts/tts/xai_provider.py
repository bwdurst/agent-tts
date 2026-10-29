"""xAI text-to-speech adapter.

POST https://api.x.ai/v1/tts returns audio bytes directly. Expression is
driven by inline tags in the text ([pause], [laugh]) and wrapping tags
(<whisper>...</whisper>), so text passes through unchanged. Voices come from
GET /v1/tts/voices as {"voices": [{voice_id, name, language, gender}]}.
"""
from typing import Any

import requests

from agent_tts.tts.base import Provider, SettingSpec, Voice

API_URL = "https://api.x.ai/v1/tts"
VOICES_URL = "https://api.x.ai/v1/tts/voices"
# xAI documents 60,000 characters per unary request.
MAX_CHARS = 60000


class XAIProvider(Provider):
    name = "xai"
    env_var = "XAI_API_KEY"
    audio_codecs = ("mp3", "wav")
    settings_schema = {
        "speed": SettingSpec("float", 1.0, 0.7, 1.5),
        "text_normalization": SettingSpec("bool", False),
        "language": SettingSpec("str", "auto"),
    }

    def _output_format(self) -> dict[str, Any]:
        if self.codec == "wav":
            return {"codec": "wav", "sample_rate": 44100}
        return {"codec": "mp3", "sample_rate": 44100, "bit_rate": 128000}

    def build_request(self, text: str, voice_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        if len(text) > MAX_CHARS:
            raise ValueError(f"text is {len(text)} chars; xAI accepts at most {MAX_CHARS}")
        return {
            "text": text,
            "voice_id": voice_id,
            "language": settings["language"],
            "speed": settings["speed"],
            "text_normalization": settings["text_normalization"],
            "output_format": self._output_format(),
        }

    def _request(self, text: str, voice_id: str, settings: dict[str, Any]) -> bytes:
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=self.build_request(text, voice_id, settings),
            timeout=(5, 30),
        )
        resp.raise_for_status()
        return resp.content

    def list_voices(self) -> list[Voice]:
        resp = requests.get(
            VOICES_URL,
            headers={"Authorization": f"Bearer {self.api_key}", "accept": "application/json"},
            timeout=(5, 30),
        )
        resp.raise_for_status()
        out = []
        for raw in resp.json().get("voices", []):
            vid, name = raw.get("voice_id"), raw.get("name")
            if not vid or not name:
                continue
            labels = {k: str(raw[k]) for k in ("language", "gender") if raw.get(k)}
            out.append(Voice(str(vid), str(name), "", labels, str(raw.get("preview_url") or "")))
        return out
