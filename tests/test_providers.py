import pytest
import requests

from agent_tts.tts import base
from agent_tts.tts import cartesia_provider as car
from agent_tts.tts import elevenlabs_provider as el
from agent_tts.tts import xai_provider as xai
from tests.conftest import FakeResponse


def make(cls, tmp_path, fmt="mp3", **kw):
    return cls("test-key", fmt, tmp_path, **kw)


# ---- interface ------------------------------------------------------------
def test_resolve_settings_fills_defaults_clamps_and_drops_unknown(tmp_path):
    p = make(xai.XAIProvider, tmp_path)
    eff = p.resolve_settings({"speed": 9, "stability": 0.4, "use_speaker_boost": True})
    assert eff == {"speed": 1.5, "text_normalization": False, "language": "auto"}


def test_resolve_settings_rejects_bad_choice(tmp_path):
    p = make(el.ElevenLabsProvider, tmp_path)
    with pytest.raises(ValueError, match="model_id"):
        p.resolve_settings({"model_id": "nope"})


def test_every_provider_declares_schema_and_defaults_resolve(tmp_path):
    for cls in (xai.XAIProvider, el.ElevenLabsProvider, car.CartesiaProvider):
        assert cls.settings_schema and cls.name and cls.env_var
        make(cls, tmp_path).resolve_settings({})


def test_placeholder_voice_rejected_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: pytest.fail("network"))
    with pytest.raises(ValueError, match="no voice assigned"):
        make(xai.XAIProvider, tmp_path).synth("hi", base.PLACEHOLDER_VOICE, {})


def test_synth_caches_and_namespaces(tmp_path, monkeypatch):
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        return FakeResponse(b"AUDIO")

    monkeypatch.setattr("requests.post", fake_post)
    a = make(xai.XAIProvider, tmp_path)
    p1 = a.synth("hello", "ara", {})
    p2 = a.synth("hello", "ara", {})
    assert p1 == p2 and len(calls) == 1
    c = make(car.CartesiaProvider, tmp_path)
    p3 = c.synth("hello", "ara", {})
    assert p3 != p1 and len(calls) == 2


def test_synth_ignores_irrelevant_settings_in_cache_key(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: FakeResponse(b"A"))
    p = make(xai.XAIProvider, tmp_path)
    assert p.synth("hi", "ara", {}) == p.synth("hi", "ara", {"stability": 0.9})


def test_synth_empty_audio_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: FakeResponse(b""))
    with pytest.raises(RuntimeError, match="empty audio"):
        make(xai.XAIProvider, tmp_path).synth("hi", "ara", {})


def test_synth_http_error_propagates_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: FakeResponse(b"x", status=401))
    with pytest.raises(requests.HTTPError):
        make(xai.XAIProvider, tmp_path).synth("hi", "ara", {})
    assert list(tmp_path.glob("*.mp3")) == []


def test_synth_enforces_cache_limit(tmp_path, monkeypatch):
    big = b"x" * (600 * 1024)
    monkeypatch.setattr("requests.post", lambda *a, **k: FakeResponse(big))
    p = make(xai.XAIProvider, tmp_path, cache_max_mb=1)
    first = p.synth("one", "ara", {})
    second = p.synth("two", "ara", {})
    assert second.exists() and not first.exists()


def test_lead_in_is_prepended(tmp_path, monkeypatch):
    sent = {}
    monkeypatch.setattr(
        "requests.post", lambda url, **kw: sent.update(kw) or FakeResponse(b"A")
    )
    make(xai.XAIProvider, tmp_path, lead_in_text="Hm. ").synth("hi", "ara", {})
    assert sent["json"]["text"] == "Hm. hi"


def test_strip_tags():
    assert base.strip_tags("Well [hmm] <whisper>ok</whisper> [laughter]") == "Well ok"
    assert base.strip_tags("[laughter] ha", keep=("[laughter]",)) == "[laughter] ha"
    assert base.strip_tags("see [1] list") == "see [1] list"


