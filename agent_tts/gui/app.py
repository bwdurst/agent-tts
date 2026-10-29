"""Agent TTS Dashboard: window, status bar, and the live TTS pipeline.

Layout (top to bottom): status and controls, Transcript, Voice Settings
(speaker cards beside the provider-tabbed Voice Library), hotkey footer.
A vertical split between Transcript and Voice Settings lets the user trade
height between them.
"""
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from dotenv import load_dotenv

from agent_tts import config as cfgmod
from agent_tts import hotkeys, player
from agent_tts import parser as parsermod
from agent_tts.gui import scrolling, winchrome
from agent_tts.gui.resize_surface import ResizeSurface
from agent_tts.gui.panes import GuidePanedWindow
from agent_tts.gui.theme import (
    BG, DANGER, FG, FG_DIM, FG_MUTED, FONT_TITLE, FONT_UI_SMALL, OK, SPEAKER_COLORS,
)
from agent_tts.gui.transcript_view import TranscriptEvent, TranscriptView
from agent_tts.gui.voice_settings import VoiceSettingsPanel
from agent_tts.gui.widgets import ModernButton, apply_ttk_styles
from agent_tts.ingest import transcript
from agent_tts.normalize import normalize
from agent_tts.parser import ASIDE, CODE
from agent_tts.tts.factory import ProviderPool


