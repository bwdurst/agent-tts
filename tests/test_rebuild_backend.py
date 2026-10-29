import ctypes
import json
import queue
import threading
import time

import pytest

from agent_tts import config, hotkeys, player
from agent_tts.ingest import transcript


def test_atomic_save_failure_preserves_original(make_cfg, tmp_path, monkeypatch):
    path = tmp_path / "voices.yaml"
    cfg = make_cfg()
    config.save(cfg, path)
    original = path.read_bytes()
    cfg.speakers["KIRA"].voice_id = "new"
    monkeypatch.setattr(config.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(OSError):
        config.save(cfg, path)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_tail_waits_for_complete_line_and_deduplicates(tmp_path):
    path = tmp_path / "session.jsonl"
    path.write_text("", encoding="utf-8")
    stop, ready = threading.Event(), threading.Event()
    received = []

    def listen():
        for text in transcript.tail(path, stop_event=stop, poll_interval=0.01,
                                    on_ready=lambda p: ready.set()):
            received.append(text)  # noqa: PERF402 - observe each live arrival

    worker = threading.Thread(target=listen)
    worker.start()
    assert ready.wait(1)
    event = json.dumps({"type": "assistant", "uuid": "one", "message": {
        "content": [{"type": "text", "text": "KIRA: Hello"}]}})
    with path.open("a", encoding="utf-8") as f:
        f.write(event[:30])
        f.flush()
        time.sleep(0.04)
        assert not received
        f.write(event[30:] + "\n" + event + "\n")
        f.flush()
    deadline = time.monotonic() + 1
    while not received and time.monotonic() < deadline:
        time.sleep(0.01)
    stop.set()
    worker.join(1)
    assert not worker.is_alive()
    assert received == ["KIRA: Hello"]


def test_player_flush_cancels_dequeued_audio_before_open(monkeypatch, tmp_path):
    reached, release = threading.Event(), threading.Event()
    played = []

    def paused_play(path, cancel, on_started):
        reached.set()
        release.wait(1)
        if not cancel.is_set():
            played.append(path)

    monkeypatch.setattr(player, "_play_one", paused_play)
    monkeypatch.setattr(player, "_start_keepawake", lambda: None)
    monkeypatch.setattr(player, "_stop_and_close", lambda alias: None)
    monkeypatch.setattr(player, "_FIRST_PLAY_WARMUP_S", 0)
    pq = player.PlayerQueue()
    pq.start()
    path = tmp_path / "current.wav"
    pending = tmp_path / "pending.wav"
    pq.enqueue(path)
    assert reached.wait(1)
    pq.enqueue(pending)
    assert pq.protected_paths() == {path, pending}
    pq.flush()
    release.set()
    pq.stop()
    pq.join(1)
    assert not pq._worker.is_alive()
    assert not played
    assert pq.protected_paths() == set()


def test_hotkeys_register_unregister_on_same_thread_and_no_leak(monkeypatch):
    messages = queue.Queue()
    calls = []
    ready = threading.Event()

    class FakeUser32:
        def PeekMessageW(self, *args):
            return 0

        def RegisterHotKey(self, hwnd, ident, *args):
            calls.append(("register", ident, threading.get_ident()))
            if ident == 2:
                ready.set()
            return 1

        def UnregisterHotKey(self, hwnd, ident):
            calls.append(("unregister", ident, threading.get_ident()))
            return 1

        def PostThreadMessageW(self, tid, message, *args):
            messages.put(message)
            return 1

        def GetMessageW(self, ptr, *args):
            message = messages.get(timeout=1)
            msg = ctypes.cast(ptr, ctypes.POINTER(hotkeys.wintypes.MSG)).contents
            msg.message = message
            return 0 if message == hotkeys.WM_QUIT else 1

    monkeypatch.setattr(hotkeys, "_user32", FakeUser32())
    for _ in range(20):
        ready.clear()
        hotkeys.register(lambda: None, lambda: None)
        assert ready.wait(1)
        hotkeys.unregister()
        assert not hotkeys._thread.is_alive()
    assert len(calls) == 80
    for offset in range(0, len(calls), 4):
        batch = calls[offset:offset + 4]
        assert [c[0] for c in batch] == ["register", "register", "unregister", "unregister"]
        assert len({c[2] for c in batch}) == 1


def test_auto_switch_reads_arriving_response_and_remembers_position(tmp_path, monkeypatch):
    monkeypatch.setattr(transcript, '_CLAUDE_DIR', tmp_path)
    monkeypatch.setattr(transcript, '_SESSION_CHECK_INTERVAL', .03)
    project = tmp_path / 'project'
    project.mkdir()
    first, second = project / 'first.jsonl', project / 'second.jsonl'

    def append(path, ident):
        with path.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'type': 'assistant', 'uuid': ident, 'message': {
                'content': [{'type': 'text', 'text': ident}]}}) + '\n')

    append(first, 'old-first')
    append(second, 'old-second')
    stop, ready = threading.Event(), threading.Event()
    received = []
    worker = threading.Thread(target=lambda: received.extend(transcript.tail(
        first, stop_event=stop, scan_all_projects=True, poll_interval=.005,
        on_ready=lambda path: ready.set())))
    worker.start()

    def wait_for(text):
        deadline = time.monotonic() + 2
        while text not in received and time.monotonic() < deadline:
            time.sleep(.005)
        assert text in received

    try:
        assert ready.wait(1)
        append(second, 'new-second')
        wait_for('new-second')
        append(first, 'new-first')
        wait_for('new-first')
        append(second, 'second-again')
        wait_for('second-again')
        third = project / 'third.jsonl'
        append(third, 'brand-new-session')
        wait_for('brand-new-session')
    finally:
        stop.set()
        worker.join(1)
    assert received == ['new-second', 'new-first', 'second-again', 'brand-new-session']
