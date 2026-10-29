import pytest
import requests

from agent_tts.config import Config, SpeakerConfig


@pytest.fixture
def make_cfg(tmp_path):
    def _make(**over):
        speakers = {
            "KIRA": SpeakerConfig("xai", "ara", {}),
            "ROOK": SpeakerConfig("cartesia", "voice-uuid", {"speed": 1.2}),
            "_default": SpeakerConfig("elevenlabs", "vid", {}),
        }
        kw = dict(
            provider="xai",
            output_format="mp3",
            lead_in_text="",
            cache_dir=tmp_path / "cache",
            cache_max_mb=500,
            code_blocks="skip",
            aside_blocks="skip",
            speakers=speakers,
        )
        kw.update(over)
        return Config(**kw)

    return _make


class FakeResponse:
    def __init__(self, content=b"AUDIO", json_data=None, status=200):
        self.content = content
        self._json = json_data
        self.status_code = status

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))