# ---- xAI ------------------------------------------------------------------
def test_xai_request(tmp_path, monkeypatch):
    sent = {}

    def fake_post(url, **kw):
        sent.update(url=url, **kw)
        return FakeResponse(b"A")

    monkeypatch.setattr("requests.post", fake_post)
    make(xai.XAIProvider, tmp_path).synth("hello [pause] there", "ara", {"speed": 1.1})
    assert sent["url"] == "https://api.x.ai/v1/tts"
    assert sent["headers"]["Authorization"] == "Bearer test-key"
    assert sent["json"] == {
        "text": "hello [pause] there",
        "voice_id": "ara",
        "language": "auto",
        "speed": 1.1,
        "text_normalization": False,
        "output_format": {"codec": "mp3", "sample_rate": 44100, "bit_rate": 128000},
    }


def test_xai_wav_and_text_limit(tmp_path):
    p = make(xai.XAIProvider, tmp_path, fmt="wav")
    assert p.build_request("a", "v", p.resolve_settings({}))["output_format"]["codec"] == "wav"
    with pytest.raises(ValueError, match="at most"):
        p.build_request("a" * 60001, "v", p.resolve_settings({}))


def test_xai_list_voices(tmp_path, monkeypatch):
    payload = {"voices": [
        {"voice_id": "ara", "name": "Ara", "language": "multilingual", "gender": "female"},
        {"name": "no id"},
    ]}
    monkeypatch.setattr("requests.get", lambda url, **kw: FakeResponse(json_data=payload))
    voices = make(xai.XAIProvider, tmp_path).list_voices()
    assert [(v.voice_id, v.name, v.labels["gender"]) for v in voices] == [("ara", "Ara", "female")]


# ---- ElevenLabs -----------------------------------------------------------
def test_elevenlabs_request(tmp_path, monkeypatch):
    sent = {}

    def fake_post(url, **kw):
        sent.update(url=url, **kw)
        return FakeResponse(b"A")

    monkeypatch.setattr("requests.post", fake_post)
    make(el.ElevenLabsProvider, tmp_path).synth(
        "hi [whispers] there", "VID", {"stability": 0.3, "model_id": "eleven_flash_v2_5"}
    )
    assert sent["url"].endswith("/v1/text-to-speech/VID")
    assert sent["headers"]["xi-api-key"] == "test-key"
    assert sent["params"] == {"output_format": "mp3_44100_128"}
    assert sent["json"]["model_id"] == "eleven_flash_v2_5"
    assert sent["json"]["text"] == "hi there"  # tags stripped for non-v3
    assert sent["json"]["voice_settings"]["stability"] == 0.3
    assert set(sent["json"]["voice_settings"]) == {
        "stability", "similarity_boost", "style", "speed", "use_speaker_boost"
    }


def test_elevenlabs_v3_keeps_tags(tmp_path):
    p = make(el.ElevenLabsProvider, tmp_path)
    eff = p.resolve_settings({"model_id": "eleven_v3"})
    assert p.prepare_text("hi [whispers]", eff) == "hi [whispers]"


def test_elevenlabs_legacy_format_string_passes_through(tmp_path):
    p = make(el.ElevenLabsProvider, tmp_path, fmt="mp3_44100_192")
    assert p.codec == "mp3" and p._api_format() == "mp3_44100_192"
    assert make(el.ElevenLabsProvider, tmp_path, fmt="wav")._api_format() == "wav_24000"


def test_elevenlabs_list_voices_paginates(tmp_path, monkeypatch):
    pages = [
        {"voices": [{"voice_id": "a", "name": "A", "category": "premade",
                     "labels": {"gender": "male"}, "preview_url": "http://p/a"}],
         "has_more": True, "next_page_token": "t1"},
        {"voices": [{"voice_id": "b", "name": "B", "description": "warm"}],
         "has_more": False},
    ]
    seen = []

    def fake_get(url, **kw):
        seen.append(kw["params"].get("next_page_token"))
        return FakeResponse(json_data=pages[len(seen) - 1])

    monkeypatch.setattr("requests.get", fake_get)
    voices = make(el.ElevenLabsProvider, tmp_path).list_voices()
    assert [v.voice_id for v in voices] == ["a", "b"]
    assert seen == [None, "t1"]
    assert voices[0].preview_url == "http://p/a" and voices[1].labels["description"] == "warm"