class Dashboard:
    def __init__(self, config_path: Path, session_path: str | None = None):
        self.config_path = config_path
        self.session_path = session_path
        self.cfg = cfgmod.load(config_path)
        self.pool: ProviderPool | None = None
        self.pq: player.PlayerQueue | None = None
        self.running = False
        self.stop_event = threading.Event()
        self.transcript_q: queue.Queue[TranscriptEvent] = queue.Queue()
        self._build_ui()

    # ---- services used by the panels -----------------------------------
    def get_pool(self) -> ProviderPool:
        if not self.pool:
            self.pool = ProviderPool(self.cfg)
        return self.pool

    def log(self, msg: str) -> None:
        self.transcript.append_system(msg)

    def play(self, path: Path, speaker: str) -> None:
        if self.pq:
            self.pq.enqueue(path, speaker=speaker)
        else:
            player.play(path)

    # ---- UI construction -------------------------------------------------
    def _build_ui(self) -> None:
        # Both must happen BEFORE tk.Tk(): DPI awareness keeps canvas widgets
        # crisp on HiDPI monitors; the AppUserModelID gives the taskbar our icon.
        winchrome.enable_dpi_awareness()
        winchrome.set_app_user_model_id()

        self.root = tk.Tk()
        self.root.title("Agent TTS")
        self.root.configure(bg=BG)
        self.root.geometry("1280x900")
        self.root.minsize(920, 700)

        # Prefer the local icon mirror: Tk's icon loader is unreliable on UNC paths.
        local_icon = Path(os.environ.get("LOCALAPPDATA", "")) / "agent_tts" / "icon.ico"
        repo_icon = Path(__file__).resolve().parent.parent.parent / "assets" / "icon.ico"
        for candidate in (local_icon, repo_icon):
            if candidate.exists():
                try:
                    self.root.iconbitmap(default=str(candidate))
                    break
                except tk.TclError:
                    continue

        apply_ttk_styles(self.root)
        scrolling.install(self.root)

        self.surface = ResizeSurface(self.root, bg=BG)
        self._build_topbar()

        body = GuidePanedWindow(self.surface, orient="vertical", bg=BG, bd=0, sashwidth=8,
                              opaqueresize=False, proxybackground=FG_MUTED,
                              sashrelief="flat", sashpad=0, borderwidth=0,
                              sashcursor="sb_v_double_arrow")
        body.pack(fill="both", expand=True, padx=18, pady=(0, 6))

        self.transcript = TranscriptView(body)
        body.add(self.transcript, stretch="always", minsize=90, height=140)
        self.voice_settings = VoiceSettingsPanel(body, self)
        body.add(self.voice_settings, stretch="always", minsize=440, height=560)

        footer = tk.Frame(self.surface, bg=BG)
        footer.pack(side="bottom", fill="x", padx=18, pady=(0, 12), before=body)
        tk.Label(footer, text=f"Hotkeys:  {hotkeys.default_label('skip')}  skip     "
                              f"{hotkeys.default_label('flush')}  flush",
                 bg=BG, fg=FG_DIM, font=FONT_UI_SMALL).pack(side="left")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Dark titlebar now, and once more after mapping for Windows builds
        # where DWM needs a second nudge.
        self.root.update_idletasks()
        winchrome.enable_dark_titlebar(self.root)
        self.root.after(40, lambda: winchrome.enable_dark_titlebar(self.root))

    def _build_topbar(self) -> None:
        top = tk.Frame(self.surface, bg=BG)
        top.pack(fill="x", padx=18, pady=(16, 12))

        status = tk.Frame(top, bg=BG)
        status.pack(side="left")
        self.status_dot = tk.Canvas(status, width=14, height=14, bg=BG, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 10), pady=(2, 0))
        self._draw_status_dot(DANGER)
        text = tk.Frame(status, bg=BG)
        text.pack(side="left")
        self.status_title = tk.Label(text, text="Stopped", bg=BG, fg=FG,
                                     font=FONT_TITLE, anchor="w")
        self.status_title.pack(anchor="w")
        self.status_sub = tk.Label(text, text="Press Start to begin listening", bg=BG,
                                   fg=FG_MUTED, font=FONT_UI_SMALL, anchor="w")
        self.status_sub.pack(anchor="w")

        controls = tk.Frame(top, bg=BG)
        controls.pack(side="right")
        self.start_btn = ModernButton(controls, "▶  Start", command=self._on_start,
                                      style="primary")
        self.stop_btn = ModernButton(controls, "■  Stop", command=self._on_stop)
        self.skip_btn = ModernButton(controls, "⏭  Skip", command=self._on_skip)
        self.flush_btn = ModernButton(controls, "⏹  Flush", command=self._on_flush)
        for btn in (self.start_btn, self.stop_btn, self.skip_btn, self.flush_btn):
            btn.pack(side="left", padx=(0, 8))
        for btn in (self.stop_btn, self.skip_btn, self.flush_btn):
            btn.set_enabled(False)

    def _draw_status_dot(self, color: str) -> None:
        self.status_dot.delete("all")
        self.status_dot.create_oval(1, 1, 13, 13, fill=color, outline="")

    def _set_status(self, title: str, subtitle: str, color: str) -> None:
        self.status_title.configure(text=title)
        self.status_sub.configure(text=subtitle)
        self._draw_status_dot(color)

    def _set_running_buttons(self, running: bool) -> None:
        self.start_btn.set_enabled(not running)
        for btn in (self.stop_btn, self.skip_btn, self.flush_btn):
            btn.set_enabled(running)

    # ---- actions -----------------------------------------------------------
    def _on_start(self) -> None:
        if self.running:
            return
        try:
            self.pool = ProviderPool(self.cfg)
            self.pool.preflight()
        except (RuntimeError, ValueError) as e:
            messagebox.showerror("Provider Error", str(e))
            return

        if self.session_path:
            jsonl_path = Path(self.session_path)
        else:
            try:
                jsonl_path = transcript.find_latest_session_anywhere()
            except FileNotFoundError as e:
                messagebox.showerror("Session Not Found", str(e))
                return

        self.running = True
        self.stop_event.clear()
        self.pq = player.PlayerQueue()
        self.pq.start()
        hotkeys.register(on_skip=self._on_skip, on_flush=self._on_flush)

        self._scan_all = not self.session_path
        self.pipeline_thread = threading.Thread(
            target=self._pipeline_loop, args=(jsonl_path,), daemon=True)
        self.pipeline_thread.start()

        self._set_running_buttons(True)
        self._set_status("Listening", f"Tailing  {jsonl_path.name[:8]}…", OK)
        self.transcript.clear_hint_if_shown()
        self._poll_transcript()

    def _on_stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self.stop_event.set()
        if self.pq:
            self.pq.stop()
            self.pq = None
        hotkeys.unregister()
        self._set_running_buttons(False)
        self._set_status("Stopped", "Listening paused", DANGER)

    def _on_skip(self) -> None:
        if not self.pq:
            return
        self.pq.skip()
        # Visible confirmation so the user never wonders if the hotkey registered.
        self.root.after(0, lambda: self.log("⟶ skip"))

    def _on_flush(self) -> None:
        if not self.pq:
            return
        self.pq.flush()
        self.root.after(0, lambda: self.log("⟶ flush"))

    def _on_close(self) -> None:
        if self.voice_settings.dirty:
            resp = messagebox.askyesnocancel(
                "Unsaved changes", "Save changes to voices.yaml before closing?")
            if resp is None:
                return  # Cancel: keep window open
            if resp:
                self.voice_settings.save_all_cards()
        self._on_stop()  # while widgets still exist
        self.root.destroy()

    # ---- pipeline ------------------------------------------------------------
    def _poll_transcript(self) -> None:
        while not self.transcript_q.empty():
            try:
                ev = self.transcript_q.get_nowait()
                self.transcript.append_block(ev.speaker, ev.text)
            except queue.Empty:
                break
        if self.running:
            self.root.after(100, self._poll_transcript)

    def _pipeline_loop(self, jsonl_path: Path) -> None:
        try:
            for text in transcript.tail(
                jsonl_path, from_end=True, stop_event=self.stop_event,
                scan_all_projects=self._scan_all,
            ):
                if not self.running:
                    break
                try:
                    self.cfg = cfgmod.load(self.config_path)
                    self.pool = ProviderPool(self.cfg)
                except Exception as e:
                    # A mid-session edit broke voices.yaml; keep speaking with
                    # the last good config and say why.
                    self.root.after(0, lambda e=e: self.log(f"voices.yaml not reloaded: {e}"))
                for b in parsermod.parse(text, parsermod.speaker_names(self.cfg.speakers)):
                    if not self.running:
                        break
                    if b.speaker == CODE:
                        if self.cfg.code_blocks == "skip":
                            continue
                        sp = self.cfg.speaker("_default")
                    elif b.speaker == ASIDE:
                        if self.cfg.aside_blocks == "skip":
                            continue
                        sp = self.cfg.speaker("_default")
                    else:
                        sp = self.cfg.speaker(b.speaker)

                    self.transcript_q.put(TranscriptEvent(b.speaker, b.text))
                    if sp.muted:
                        continue
                    self._update_status_speaking(b.speaker)

                    synth_text = normalize(b.text, b.speaker, self.cfg.pronunciations)
                    try:
                        audio_path = self.pool.synth(synth_text, sp)
                    except Exception as e:
                        # One failed block (bad voice, vendor error) must not
                        # end the live loop.
                        self.root.after(0, lambda b=b, e=e: self.log(
                            f"synth failed for {b.speaker}: {e}"))
                        continue
                    if self.pq:
                        self.pq.enqueue(audio_path, speaker=b.speaker)

                if self.running:
                    self.root.after(0, lambda: self._set_status(
                        "Listening", "Waiting for next message…", OK))
        except Exception as e:
            self.root.after(0, lambda e=e: self.log(f"listening stopped: {e}"))

    def _update_status_speaking(self, speaker: str) -> None:
        color = SPEAKER_COLORS.get(speaker, FG)
        self.root.after(0, lambda: self._set_status(
            f"Speaking  {speaker}", "Playing block…", color))

    def run(self) -> None:
        self.root.mainloop()
        self._on_stop()


def launch(config_path: Path = Path("voices.yaml"), session: str | None = None) -> None:
    load_dotenv()
    Dashboard(config_path, session).run()
