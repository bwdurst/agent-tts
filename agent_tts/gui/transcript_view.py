"""Transcript card: stacked messages with a colored speaker label."""
import tkinter as tk
from tkinter import ttk

from agent_tts.gui import scrolling
from agent_tts.gui.theme import (
    ACCENT, BG, BG_CARD, BORDER, FG, FG_DIM, FONT_BODY, FONT_MONO, FONT_SECTION,
    FONT_SPEAKER, SPEAKER_COLORS, blend,
)


class TranscriptEvent:
    def __init__(self, speaker: str, text: str):
        self.speaker = speaker
        self.text = text


class TranscriptView(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG_CARD, bd=0, highlightthickness=1,
                         highlightbackground=BORDER)
        header = tk.Frame(self, bg=BG_CARD)
        header.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(header, text="Transcript", bg=BG_CARD, fg=FG,
                 font=FONT_SECTION).pack(side="left")

        body = tk.Frame(self, bg=BG_CARD)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.text = tk.Text(
            body, wrap="word", state="disabled", height=6,
            bg=BG_CARD, fg=FG, insertbackground=FG, font=FONT_BODY,
            relief="flat", padx=4, pady=4, bd=0, highlightthickness=0,
            selectbackground=ACCENT, selectforeground=BG, spacing3=4,
        )
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        scrolling.register(self.text)

        self._has_content = False
        self._setup_tags()
        self.show_hint()

    def _setup_tags(self) -> None:
        # The label is the full speaker color; the body is that color blended
        # 70% toward FG so reading stays easy while the block still carries
        # whose voice is speaking.
        for speaker, color in SPEAKER_COLORS.items():
            self.text.tag_configure(f"label_{speaker}", foreground=color,
                                    font=FONT_SPEAKER, spacing1=10, spacing3=4)
            self.text.tag_configure(f"body_{speaker}", foreground=blend(color, FG, 0.70),
                                    font=FONT_BODY, lmargin1=0, lmargin2=0, spacing3=8)
        self.text.tag_configure("system", foreground=FG_DIM, font=FONT_MONO,
                                spacing1=6, spacing3=6)
        self.text.tag_configure("hint", foreground=FG_DIM, font=("Segoe UI Italic", 10),
                                justify="center", spacing1=10)

    def show_hint(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "Waiting for messages…\n"
                         "Press Start, then invoke an agent in Claude Code.", "hint")
        self.text.configure(state="disabled")
        self._has_content = False

    def _clear_hint(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self._has_content = True

    def clear_hint_if_shown(self) -> None:
        if not self._has_content:
            self._clear_hint()

    def _insert(self, parts: list[tuple[str, str]]) -> None:
        self.clear_hint_if_shown()
        # Auto-scroll only if the reader is already at the bottom, so a block
        # arriving never yanks someone reading an earlier turn.
        at_bottom = self.text.yview()[1] > 0.95
        self.text.configure(state="normal")
        for content, tag in parts:
            self.text.insert("end", content, tag)
        if at_bottom:
            self.text.see("end")
        self.text.configure(state="disabled")

    def append_block(self, speaker: str, text: str) -> None:
        tag = speaker if speaker in SPEAKER_COLORS else "_default"
        name = "NARRATOR" if speaker == "_default" else speaker
        self._insert([(name + "\n", f"label_{tag}"), (text + "\n", f"body_{tag}")])

    def append_system(self, msg: str) -> None:
        self._insert([(f"› {msg}\n", "system")])
