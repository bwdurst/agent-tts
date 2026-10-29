"""One speaker's card: provider, voice id, and the controls that provider's
settings spec defines (nothing else)."""
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from agent_tts.gui.library_model import tab_label
from agent_tts.gui.settings_spec import Control, controls_for, initial_values
from agent_tts.gui.theme import (
    ACCENT, BG, BG_ELEV, BORDER, FG, FG_MUTED, FONT_MONO,
    FONT_SECTION, FONT_UI, FONT_UI_SMALL, SPEAKER_COLORS,
)
from agent_tts.gui.widgets import ModernButton, ModernSlider, ToggleSwitch


class SpeakerCard(tk.Frame):
    def __init__(self, parent, name: str, provider: str, voice_id: str,
                 settings: dict[str, Any], *, on_dirty: Callable[[str], None],
                 on_browse: Callable[[str], None], on_test: Callable[[str], None],
                 on_save: Callable[[str], None], on_revert: Callable[[str], None]):
        super().__init__(parent, bg=BG_ELEV, highlightthickness=2,
                         highlightbackground=BG_ELEV, highlightcolor=BG_ELEV)
        self.name = name
        self._color = SPEAKER_COLORS.get(name, FG)
        self._on_dirty = on_dirty
        self.provider = provider
        self._getters: dict[str, Callable[[], Any]] = {}
        self._setters: dict[str, Callable[[Any], None]] = {}
        self._controls: list[Control] = []
        self._muted = False  # suppress dirty callbacks while loading values

        tk.Frame(self, bg=self._color, width=4).pack(side="left", fill="y")
        inner = tk.Frame(self, bg=BG_ELEV)
        inner.pack(side="left", fill="both", expand=True, padx=14, pady=12)

        header = tk.Frame(inner, bg=BG_ELEV)
        header.pack(fill="x", pady=(0, 6))
        tk.Label(header, text=name, bg=BG_ELEV, fg=self._color,
                 font=FONT_SECTION).pack(side="left")
        self.badge = tk.Label(header, bg=BG, fg=FG_MUTED, font=FONT_UI_SMALL,
                              padx=8, pady=2)
        self.badge.pack(side="left", padx=(10, 0))

        voice_row = tk.Frame(inner, bg=BG_ELEV)
        voice_row.pack(fill="x", pady=(0, 6))
        tk.Label(voice_row, text="voice id", bg=BG_ELEV, fg=FG_MUTED, font=FONT_UI,
                 anchor="w", width=14).pack(side="left")
        self.voice_id = tk.StringVar(value=voice_id)
        entry = tk.Entry(voice_row, textvariable=self.voice_id, bg=BG, fg=FG,
                         insertbackground=ACCENT, font=FONT_MONO, relief="flat",
                         highlightthickness=2, highlightbackground=BORDER,
                         highlightcolor=ACCENT, bd=0)
        entry.pack(side="left", fill="x", expand=True, ipady=5, ipadx=6, padx=(4, 0))
        self.voice_id.trace_add("write", lambda *_: self._changed())

        self.grid_frame = tk.Frame(inner, bg=BG_ELEV)
        self.grid_frame.pack(fill="x")
        self.grid_frame.columnconfigure(1, weight=1)

        actions = tk.Frame(inner, bg=BG_ELEV)
        actions.pack(fill="x", pady=(8, 0))
        ModernButton(actions, "⌕  Browse", command=lambda: on_browse(name),
                     padx=10, pady=6, font=FONT_UI_SMALL).pack(side="left")
        ModernButton(actions, "▶  Test", command=lambda: on_test(name),
                     padx=10, pady=6, font=FONT_UI_SMALL).pack(side="right")
        ModernButton(actions, "Save", command=lambda: on_save(name),
                     padx=10, pady=6, font=FONT_UI_SMALL).pack(side="right", padx=(0, 6))
        ModernButton(actions, "↺  Revert", command=lambda: on_revert(name),
                     padx=10, pady=6, font=FONT_UI_SMALL).pack(side="right", padx=(0, 6))

        self._rebuild(provider, settings)

    # ---- state -----------------------------------------------------------
    def _changed(self) -> None:
        if not self._muted:
            self._on_dirty(self.name)

    @property
    def controls(self) -> list[Control]:
        return self._controls

    def values(self) -> dict[str, Any]:
        """Current value of every control, keyed by setting name."""
        return {c.name: self._getters[c.name]() for c in self._controls}

    def load(self, provider: str, voice_id: str, settings: dict[str, Any]) -> None:
        """Replace provider, voice and control values without marking dirty."""
        self._muted = True
        try:
            self.voice_id.set(voice_id)
            self._rebuild(provider, settings)
        finally:
            self._muted = False

    def change_provider(self, provider: str) -> None:
        """Switch vendor from the library. Controls reset to the new provider's
        defaults because the old vendor's values mean nothing to it."""
        if provider == self.provider:
            return
        self._rebuild(provider, {})
        self._changed()

    def set_selected(self, on: bool) -> None:
        edge = ACCENT if on else BG_ELEV
        self.configure(highlightbackground=edge, highlightcolor=edge)

    # ---- control construction -------------------------------------------
    def _rebuild(self, provider: str, settings: dict[str, Any]) -> None:
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.provider = provider
        self.badge.configure(text=tab_label(provider))
        self._controls = controls_for(provider)
        self._getters.clear()
        self._setters.clear()
        values = initial_values(provider, self._controls, settings)
        previous, self._muted = self._muted, True
        try:
            for row, control in enumerate(self._controls):
                self._add_row(row, control, values[control.name])
        finally:
            self._muted = previous

    def _add_row(self, row: int, c: Control, value: Any) -> None:
        tk.Label(self.grid_frame, text=c.label, bg=BG_ELEV, fg=FG_MUTED, font=FONT_UI,
                 anchor="w", width=14).grid(row=row, column=0, sticky="w", pady=2)

        if c.widget == "slider":
            readout = tk.Label(self.grid_frame, text=f"{value:.2f}", bg=BG_ELEV, fg=FG,
                               font=FONT_MONO, width=5, anchor="e")
            readout.grid(row=row, column=2, padx=(8, 0))

            def on_change(v, readout=readout):
                readout.configure(text=f"{v:.2f}")
                self._changed()

            slider = ModernSlider(self.grid_frame, from_=c.lo, to=c.hi, value=value,
                                  resolution=c.step, on_change=on_change, bg=BG_ELEV, track=BG)
            slider.grid(row=row, column=1, sticky="ew", padx=(4, 0))
            self._getters[c.name] = slider.get
            self._setters[c.name] = slider.set
        elif c.widget == "toggle":
            toggle = ToggleSwitch(self.grid_frame, value=value, bg=BG_ELEV,
                                  on_change=lambda _v: self._changed())
            toggle.grid(row=row, column=1, columnspan=2, sticky="w", padx=(4, 0), pady=4)
            self._getters[c.name] = toggle.get
            self._setters[c.name] = toggle.set
        elif c.widget == "choice":
            var = tk.StringVar(value=value)
            combo = ttk.Combobox(self.grid_frame, textvariable=var, values=c.choices,
                                 state="readonly", style="Dark.TCombobox", font=FONT_UI)
            combo.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(4, 0), pady=4)
            combo.bind("<<ComboboxSelected>>", lambda _e: self._changed())
            self._getters[c.name] = var.get
            self._setters[c.name] = var.set
        else:
            var = tk.StringVar(value=value)
            entry = tk.Entry(self.grid_frame, textvariable=var, bg=BG, fg=FG,
                             insertbackground=ACCENT, font=FONT_UI, relief="flat",
                             highlightthickness=2, highlightbackground=BORDER,
                             highlightcolor=ACCENT, bd=0)
            entry.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(4, 0), pady=3, ipady=4)
            var.trace_add("write", lambda *_: self._changed())
            self._getters[c.name] = var.get
            self._setters[c.name] = var.set
