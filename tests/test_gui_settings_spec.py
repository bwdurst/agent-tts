import pytest

from agent_tts.gui.settings_spec import controls_for, initial_values, settings_to_save


def _by_name(provider):
    return {c.name: c for c in controls_for(provider)}


def test_xai_controls_come_from_its_spec_only():
    names = [c.name for c in controls_for("xai")]
    assert names == ["speed", "language", "text_normalization"]
    for foreign in ("stability", "similarity_boost", "style", "use_speaker_boost"):
        assert foreign not in names


def test_slider_ranges_follow_each_providers_spec():
    assert (_by_name("xai")["speed"].lo, _by_name("xai")["speed"].hi) == (0.7, 1.5)
    assert (_by_name("elevenlabs")["speed"].lo, _by_name("elevenlabs")["speed"].hi) == (0.7, 1.2)
    cart = _by_name("cartesia")
    assert (cart["speed"].lo, cart["speed"].hi) == (0.6, 1.5)
    assert (cart["volume"].lo, cart["volume"].hi) == (0.5, 2.0)


def test_widget_kind_per_setting_kind():
    el = _by_name("elevenlabs")
    assert el["stability"].widget == "slider"
    assert el["use_speaker_boost"].widget == "toggle"
    assert el["model_id"].widget == "choice" and "eleven_v3" in el["model_id"].choices
    assert _by_name("cartesia")["emotion"].widget == "text"


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        controls_for("nope")


def test_initial_values_use_saved_then_default_and_clamp():
    ctrls = controls_for("elevenlabs")
    vals = initial_values("elevenlabs", ctrls, {"speed": 9, "stability": 0.3, "model_id": "bogus"})
    assert vals["speed"] == 1.2          # clamped to the spec's hi
    assert vals["stability"] == 0.3
    assert vals["model_id"] == "eleven_multilingual_v2"  # invalid choice -> default
    assert vals["use_speaker_boost"] is True  # default


def test_initial_values_ignore_other_providers_keys():
    vals = initial_values("xai", controls_for("xai"), {"stability": 0.9, "speed": 1.4})
    assert set(vals) == {"speed", "language", "text_normalization"}
    assert vals["speed"] == 1.4


def test_settings_to_save_skips_untouched_defaults_and_keeps_unknown_keys():
    ctrls = controls_for("xai")
    values = {"speed": 1.0, "language": "auto", "text_normalization": False}
    assert settings_to_save(ctrls, values, {}) == {}
    values["speed"] = 1.35
    out = settings_to_save(ctrls, values, {"custom": 1})
    assert out == {"custom": 1, "speed": 1.35}


def test_settings_to_save_updates_keys_already_in_file_even_at_default():
    ctrls = controls_for("xai")
    values = {"speed": 1.0, "language": "auto", "text_normalization": False}
    assert settings_to_save(ctrls, values, {"speed": 1.2}) == {"speed": 1.0}


def test_initial_values_match_provider_coerce_for_quoted_bool():
    ctrls = controls_for("elevenlabs")
    vals = initial_values("elevenlabs", ctrls, {"use_speaker_boost": "false"})
    assert vals["use_speaker_boost"] is False
