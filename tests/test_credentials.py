"""Key storage: the credential store beats the environment; nothing real is touched."""
import keyring
import pytest
from keyring.errors import KeyringError

from agent_tts import credentials
from agent_tts.config import SpeakerConfig
from agent_tts.tts.factory import ProviderPool, create, provider_class

VAR = "XAI_API_KEY"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("XAI_API_KEY", "ELEVENLABS_API_KEY", "CARTESIA_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_saved_key_wins_over_environment(monkeypatch):
    monkeypatch.setenv(VAR, "from-env")
    assert credentials.lookup(VAR) == ("from-env", credentials.ENVIRONMENT)
    credentials.save(VAR, "  from-app  ")
    assert credentials.lookup(VAR) == ("from-app", credentials.SAVED)
    assert credentials.status(VAR) == (True, True)
    assert credentials.delete(VAR) is True
    assert credentials.lookup(VAR) == ("from-env", credentials.ENVIRONMENT)
    assert credentials.delete(VAR) is False


def test_blank_key_is_rejected_and_nothing_found():
    with pytest.raises(ValueError):
        credentials.save(VAR, "   ")
    assert credentials.lookup(VAR) is None
    assert credentials.status(VAR) == (False, False)


def test_unreadable_store_does_not_hide_an_environment_key(monkeypatch):
    monkeypatch.setenv(VAR, "from-env")

    def broken(*args):
        raise KeyringError("locked")

    monkeypatch.setattr(keyring, "get_password", broken)
    assert credentials.lookup(VAR) == ("from-env", credentials.ENVIRONMENT)
    with pytest.raises(credentials.CredentialError):
        credentials._saved(VAR)


def test_provider_is_built_from_the_saved_key(tmp_path):
    with pytest.raises(RuntimeError, match="Providers"):
        create("xai", "mp3", tmp_path)
    credentials.save(VAR, "saved-key")
    assert create("xai", "mp3", tmp_path).api_key == "saved-key"


def test_key_is_not_stored_where_the_repo_could_pick_it_up(tmp_path, memory_keyring):
    credentials.save(VAR, "secret-value")
    assert list(tmp_path.iterdir()) == []
    assert memory_keyring.store == {(credentials.SERVICE, VAR): "secret-value"}


def test_muted_speaker_needs_no_provider_key(make_cfg):
    cfg = make_cfg()
    cfg.speakers["KIRA"] = SpeakerConfig("xai", "ara", {}, muted=True)
    cfg.speakers["ROOK"] = SpeakerConfig("cartesia", "v", {}, muted=True)
    cfg.speakers["_default"] = SpeakerConfig("elevenlabs", "v", {}, muted=True)
    ProviderPool(cfg).preflight()  # no keys anywhere, nothing in use, no error
    cfg.speakers["KIRA"].muted = False
    with pytest.raises(RuntimeError):
        ProviderPool(cfg).preflight()
    assert provider_class("xai").env_var == VAR


class WindowsLikeError(Exception):
    """Stand-in for pywintypes.error, which is not a KeyringError."""


def test_any_backend_failure_is_handled_not_just_keyring_errors(monkeypatch):
    monkeypatch.setenv(VAR, "from-env")

    def broken(*args):
        raise WindowsLikeError(1312, "CredRead", "A specified logon session does not exist.")

    monkeypatch.setattr(keyring, "get_password", broken)
    monkeypatch.setattr(keyring, "set_password", broken)
    monkeypatch.setattr(keyring, "delete_password", broken)
    assert credentials.lookup(VAR) == ("from-env", credentials.ENVIRONMENT)
    assert credentials.status(VAR) == (False, True)
    with pytest.raises(credentials.CredentialError):
        credentials.save(VAR, "key")
    with pytest.raises(credentials.CredentialError):
        credentials.delete(VAR)