# ---- Cartesia -------------------------------------------------------------
def test_cartesia_request(tmp_path, monkeypatch):
    sent = {}

    def fake_post(url, **kw):
        sent.update(url=url, **kw)
        return FakeResponse(b"A")

    monkeypatch.setattr("requests.post", fake_post)
    make(car.CartesiaProvider, tmp_path).synth(
        "hi [hmm] [laughter]", "UUID", {"emotion": "calm", "speed": 1.2}
    )
    assert sent["url"] == "https://api.cartesia.ai/tts/bytes"
    assert sent["headers"]["Authorization"] == "Bearer test-key"
    assert sent["headers"]["Cartesia-Version"] == car.API_VERSION
    assert sent["json"] == {
        "model_id": "sonic-3.6",
        "transcript": "hi [laughter]",
        "voice": {"id": "UUID"},
        "language": "en",
        "output_format": {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000},
        "generation_config": {"speed": 1.2, "volume": 1.0, "emotion": "calm"},
    }


def test_cartesia_omits_empty_emotion_and_wav_format(tmp_path):
    p = make(car.CartesiaProvider, tmp_path, fmt="wav")
    req = p.build_request("t", "v", p.resolve_settings({}))
    assert "emotion" not in req["generation_config"]
    assert req["output_format"] == {
        "container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100
    }


def test_cartesia_list_voices_paginates(tmp_path, monkeypatch):
    pages = [
        {"data": [{"id": "1", "name": "One", "gender": "feminine", "language": "en",
                   "tagline": "Guide", "country": "US", "description": "d"}],
         "has_more": True, "next_page": "cur"},
        {"data": [{"id": "2", "name": "Two"}], "has_more": False, "next_page": None},
    ]
    seen = []

    def fake_get(url, **kw):
        seen.append(kw["params"].get("starting_after"))
        return FakeResponse(json_data=pages[len(seen) - 1])

    monkeypatch.setattr("requests.get", fake_get)
    voices = make(car.CartesiaProvider, tmp_path).list_voices()
    assert [v.voice_id for v in voices] == ["1", "2"]
    assert seen == [None, "cur"]
    assert voices[0].labels["use_case"] == "Guide" and voices[0].labels["accent"] == "US"


# ---- review fixes ---------------------------------------------------------
def test_strip_tags_leaves_ordinary_prose():
    text = "Return a Promise<string> from the <Dashboard> component [see notes]"
    assert base.strip_tags(text) == text


def test_elevenlabs_v3_snaps_stability(tmp_path):
    p = make(el.ElevenLabsProvider, tmp_path)
    assert p.resolve_settings({"model_id": "eleven_v3", "stability": 0.3})["stability"] == 0.5
    assert p.resolve_settings({"model_id": "eleven_v3", "stability": 0.9})["stability"] == 1.0
    assert p.resolve_settings({"stability": 0.3})["stability"] == 0.3


def test_synth_leaves_no_temp_files(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: FakeResponse(b"A"))
    make(xai.XAIProvider, tmp_path).synth("hi", "ara", {})
    assert [f.suffix for f in tmp_path.iterdir()] == [".mp3"]


def test_eviction_survives_locked_file(tmp_path, monkeypatch):
    from pathlib import Path

    from agent_tts.tts import cache

    (tmp_path / "a.mp3").write_bytes(b"x" * 2 * 1024 * 1024)
    real = Path.unlink

    def locked(self, *a, **k):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", locked)
    assert cache.evict(tmp_path, max_mb=1) == 0
    monkeypatch.setattr(Path, "unlink", real)
