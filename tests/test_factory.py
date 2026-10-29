import pytest

from agent_tts.tts import factory
from agent_tts.tts.cartesia_provider import CartesiaProvider
from agent_tts.tts.elevenlabs_provider import ElevenLabsProvider
from agent_tts.tts.xai_provider import XAIProvider


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for var in ("XAI_API_KEY", "ELEVENLABS_API_KEY", "CARTESIA_API_KEY"):
        monkeypatch.setenv(var, "test-key")


def test_registry_has_three_providers():
    assert set(factory.PROVIDERS) == {"xai", "elevenlabs", "cartesia"}


def test_unknown_provider():
    with pytest.raises(ValueError, match="unknown provider"):
        factory.provider_class("nope")


def test_pool_routes_by_name(make_cfg):
    pool = factory.ProviderPool(make_cfg())
    assert isinstance(pool.get("xai"), XAIProvider)
    assert isinstance(pool.get("elevenlabs"), ElevenLabsProvider)
    assert isinstance(pool.get("cartesia"), CartesiaProvider)
    assert pool.get("xai") is pool.get("xai")


def test_pool_passes_cache_settings(make_cfg, tmp_path):
    cfg = make_cfg(cache_max_mb=7, lead_in_text="lead ")
    p = factory.ProviderPool(cfg).get("xai")
    assert p.cache_max_mb == 7 and p.lead_in_text == "lead " and p.cache_dir == tmp_path / "cache"


def test_missing_key_names_variable_only_for_used_provider(make_cfg, monkeypatch):
    monkeypatch.delenv("CARTESIA_API_KEY")
    pool = factory.ProviderPool(make_cfg())
    assert pool.get("xai")
    with pytest.raises(RuntimeError, match="CARTESIA_API_KEY"):
        pool.get("cartesia")


def test_preflight_checks_every_provider_in_use(make_cfg, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        factory.ProviderPool(make_cfg()).preflight()


def test_pool_synth_uses_speaker_voice_and_provider(make_cfg, monkeypatch):
    cfg = make_cfg()
    pool = factory.ProviderPool(cfg)
    seen = {}

    def fake(self, text, voice_id, settings):
        seen.update(provider=self.name, voice=voice_id, settings=settings)
        return b"AUDIO"

    monkeypatch.setattr(CartesiaProvider, "_request", fake)
    path = pool.synth("hello", cfg.speakers["ROOK"])
    assert path.read_bytes() == b"AUDIO"
    assert seen["provider"] == "cartesia" and seen["voice"] == "voice-uuid"
    assert seen["settings"]["speed"] == 1.2


def test_unsupported_output_format(make_cfg):
    cfg = make_cfg(output_format="ogg")
    with pytest.raises(ValueError, match="not supported"):
        factory.ProviderPool(cfg).get("xai")
