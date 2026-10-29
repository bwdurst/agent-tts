import pytest
import yaml

from agent_tts import config


def _write(path, data):
    path.write_text(yaml.dump(data), encoding="utf-8")


def test_save_keeps_cache_dir_as_written(tmp_path, make_cfg):
    p = tmp_path / "voices.yaml"
    config.save(make_cfg(), p)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["cache_dir"] = "%LOCALAPPDATA%\\agent_tts\\cache"
    p.write_text(yaml.dump(data), encoding="utf-8")
    cfg = config.load(p)
    assert "%" not in str(cfg.cache_dir)
    config.save(cfg, p)
    assert yaml.safe_load(p.read_text(encoding="utf-8"))["cache_dir"] == "%LOCALAPPDATA%\\agent_tts\\cache"


def test_ensure_user_config_copies_example_once(tmp_path):
    example = tmp_path / "voices.example.yaml"
    example.write_text("a: 1\n", encoding="utf-8")
    target = tmp_path / "voices.yaml"
    config.ensure_user_config(target)
    assert target.read_text(encoding="utf-8") == "a: 1\n"
    target.write_text("edited\n", encoding="utf-8")
    config.ensure_user_config(target)
    assert target.read_text(encoding="utf-8") == "edited\n"


def test_roundtrip(tmp_path, make_cfg):
    cfg = make_cfg()
    p = tmp_path / "voices.yaml"
    config.save(cfg, p)
    back = config.load(p)
    assert back.provider == "xai"
    assert back.speakers["ROOK"].provider == "cartesia"
    assert back.speakers["ROOK"].settings == {"speed": 1.2}
    assert back.speakers["_default"].provider == "elevenlabs"
    assert "tool_output" not in yaml.safe_load(p.read_text(encoding="utf-8"))


def test_legacy_file_without_providers_uses_default(tmp_path):
    p = tmp_path / "voices.yaml"
    _write(p, {
        "model": "eleven_multilingual_v2",
        "output_format": "mp3_44100_128",
        "cache_dir": str(tmp_path / "c"),
        "tool_output": "skip",
        "speakers": {
            "KIRA": {"voice_id": "abc", "settings": {"stability": 0.5}},
            "_default": {"voice_id": "abc", "settings": {}},
        },
    })
    cfg = config.load(p)
    # an eleven_* model with no provider marks an ElevenLabs-era file
    assert cfg.provider == "elevenlabs"
    assert cfg.speaker("KIRA").provider == "elevenlabs"
    assert cfg.output_format == "mp3_44100_128"


def test_legacy_file_without_model_defaults_to_xai(tmp_path):
    p = tmp_path / "voices.yaml"
    _write(p, {
        "model": "",
        "cache_dir": str(tmp_path / "c"),
        "speakers": {"_default": {"voice_id": "eve"}},
    })
    assert config.load(p).provider == "xai"


def test_top_level_provider_applies_to_unlabelled_speakers(tmp_path):
    p = tmp_path / "voices.yaml"
    _write(p, {
        "provider": "cartesia",
        "cache_dir": str(tmp_path / "c"),
        "speakers": {"_default": {"voice_id": "v"}},
    })
    assert config.load(p).speaker("ANYONE").provider == "cartesia"


def test_unknown_provider_rejected(tmp_path):
    p = tmp_path / "voices.yaml"
    _write(p, {
        "cache_dir": str(tmp_path / "c"),
        "speakers": {"_default": {"provider": "nope", "voice_id": "v"}},
    })
    with pytest.raises(ValueError, match="unknown provider"):
        config.load(p)


def test_default_speaker_required(tmp_path):
    p = tmp_path / "voices.yaml"
    _write(p, {"cache_dir": str(tmp_path / "c"), "speakers": {"KIRA": {"voice_id": "v"}}})
    with pytest.raises(ValueError, match="_default"):
        config.load(p)


def test_shipped_voices_yaml_loads():
    cfg = config.load("voices.example.yaml")
    assert cfg.speaker("_default").voice_id
