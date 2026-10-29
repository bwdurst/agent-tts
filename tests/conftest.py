import keyring
import pytest
import requests
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from agent_tts.config import Config, SpeakerConfig


class MemoryKeyring(KeyringBackend):
    """Tests never touch the real Windows Credential Manager."""

    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise PasswordDeleteError("not found")
        del self.store[(service, username)]


@pytest.fixture(autouse=True)
def memory_keyring():
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


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
