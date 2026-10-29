"""A silent speaker is skipped in the CLI's file and --text modes, with no key configured."""
from types import SimpleNamespace

import pytest

from agent_tts import cli
from agent_tts import player as player_module


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for var in ("XAI_API_KEY", "ELEVENLABS_API_KEY", "CARTESIA_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def all_muted(cfg):
    # preflight builds every provider that any unmuted speaker uses, so mute them all
    for speaker in cfg.speakers.values():
        speaker.muted = True
    return cfg


def test_file_mode_skips_a_muted_speaker_and_needs_no_key(make_cfg, tmp_path, capsys, monkeypatch):
    cfg = all_muted(make_cfg())
    dialogue = tmp_path / "dialogue.txt"
    dialogue.write_text("KIRA: Quiet.", encoding="utf-8")
    monkeypatch.setattr(player_module, "play", lambda path: pytest.fail("played a muted speaker"))
    args = SimpleNamespace(text=None, file=dialogue, speaker=None, dry_run=False)
    assert cli._run_file(args, cfg) == 0
    assert "(muted)" in capsys.readouterr().out


def test_text_mode_skips_a_muted_speaker(make_cfg, capsys, monkeypatch):
    cfg = all_muted(make_cfg())
    monkeypatch.setattr(player_module, "play", lambda path: pytest.fail("played a muted speaker"))
    args = SimpleNamespace(text="hello", file=None, speaker="kira", dry_run=False)
    assert cli._run_file(args, cfg) == 0
    assert "(muted)" in capsys.readouterr().out
