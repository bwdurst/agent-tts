"""Player startup and cancellation without a real audio endpoint."""
import threading

from agent_tts import player


def test_queue_start_warms_on_worker_and_stop_cancels(monkeypatch):
    monkeypatch.setattr(player, '_start_keepawake', lambda: None)
    monkeypatch.setattr(player, '_FIRST_PLAY_WARMUP_S', 0.2)
    played = []
    monkeypatch.setattr(player, '_play_one', played.append)
    monkeypatch.setattr(player, '_stop_and_close', lambda alias: None)
    queue = player.PlayerQueue()
    caller = threading.get_ident()
    warmup_threads = []
    real_wait = queue._stop_flag.wait

    def wait(timeout):
        warmup_threads.append(threading.get_ident())
        return real_wait(timeout)

    monkeypatch.setattr(queue._stop_flag, 'wait', wait)
    queue.start()
    queue.enqueue('never-played.mp3')
    queue.stop()
    queue._worker.join(timeout=1)
    assert not queue._worker.is_alive()
    assert warmup_threads and all(t != caller for t in warmup_threads)
    assert not played


def test_repeated_interruptions_keep_mci_on_playback_thread(monkeypatch, tmp_path):
    import time

    class ThreadOwnedMci:
        def __init__(self):
            self.owner = None
            self.commands = []

        def mciSendStringW(self, cmd, buffer, size, callback):
            caller = threading.get_ident()
            self.commands.append((cmd.split()[0], caller))
            if cmd.startswith('open '):
                if self.owner is not None:
                    return 289
                self.owner = caller
            elif self.owner != caller:
                return 257
            elif cmd.startswith('close '):
                self.owner = None
            elif cmd.startswith('status '):
                buffer.value = 'playing'
            return 0

        def mciGetErrorStringW(self, code, buffer, size):
            buffer.value = 'Wrong owner or alias already open'
            return 1

    backend = ThreadOwnedMci()
    monkeypatch.setattr(player, '_winmm', backend)
    monkeypatch.setattr(player, '_content_open', False)
    monkeypatch.setattr(player, '_start_keepawake', lambda: None)
    monkeypatch.setattr(player, '_FIRST_PLAY_WARMUP_S', 0)
    events = []
    queue = player.PlayerQueue(lambda kind, token: events.append((kind, token)))
    queue.start()
    try:
        for i in range(12):
            queue.flush()
            queue.enqueue(tmp_path / 'sample.mp3', i)
            deadline = time.monotonic() + 1
            while ('playing', i) not in events and time.monotonic() < deadline:
                time.sleep(.005)
            assert ('playing', i) in events
            if i % 2:
                queue.skip()
    finally:
        queue.stop()
        queue.join(2)
    assert not queue._worker.is_alive()
    assert not any(kind == 'error' for kind, token in events)
    assert backend.owner is None
    assert {thread for command, thread in backend.commands} == {queue._worker.ident}
    assert sum(command == 'close' for command, thread in backend.commands) == 12
