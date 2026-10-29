import queue
import threading
import time
from pathlib import Path

import pytest

from agent_tts import config
from agent_tts.application.controller import Controller, Result
from agent_tts.application.drafts import Drafts, FileChangedError


@pytest.fixture
def drafts(make_cfg, tmp_path):
    path = tmp_path / "voices.yaml"
    config.save(make_cfg(), path)
    return Drafts(path)


def test_save_selected_keeps_other_drafts_and_favorites_independent(drafts):
    drafts.speakers["KIRA"].voice_id = "rex"
    drafts.speakers["ROOK"].voice_id = "other"
    drafts.toggle_favorite("favorite")
    assert config.load(drafts.path).speakers["KIRA"].voice_id == "ara"
    drafts.save_speaker("KIRA")
    saved = config.load(drafts.path)
    assert saved.speakers["KIRA"].voice_id == "rex"
    assert saved.speakers["ROOK"].voice_id == "voice-uuid"
    assert saved.voice_library_favorites == ["favorite"]
    assert drafts.dirty == {"ROOK"}
    drafts.revert("ROOK")
    assert not drafts.dirty


def test_disk_change_requires_reload(drafts):
    drafts.path.write_text(drafts.path.read_text() + "\n# external edit\n")
    original = drafts.path.read_bytes()
    with pytest.raises(FileChangedError):
        drafts.save_speaker("KIRA")
    assert drafts.path.read_bytes() == original


class FakePlayer:
    def __init__(self, on_event):
        self.items = []
        self.on_event = on_event

    def start(self):
        pass

    def enqueue(self, path, speaker):
        self.items.append((path, speaker))

    def protected_paths(self):
        return {item[0] for item in self.items}

    def flush(self):
        self.items.clear()

    def skip(self):
        pass

    def stop(self):
        pass

    def join(self, timeout):
        pass


