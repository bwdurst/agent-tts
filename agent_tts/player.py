"""MP3/WAV player using the Windows MCI API via ctypes.

Two modes:
  play(path)  — synchronous, blocks until done. Used by M1 file mode.
  PlayerQueue — threaded queue with skip/flush. Used by M2 live mode.

A background keepawake thread continuously plays a silent WAV loop to hold
the Windows audio endpoint warm across blocks.
"""
import atexit
import ctypes
import logging
import os
import queue
import struct
import tempfile
import threading
import time
from ctypes import c_int, c_uint, c_void_p, c_wchar_p, create_unicode_buffer
from pathlib import Path

_winmm = ctypes.WinDLL("winmm")
_winmm.mciSendStringW.argtypes = [c_wchar_p, c_wchar_p, c_uint, c_void_p]
_winmm.mciSendStringW.restype = c_int
_winmm.mciGetErrorStringW.argtypes = [c_int, c_wchar_p, c_uint]
_winmm.mciGetErrorStringW.restype = c_int

_CONTENT = "agent_tts_content"
_KEEPAWAKE_ROOT = "agent_tts_keepawake"
_KEEPAWAKE_SECONDS = 10.0
_FIRST_PLAY_WARMUP_S = 0.35

_keepawake_started = False
_keepawake_stop = threading.Event()
_keepawake_thread: threading.Thread | None = None
_keepawake_temp_path: Path | None = None
_first_play = True

# _init_lock guards the check-then-set in _start_keepawake so concurrent
# callers from GUI/PlayerQueue can't both spawn the thread + write the temp WAV.
_init_lock = threading.Lock()

# Content-device operations run on the playback thread. Skip/flush signal the
# item's cancellation event; they never issue cross-thread MCI commands.
_alias_lock = threading.Lock()
_content_open = False


def _mci(cmd: str) -> None:
    rv = _winmm.mciSendStringW(cmd, None, 0, None)
    if rv != 0:
        err = create_unicode_buffer(512)
        _winmm.mciGetErrorStringW(rv, err, 512)
        raise RuntimeError(f"MCI {rv}: {err.value} [cmd={cmd!r}]")


def _silent_wav(duration_s: float, sample_rate: int = 44100) -> bytes:
    samples = int(sample_rate * duration_s)
    data = b"\x00\x00" * samples
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + struct.pack("<H", 1)
        + struct.pack("<H", 1)
        + struct.pack("<I", sample_rate)
        + struct.pack("<I", sample_rate * 2)
        + struct.pack("<H", 2)
        + struct.pack("<H", 16)
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


def _close(alias: str) -> None:
    _winmm.mciSendStringW(f"close {alias}", None, 0, None)


def _keepawake_loop(path_str: str) -> None:
    """Keep the Windows audio endpoint continuously active by overlapping two
    silent-WAV aliases. The second alias starts ~500ms before the first ends,
    so there's no gap where the audio graph could go idle and cause the first
    chunk of real content to be played at accelerated speed on recovery.
    """
    aliases = [f"{_KEEPAWAKE_ROOT}_0", f"{_KEEPAWAKE_ROOT}_1"]
    overlap = 0.5  # seconds of concurrent playback during the handoff

    try:
        for a in aliases:
            _mci(f'open "{path_str}" alias {a}')
    except RuntimeError:
        for a in aliases:
            _close(a)
        return

    try:
        # Kick off the first alias — non-blocking so we stay in control of timing.
        _mci(f"play {aliases[0]}")

        i = 0
        while not _keepawake_stop.is_set():
            nxt = aliases[(i + 1) % 2]
            # Wait most of the WAV's duration, then start the next alias while
            # the current one is still producing silent samples.
            if _keepawake_stop.wait(_KEEPAWAKE_SECONDS - overlap):
                break
            try:
                _mci(f"seek {nxt} to start")
                _mci(f"play {nxt}")
            except RuntimeError as e:
                logging.getLogger(__name__).warning("Keepawake: %s", e)
            # Let the overlap play out, then the previous alias naturally ends.
            if _keepawake_stop.wait(overlap):
                break
            i += 1
    finally:
        for a in aliases:
            _close(a)


def _start_keepawake() -> None:
    global _keepawake_started, _keepawake_thread, _keepawake_temp_path
    with _init_lock:
        if _keepawake_started:
            return
        path = Path(tempfile.gettempdir()) / f"agent_tts_keepawake_{os.getpid()}.wav"
        path.write_bytes(_silent_wav(_KEEPAWAKE_SECONDS))
        t = threading.Thread(target=_keepawake_loop, args=(str(path),), daemon=True)
        t.start()
        _keepawake_started = True
        _keepawake_thread = t
        _keepawake_temp_path = path
        atexit.register(_cleanup_keepawake)


def _cleanup_keepawake() -> None:
    """atexit: signal the keepawake thread, give it a brief window to close
    its MCI aliases via the finally-clause, then unlink the temp WAV."""
    _keepawake_stop.set()
    t = _keepawake_thread
    if t is not None:
        t.join(timeout=2.0)
    p = _keepawake_temp_path
    if p is not None:
        try:
            p.unlink(missing_ok=True)
        except OSError as e:
            logging.getLogger(__name__).warning("Keepawake cleanup: %s", e)


def _validate_mci_path(path: Path) -> None:
    s = str(path)
    if '"' in s or "\n" in s or "\r" in s:
        raise ValueError(f"MCI path contains invalid character: {s!r}")


_POLL_INTERVAL_S = 0.05


