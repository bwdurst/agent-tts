"""Session lifecycle. Workers post results; the UI dispatches receive on its thread."""
import hashlib
import logging
import queue
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import requests

from agent_tts import hotkeys, parser, player, voice_library
from agent_tts.config import SpeakerConfig
from agent_tts.ingest import transcript
from agent_tts.normalize import normalize
from agent_tts.tts.factory import ProviderPool


@dataclass
class Result:
    gen: int
    kind: str
    data: object = None
    ack: threading.Event | None = None
    cancel: threading.Event | None = None


def error_message(exc):
    """Do not include HTTP headers, bodies, or signed preview URLs in diagnostics."""
    if isinstance(exc, requests.HTTPError):
        code = exc.response.status_code if exc.response is not None else "unknown"
        return f"Provider returned HTTP {code}. Check account access and API credentials."
    if isinstance(exc, requests.Timeout):
        return "Provider timed out. Try again."
    if isinstance(exc, requests.RequestException):
        return "Could not reach the provider. Check the network connection."
    return str(exc)


class Controller:
    def __init__(self, drafts, post, notify, *, enable_hotkeys=True,
                 player_factory=player.PlayerQueue, pool_factory=ProviderPool):
        self.drafts = drafts
        self.post = post
        self.notify = notify
        self.pool_factory = pool_factory
        self.enable_hotkeys = enable_hotkeys
        self.session_gen = 0
        self.listening = False
        self.closed = False
        self._stop = threading.Event()
        self._tail_threads = []
        self._jobs = queue.Queue()
        self._catalog_loading = set()
        self.catalogs = {}
        self._player = player_factory(on_event=self._player_event)
        self._player_started = False
        self._synth_thread = threading.Thread(target=self._audio_loop, daemon=True, name="tts-synthesis")
        self._synth_thread.start()

    def _emit(self, result):
        if not self.closed:
            self.post(result)
        elif result.ack:
            result.ack.set()

    def _player_event(self, kind, token):
        gen, speaker = token
        self._emit(Result(gen, "player", (kind, speaker)))

    def receive(self, result):
        """The single acceptance boundary for asynchronous results (UI thread only)."""
        try:
            if result.kind in ("catalog", "catalog_error"):
                provider = result.data[0]
                self._catalog_loading.discard(provider)
            if self.closed or result.gen != self.session_gen or (result.cancel and result.cancel.is_set()):
                if not self.closed and result.kind in ("catalog", "catalog_error"):
                    self.fetch_catalog(provider)
                return
            kind, data = result.kind, result.data
            if kind == "audio":
                path, speaker = data
                if not self._player_started:
                    self._player.start()
                    self._player_started = True
                self._player.enqueue(path, (result.gen, speaker))
            elif kind == "text":
                self._submit_text(data)
            elif kind == "catalog":
                self.catalogs[data[0]] = data[1]
                self.notify(kind, data)
            elif kind == "fatal":
                self.stop()
                self.notify("error", data)
            elif kind == "hotkey":
                self.skip() if data == "skip" else self.flush()
            else:
                self.notify(kind, data)
        finally:
            if result.ack:
                result.ack.set()

    def start(self, session=None, source="both", include_progress=False):
        if self.listening:
            return
        self.flush()
        self.listening = True
        self._stop = threading.Event()
        stop = self._stop
        cfg = deepcopy(self.drafts.saved)
        gen = self.session_gen
        if self.enable_hotkeys:
            try:
                hotkeys.register(
                    lambda: self._emit(Result(self.session_gen, "hotkey", "skip")),
                    lambda: self._emit(Result(self.session_gen, "hotkey", "flush")),
                    lambda message: self._emit(Result(gen, "error", message)))
            except RuntimeError as exc:
                self.notify("error", str(exc))
        self.notify("state", True)
        self.notify("status", "Finding session…")

        def listen(origin):
            try:
                self.pool_factory(cfg).preflight()
                ready = lambda label: self._emit(Result(self.session_gen, "session", label, cancel=stop))
                if session:
                    stream = transcript.tail(Path(session), from_end=True, stop_event=stop,
                        include_progress=include_progress,
                        on_ready=lambda p: ready(f"{origin.title()}: {p}"))
                else:
                    stream = transcript.follow(origin, stop_event=stop, include_progress=include_progress,
                        on_ready=ready,
                        on_error=lambda message: self._emit(Result(self.session_gen, "error", message, cancel=stop)))
                for text in stream:
                    if stop.is_set():
                        break
                    self._emit(Result(self.session_gen, "text", text, cancel=stop))
            except Exception as exc:  # noqa: BLE001 - worker/UI error boundary
                if not stop.is_set():
                    self._emit(Result(self.session_gen, "fatal" if session else "error",
                                      f"{origin.title()}: {error_message(exc)}", cancel=stop))

        origins = (["codex" if Path(session).name.startswith("rollout-") else "claude"] if session else
                   ["claude", "codex"] if source == "both" else [source])
        self._tail_threads = [t for t in self._tail_threads if t.is_alive()]
        for origin in origins:
            thread = threading.Thread(target=listen, args=(origin,), daemon=True, name=f"tts-transcript-{origin}")
            self._tail_threads.append(thread)
            thread.start()

    def stop(self):
        self._stop.set()
        self.listening = False
        self.flush()
        if self.enable_hotkeys:
            hotkeys.unregister()
        self.notify("state", False)
        self.notify("status", "Stopped")

    def skip(self):
        self._player.skip()
        self.notify("log", "Skipped current audio")

    def flush(self):
        self.session_gen += 1
        self._player.flush()
        self.notify("status", "Listening — queue cleared" if self.listening else "Ready")

    def _submit_text(self, text):
        cfg = deepcopy(self.drafts.saved)
        for block in parser.parse(text):
            if block.speaker == parser.CODE and cfg.code_blocks == "skip":
                continue
            if block.speaker == parser.ASIDE and cfg.aside_blocks == "skip":
                continue
            self.notify("transcript", (block.speaker, block.text))
            self._jobs.put((self.session_gen, "synth", cfg, block.speaker,
                            deepcopy(cfg.speaker(block.speaker)), block.text))

    def test_speaker(self, name, text):
        if self.listening:
            return
        self.flush()
        cfg = deepcopy(self.drafts.saved)
        self.notify("transcript", (name, text))
        self._jobs.put((self.session_gen, "synth", cfg, name,
                        deepcopy(self.drafts.speakers[name]), text))

    def preview(self, provider, voice):
        if self.listening:
            self.notify("log", f"Preview queued for {voice.name}; listening continues")
            self.notify("status", f"Preview queued for {voice.name} after pending dialogue")
        else:
            self.flush()
        cfg = deepcopy(self.drafts.saved)
        if voice.preview_url:
            self._jobs.put((self.session_gen, "preview", cfg, voice.name, provider, voice))
        else:
            self._jobs.put((self.session_gen, "synth", cfg, voice.name,
                            SpeakerConfig(provider, voice.voice_id, {}),
                            "Hello! Here is a short preview of this voice. How does it sound?"))

    def _audio_loop(self):
        # One network lane preserves dialogue order and keeps auditions from
        # spawning unbounded requests. Old generations are skipped before work.
        while True:
            job = self._jobs.get()
            if job is None:
                return
            gen, kind, cfg, name, target, text = job
            if self.closed or gen != self.session_gen:
                continue
            try:
                self._emit(Result(gen, "status", f"Preparing audio for {name}…"))
                if kind == "preview":
                    key = hashlib.sha256(f"{target}:{text.voice_id}".encode()).hexdigest()
                    path = voice_library.download_preview(text.preview_url, cfg.cache_dir / "voice_previews" / f"{key}.mp3")
                else:
                    provider = self.pool_factory(cfg).get(target.provider)
                    provider.cache_keep = self._player.protected_paths
                    path = provider.synth(normalize(text, name, cfg.pronunciations),
                                          target.voice_id, target.settings)
                # Main-thread acknowledgement means this file is queued (and
                # eviction-protected) before the next synthesis can evict it.
                ack = threading.Event()
                self._emit(Result(gen, "audio", (path, name), ack))
                while not ack.wait(0.05):
                    if self.closed:
                        return
            except Exception as exc:  # noqa: BLE001 - worker/UI error boundary
                message = f"{name}: {error_message(exc)}"
                logging.getLogger(__name__).warning(message)
                self._emit(Result(gen, "error", message))

    def fetch_catalog(self, provider, refresh=False):
        if provider in self._catalog_loading:
            return
        if provider in self.catalogs and not refresh:
            self.notify("catalog", (provider, self.catalogs[provider]))
            return
        self._catalog_loading.add(provider)
        gen, cfg = self.session_gen, deepcopy(self.drafts.saved)
        self.notify("catalog_loading", provider)

        def fetch():
            try:
                voices = self.pool_factory(cfg).get(provider).list_voices()
                self._emit(Result(gen, "catalog", (provider, voices)))
            except Exception as exc:  # noqa: BLE001 - worker/UI error boundary
                self._emit(Result(gen, "catalog_error", (provider, error_message(exc))))

        threading.Thread(target=fetch, daemon=True, name=f"tts-catalog-{provider}").start()

    def close(self):
        self.closed = True
        self.session_gen += 1
        self._stop.set()
        self._jobs.put(None)
        self._player.stop()
        if self.enable_hotkeys:
            hotkeys.stop()
        deadline = time.monotonic() + 2.0
        if self._player_started:
            self._player.join(max(0, deadline - time.monotonic()))
        if self.enable_hotkeys:
            hotkeys.join(max(0, deadline - time.monotonic()))