def pump(controller, results, predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            controller.receive(results.get(timeout=0.01))
        except queue.Empty:
            pass
        if predicate():
            return
    assert predicate(), "timed out waiting for result"


def test_delayed_synth_is_discarded_after_flush_and_next_test_replaces_it(drafts):
    entered, release = threading.Event(), threading.Event()

    class Pool:
        def __init__(self, cfg):
            pass

        def get(self, name):
            return self

        def synth(self, text, *args):
            entered.set()
            release.wait(2)
            return Path(text + ".wav")

    results = queue.Queue()
    controller = Controller(drafts, results.put, lambda *args: None, enable_hotkeys=False,
                            player_factory=FakePlayer, pool_factory=Pool)
    try:
        controller.test_speaker("KIRA", "old")
        assert entered.wait(1)
        controller.test_speaker("KIRA", "new")
        release.set()
        pump(controller, results, lambda: bool(controller._player.items))
        assert [p.name for p, _ in controller._player.items] == ["new.wav"]
    finally:
        controller.close()
        controller._synth_thread.join(1)


def test_twenty_start_stop_cycles_leave_no_transcript_threads(drafts, tmp_path):
    class Pool:
        def __init__(self, cfg):
            pass

        def preflight(self):
            pass

    path = tmp_path / "session.jsonl"
    path.write_text("")
    results = queue.Queue()
    events = []
    baseline = {t.ident for t in threading.enumerate() if t.name.startswith("tts-")}
    controller = Controller(drafts, results.put, lambda *args: events.append(args), enable_hotkeys=False,
                            player_factory=FakePlayer, pool_factory=Pool)
    try:
        for _ in range(20):
            events.clear()
            controller.start(path)
            pump(controller, results, lambda: any(e[0] == "session" for e in events))
            controller.stop()
        for thread in controller._tail_threads:
            thread.join(1)
        assert not any(t.is_alive() for t in controller._tail_threads)
        old = Result(controller.session_gen, "text", "KIRA: wrong", cancel=controller._stop)
        controller.receive(old)
        assert not any(e[0] == "transcript" for e in events)
    finally:
        controller.close()
        controller._synth_thread.join(1)
    remaining = {t.ident for t in threading.enumerate() if t.name.startswith("tts-")}
    assert remaining == baseline


@pytest.mark.parametrize("recorded", [False, True])
def test_preview_recording_or_synthesis_without_assignment(drafts, monkeypatch, recorded):
    from copy import deepcopy

    from agent_tts import voice_library
    from agent_tts.tts.base import Voice
    calls = []
    original = deepcopy(drafts.speakers)

    class Pool:
        def __init__(self, cfg):
            pass

        def get(self, provider):
            calls.append(provider)
            return self

        def synth(self, text, voice_id, settings):
            calls.append((voice_id, settings, text))
            return Path("generated.wav")

    monkeypatch.setattr(voice_library, "download_preview", lambda url, path: Path("recorded.mp3"))
    results = queue.Queue()
    controller = Controller(drafts, results.put, lambda *args: None, enable_hotkeys=False,
                            player_factory=FakePlayer, pool_factory=Pool)
    try:
        voice = Voice("zenith", "Zenith", "", {}, "https://example.com/sample.mp3" if recorded else "")
        controller.preview("xai", voice)
        pump(controller, results, lambda: bool(controller._player.items))
        assert controller._player.items[0] == (Path("recorded.mp3" if recorded else "generated.wav"), (controller.session_gen, "Zenith"))
        assert drafts.speakers == original
        assert not drafts.dirty
        if recorded:
            assert calls == []
        else:
            assert calls[0] == "xai"
            assert calls[1][:2] == ("zenith", {})
        controller.listening = True
        generation = controller.session_gen
        controller.preview("xai", voice)
        assert controller.session_gen == generation
    finally:
        controller.close()
        controller._synth_thread.join(1)


def test_listening_preview_preserves_queue_and_order(drafts):
    from agent_tts.tts.base import Voice
    entered, release = threading.Event(), threading.Event()
    calls=[]
    class Pool:
        def __init__(self,cfg): pass
        def get(self,provider): return self
        def synth(self,text,voice,settings):
            calls.append((text,voice))
            if len(calls)==1:
                entered.set();release.wait(2)
            return Path(str(len(calls))+'.wav')
    results=queue.Queue()
    c=Controller(drafts,results.put,lambda *args:None,enable_hotkeys=False,
                 player_factory=FakePlayer,pool_factory=Pool)
    try:
        c.listening=True
        c._submit_text('KIRA: First dialogue.')
        assert entered.wait(1)
        gen=c.session_gen
        c.preview('xai',Voice('rex','Rex','',{},''))
        c._submit_text('KIRA: Next dialogue.')
        assert c.listening and c.session_gen==gen and not c._stop.is_set()
        release.set()
        pump(c,results,lambda:len(c._player.items)==3)
        assert [token[1] for path,token in c._player.items]==['KIRA','Rex','KIRA']
        assert calls[1][1]=='rex'
        assert calls[0][0]=='First dialogue.' and calls[2][0]=='Next dialogue.'
    finally:
        release.set();c.close();c._synth_thread.join(1)


def test_muted_speaker_is_shown_but_never_synthesized(drafts):
    drafts.speakers["KIRA"].muted = True
    drafts.save_speaker("KIRA")
    synthesized, events = [], []

    class Pool:
        def __init__(self, cfg):
            pass

        def get(self, name):
            return self

        def synth(self, text, *args):
            synthesized.append(text)
            return Path(text + ".wav")

    results = queue.Queue()
    controller = Controller(drafts, results.put, lambda *args: events.append(args), enable_hotkeys=False,
                            player_factory=FakePlayer, pool_factory=Pool)
    try:
        controller._submit_text("KIRA: Quiet one.\n\nROOK: Loud one.")
        pump(controller, results, lambda: bool(controller._player.items))
        assert synthesized == ["Loud one."]
        assert [e[1][0] for e in events if e[0] == "transcript"] == ["KIRA", "ROOK"]
        controller.test_speaker("KIRA", "test")
        assert ("log", "KIRA is muted") in events
        assert synthesized == ["Loud one."]
    finally:
        controller.close()
        controller._synth_thread.join(1)


def test_a_muted_speaker_can_be_saved_without_a_voice(drafts):
    drafts.speakers["KIRA"].voice_id = ""
    with pytest.raises(ValueError):
        drafts.save_speaker("KIRA")
    drafts.speakers["KIRA"].muted = True
    drafts.save_speaker("KIRA")
    assert config.load(drafts.path).speakers["KIRA"].muted is True