def _play_one(path: Path, cancel=None, on_started=None) -> None:
    """Open, play, poll, and close on the playback thread.

    MCI devices belong to the thread that opens them. UI/hotkey callers only
    signal cancellation; this thread observes it within 50 ms and closes the
    device before opening the next file.
    """
    global _content_open
    _validate_mci_path(path)
    p = str(path)

    with _alias_lock:
        if cancel is not None and cancel.is_set():
            return
        # Retry cleanup if an earlier close failed; never mark it closed
        # until MCI confirms success.
        if _content_open:
            _mci(f"stop {_CONTENT}")
            _mci(f"close {_CONTENT}")
            _content_open = False
        if path.suffix.lower() == ".mp3":
            _mci(f'open "{p}" type mpegvideo alias {_CONTENT}')
        else:
            _mci(f'open "{p}" alias {_CONTENT}')
        _content_open = True
        try:
            _mci(f"play {_CONTENT}")
        except RuntimeError:
            _mci(f"close {_CONTENT}")
            _content_open = False
            raise

    try:
        if on_started is not None:
            on_started()
        mode_buf = create_unicode_buffer(64)
        while True:
            with _alias_lock:
                if cancel is not None and cancel.is_set():
                    _mci(f"stop {_CONTENT}")
                    return
                if not _content_open:
                    return
                # status {alias} mode returns "playing", "stopped", "paused",
                # "open", "not ready", etc. We break out on anything that
                # isn't "playing".
                mode_buf.value = ""
                result = _winmm.mciSendStringW(
                    f"status {_CONTENT} mode", mode_buf, 64, None
                )
                if result:
                    raise RuntimeError(f"MCI status failed with code {result}")
            if mode_buf.value != "playing":
                break
            time.sleep(_POLL_INTERVAL_S)
    finally:
        with _alias_lock:
            if _content_open:
                _mci(f"close {_CONTENT}")
                _content_open = False


# ---------------------------------------------------------------------------
# Synchronous play — used by M1 file mode
# ---------------------------------------------------------------------------

def play(path: Path) -> None:
    global _first_play
    _start_keepawake()
    if _first_play:
        time.sleep(_FIRST_PLAY_WARMUP_S)
        _first_play = False
    _play_one(path)


# ---------------------------------------------------------------------------
# Queued player — used by M2 live mode
# ---------------------------------------------------------------------------

_SENTINEL = None  # signals the worker to exit


def _stop_and_close(alias: str) -> None:
    """Force-interrupt playback on an alias. `stop` is the documented way to
    cut off an in-progress `play wait`; `close` alone can let the decode
    buffer drain first, which is why Skip/Flush appeared to do nothing.

    For the _CONTENT alias the mutation is performed under _alias_lock and
    the shared _content_open flag is updated, so a concurrent _play_one in
    its finally-clause won't double-close a fresh alias.
    """
    if alias == _CONTENT:
        global _content_open
        with _alias_lock:
            if _content_open:
                _winmm.mciSendStringW(f"stop {alias}", None, 0, None)
                _winmm.mciSendStringW(f"close {alias}", None, 0, None)
                _content_open = False
        return
    _winmm.mciSendStringW(f"stop {alias}", None, 0, None)
    _winmm.mciSendStringW(f"close {alias}", None, 0, None)


class PlayerQueue:
    """Thread-safe playback queue with skip and flush support."""

    def __init__(self, on_event=None) -> None:
        self._q = queue.Queue()
        self._playing = threading.Event()
        self._stop_flag = threading.Event()
        self._lock = threading.RLock()
        self._current = None
        self._pending = {}
        self._on_event = on_event or (lambda *args: None)
        self._worker = threading.Thread(target=self._loop, daemon=True, name="tts-player")

    def start(self) -> None:
        self._worker.start()

    def enqueue(self, path: Path, speaker: str = "") -> None:
        with self._lock:
            if self._stop_flag.is_set():
                return
            item = (Path(path), speaker, threading.Event())
            self._pending[item[2]] = item[0]
            self._q.put(item)

    def protected_paths(self) -> set[Path]:
        with self._lock:
            paths = set(self._pending.values())
            if self._current:
                paths.add(self._current[0])
            return paths

    def skip(self) -> None:
        """Stop the currently playing block, advance to next."""
        with self._lock:
            if self._current:
                self._current[2].set()
            # The playback worker owns the MCI device. Never close it here.

    def flush(self) -> None:
        """Stop current block and clear the entire queue."""
        with self._lock:
            self.skip()
            for cancel in self._pending:
                cancel.set()
            self._pending.clear()
            while not self._q.empty():
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    break

    def stop(self) -> None:
        self._stop_flag.set()
        self.flush()
        self._q.put(_SENTINEL)

    def join(self, timeout=None) -> None:
        self._worker.join(timeout)

    def _loop(self) -> None:
        # Warm the audio endpoint off the UI thread; Stop can cancel the wait.
        _start_keepawake()
        if self._stop_flag.wait(_FIRST_PLAY_WARMUP_S):
            return
        while not self._stop_flag.is_set():
            item = self._q.get()
            if item is _SENTINEL:
                break
            path, speaker, cancel = item
            with self._lock:
                self._pending.pop(cancel, None)
                if cancel.is_set() or self._stop_flag.is_set():
                    continue
                self._current = item
            self._playing.set()
            try:
                _play_one(path, cancel, lambda speaker=speaker: self._on_event("playing", speaker))
            except (RuntimeError, ValueError) as e:
                logging.getLogger(__name__).warning("Playback failed: %s", e)
                self._on_event("error", speaker)
            finally:
                with self._lock:
                    self._current = None
                self._playing.clear()
                self._on_event("finished", speaker)
