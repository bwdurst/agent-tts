"""Custom Tk widgets: slider, button, toggle, chip, tab strip, star.

Every interactive widget takes keyboard focus (Tab order follows pack order),
shows a visible focus ring, and activates on Space or Enter, so the whole
dashboard is usable without a mouse.
"""
import tkinter as tk
from tkinter import ttk

from agent_tts.gui.theme import (
    ACCENT, ACCENT_FILL, ACCENT_HOVER, BG, BG_CARD, BG_ELEV, BG_HOVER, BORDER,
    DANGER, FG, FG_DIM, FG_MUTED, FONT_UI, FONT_UI_BOLD, FONT_UI_SMALL,
    STAR_COLOR_OFF, STAR_COLOR_ON, STAR_OFF, STAR_ON,
)


def apply_ttk_styles(root: tk.Misc) -> None:
    """Baseline ttk look: dark scrollbar and combobox, popdown list included."""
    style = ttk.Style(root)
    style.theme_use("default")
    style.configure("TFrame", background=BG)
    style.configure("Voices.Treeview", background=BG_ELEV, fieldbackground=BG_ELEV,
                    foreground=FG, font=FONT_UI, rowheight=32, borderwidth=0)
    style.configure("Voices.Treeview.Heading", background=BG_CARD, foreground=FG_MUTED,
                    font=FONT_UI_BOLD, relief="flat")
    style.map("Voices.Treeview", background=[("selected", ACCENT_FILL)],
              foreground=[("selected", "#ffffff")])
    style.configure("Vertical.TScrollbar", background=BG_HOVER, troughcolor=BG_CARD,
                    bordercolor=BG_CARD, arrowcolor=FG_MUTED, lightcolor=BG_HOVER,
                    darkcolor=BG_HOVER, gripcount=0, width=12)
    style.map("Vertical.TScrollbar", background=[("active", BORDER)])
    # Thumb only: the arrow buttons are redundant with the wheel and drag.
    style.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {
        "sticky": "ns",
        "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    style.configure("Dark.TCombobox", fieldbackground=BG, background=BG_ELEV,
                    foreground=FG, arrowcolor=FG_MUTED, bordercolor=BORDER,
                    lightcolor=BG, darkcolor=BG, selectbackground=BG,
                    selectforeground=FG, padding=4)
    style.map("Dark.TCombobox",
              fieldbackground=[("readonly", BG)],
              foreground=[("readonly", FG)],
              bordercolor=[("focus", ACCENT)])
    root.option_add("*TCombobox*Listbox.background", BG_ELEV)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_FILL)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", FONT_UI)


class ModernSlider(tk.Canvas):
    """A thin-track, round-thumb slider that fills the width it is given.

    Emits changes via on_change. Use .get() / .set() like tk.Scale. Arrow keys
    step by one resolution unit (Shift for ten), Home/End jump to the ends.
    """
    TRACK_W = 4
    THUMB_R = 8
    PADDING = 12
    HEIGHT = 34

    def __init__(self, parent, *, from_: float, to: float, value: float,
                 resolution: float = 0.01, width: int = 240,
                 bg: str = BG_CARD, track: str = BG_ELEV,
                 fill: str = ACCENT, thumb: str = ACCENT,
                 on_change=None):
        super().__init__(parent, width=width, height=self.HEIGHT,
                         bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=True)
        self.from_ = from_
        self.to = to
        self.resolution = resolution
        self._value = max(from_, min(to, value))
        self._bg = bg
        self._track_color = track
        self._fill_color = fill
        self._thumb_color = thumb
        self._on_change = on_change
        self._dragging = False
        self._hovered = False
        self._focused = False

        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda e: self._set_flag("_hovered", True))
        self.bind("<Leave>", lambda e: self._set_flag("_hovered", False))
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<FocusIn>", lambda e: self._set_flag("_focused", True))
        self.bind("<FocusOut>", lambda e: self._set_flag("_focused", False))
        self.bind("<Left>",        lambda e: self._step(-1))
        self.bind("<Right>",       lambda e: self._step(1))
        self.bind("<Down>",        lambda e: self._step(-1))
        self.bind("<Up>",          lambda e: self._step(1))
        self.bind("<Shift-Left>",  lambda e: self._step(-10))
        self.bind("<Shift-Right>", lambda e: self._step(10))
        self.bind("<Home>",        lambda e: self.set(self.from_))
        self.bind("<End>",         lambda e: self.set(self.to))

        self.after(1, self._redraw)

    def _span(self) -> float:
        # Use the real width: the slider stretches with its row, and a width
        # captured at construction leaves the track short of the thumb range.
        return max(1, (self.winfo_width() or int(self["width"]))) - 2 * self.PADDING

    def _value_to_x(self, v: float) -> float:
        ratio = (v - self.from_) / (self.to - self.from_)
        return self.PADDING + ratio * self._span()

    def _x_to_value(self, x: float) -> float:
        ratio = max(0.0, min(1.0, (x - self.PADDING) / self._span()))
        raw = self.from_ + ratio * (self.to - self.from_)
        steps = round((raw - self.from_) / self.resolution)
        return round(self.from_ + steps * self.resolution, 3)

    def _redraw(self) -> None:
        self.delete("all")
        y = self.HEIGHT // 2
        right = self.PADDING + self._span()

        self.create_rectangle(self.PADDING, y - self.TRACK_W // 2,
                              right, y + self.TRACK_W // 2 + 1,
                              fill=self._track_color, outline="")
        thumb_x = self._value_to_x(self._value)
        self.create_rectangle(self.PADDING, y - self.TRACK_W // 2,
                              thumb_x, y + self.TRACK_W // 2 + 1,
                              fill=self._fill_color, outline="")

        r = self.THUMB_R
        if self._focused:
            self.create_oval(thumb_x - r - 4, y - r - 4, thumb_x + r + 4, y + r + 4,
                             fill="", outline=ACCENT_HOVER, width=2)
        active = self._hovered or self._dragging or self._focused
        self.create_oval(thumb_x - r, y - r, thumb_x + r, y + r,
                         fill=ACCENT_HOVER if active else self._thumb_color,
                         outline=self._bg, width=2)

    def _set_flag(self, name: str, value: bool) -> None:
        setattr(self, name, value)
        self._redraw()

    def _on_click(self, e) -> None:
        self._dragging = True
        self.focus_set()
        self.set(self._x_to_value(e.x))

    def _on_drag(self, e) -> None:
        self.set(self._x_to_value(e.x))

    def _on_release(self, _e) -> None:
        self._dragging = False
        self._redraw()

    def _step(self, multiplier: int) -> None:
        self.set(round(self._value + self.resolution * multiplier, 3))

    def get(self) -> float:
        return self._value

    def set(self, v: float) -> None:
        v = max(self.from_, min(self.to, v))
        if v != self._value:
            self._value = v
            if self._on_change:
                self._on_change(v)
        self._redraw()


class ModernButton(tk.Frame):
    """Flat, hoverable, keyboard-focusable button: primary / ghost / danger."""

    STYLES = {
        "primary": dict(bg=ACCENT_FILL, fg="#ffffff", hover=ACCENT),
        "ghost":   dict(bg=BG_ELEV, fg=FG,        hover=BG_HOVER),
        "danger":  dict(bg=BG_ELEV, fg=DANGER,    hover=BG_HOVER),
    }

    def __init__(self, parent, text: str, command=None, *,
                 style: str = "ghost", padx: int = 14, pady: int = 9,
                 font=FONT_UI_BOLD):
        s = self.STYLES[style]
        # The frame's highlight ring is the focus indicator; at rest it is
        # painted in the button color so it takes no visible space.
        super().__init__(parent, bg=s["bg"], bd=0, highlightthickness=2,
                         highlightbackground=s["bg"], highlightcolor=ACCENT_HOVER,
                         takefocus=True)
        self._style = s
        self._command = command
        self._enabled = True

        self.label = tk.Label(self, text=text, bg=s["bg"], fg=s["fg"], font=font,
                              padx=padx, pady=pady, cursor="hand2")
        self.label.pack()

        for widget in (self, self.label):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<Button-1>", self._on_click)
        self.bind("<space>", self._on_click)
        self.bind("<Return>", self._on_click)

    def _paint(self, bg: str) -> None:
        self.configure(bg=bg, highlightbackground=self._style["bg"])
        self.label.configure(bg=bg)

    def _on_enter(self, _e) -> None:
        if self._enabled:
            self._paint(self._style["hover"])

    def _on_leave(self, _e) -> None:
        if self._enabled:
            self._paint(self._style["bg"])

    def _on_click(self, _e) -> None:
        if self._enabled and self._command:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(takefocus=enabled)
        self.label.configure(fg=self._style["fg"] if enabled else FG_DIM,
                             cursor="hand2" if enabled else "")

    def set_style(self, name: str) -> None:
        self._style = self.STYLES[name]
        self._paint(self._style["bg"])
        self.label.configure(fg=self._style["fg"] if self._enabled else FG_DIM)

    def set_text(self, text: str) -> None:
        self.label.configure(text=text)


class ToggleSwitch(tk.Canvas):
    """Pill-shaped on/off toggle. Space or Enter toggles."""
    WIDTH = 40
    HEIGHT = 24
    PAD = 3

    def __init__(self, parent, *, value: bool = False, on_change=None,
                 bg: str = BG_ELEV,
                 on_color: str = ACCENT_FILL, off_color: str = BG_HOVER,
                 thumb_color: str = "#ffffff"):
        super().__init__(parent, width=self.WIDTH, height=self.HEIGHT,
                         bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=True)
        self._value = value
        self._on_color = on_color
        self._off_color = off_color
        self._thumb_color = thumb_color
        self._on_change = on_change
        self._focused = False

        self.bind("<Button-1>", self._toggle)
        self.bind("<space>",    self._toggle)
        self.bind("<Return>",   self._toggle)
        self.bind("<FocusIn>",  lambda e: self._focus(True))
        self.bind("<FocusOut>", lambda e: self._focus(False))
        self.after(1, self._redraw)

    def _redraw(self) -> None:
        self.delete("all")
        color = self._on_color if self._value else self._off_color
        r = self.HEIGHT // 2
        self.create_oval(0, 0, self.HEIGHT, self.HEIGHT, fill=color, outline="")
        self.create_oval(self.WIDTH - self.HEIGHT, 0, self.WIDTH, self.HEIGHT,
                         fill=color, outline="")
        self.create_rectangle(r, 0, self.WIDTH - r, self.HEIGHT, fill=color, outline="")
        if self._focused:
            self.create_rectangle(0, 0, self.WIDTH - 1, self.HEIGHT - 1,
                                  outline=ACCENT_HOVER, width=2)
        d = self.HEIGHT - 2 * self.PAD
        x = (self.WIDTH - self.PAD - d) if self._value else self.PAD
        self.create_oval(x, self.PAD, x + d, self.PAD + d,
                         fill=self._thumb_color, outline="")

    def _toggle(self, _e=None) -> None:
        self.set(not self._value)
        self.focus_set()

    def _focus(self, on: bool) -> None:
        self._focused = on
        self._redraw()

    def get(self) -> bool:
        return self._value

    def set(self, v: bool) -> None:
        v = bool(v)
        if v != self._value:
            self._value = v
            if self._on_change:
                self._on_change(v)
        self._redraw()


class ChipButton(tk.Frame):
    """On/off pill for faceted filters. The selected chip carries a check
    mark as well as the accent fill, so state never relies on color alone."""

    def __init__(self, parent, text: str, *, value: bool = False, on_change=None):
        super().__init__(parent, bg=BG_ELEV, bd=0, highlightthickness=2,
                         highlightbackground=BG_CARD, highlightcolor=ACCENT_HOVER,
                         takefocus=True)
        self._value = value
        self._on_change = on_change
        self._text = text
        self.label = tk.Label(self, font=FONT_UI_SMALL, padx=10, pady=4, cursor="hand2")
        self.label.pack()
        self._apply_state()
        for w in (self, self.label):
            w.bind("<Button-1>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<Return>", self._toggle)

    def _apply_state(self) -> None:
        if self._value:
            self.configure(bg=ACCENT_FILL)
            self.label.configure(bg=ACCENT_FILL, fg="#ffffff", text=f"✓ {self._text}")
        else:
            self.configure(bg=BG_ELEV)
            self.label.configure(bg=BG_ELEV, fg=FG_MUTED, text=self._text)

    def _toggle(self, _e=None) -> None:
        self._value = not self._value
        self._apply_state()
        if self._on_change:
            self._on_change(self._text, self._value)

    def get(self) -> bool:
        return self._value


class StarButton(tk.Label):
    """Favorite toggle with a real click target. Space or Enter toggles."""

    def __init__(self, parent, *, on: bool, bg: str, command):
        super().__init__(parent, text=STAR_ON if on else STAR_OFF, bg=bg,
                         fg=STAR_COLOR_ON if on else STAR_COLOR_OFF,
                         font=("Segoe UI", 15), width=2, pady=4, cursor="hand2",
                         takefocus=True, highlightthickness=2,
                         highlightbackground=bg, highlightcolor=ACCENT_HOVER)
        self._command = command
        self.bind("<Button-1>", lambda _e: command())
        self.bind("<space>", lambda _e: command())
        self.bind("<Return>", lambda _e: command())


class TabStrip(tk.Frame):
    """Tab row with an accent underline on the selected tab. Left/Right move
    between tabs when the strip has focus; each tab is a Tab stop."""

    def __init__(self, parent, tabs: list[tuple[str, str]], *, on_select, bg: str = BG_CARD):
        super().__init__(parent, bg=bg)
        self._on_select = on_select
        self._keys = [k for k, _ in tabs]
        self._items: dict[str, tuple[tk.Frame, tk.Label, tk.Frame]] = {}
        self._selected: str | None = None
        for key, text in tabs:
            item = tk.Frame(self, bg=bg, highlightthickness=2, highlightbackground=bg,
                            highlightcolor=ACCENT_HOVER, takefocus=True)
            item.pack(side="left", padx=(0, 4))
            label = tk.Label(item, text=text, bg=bg, fg=FG_MUTED, font=FONT_UI_BOLD,
                             padx=16, pady=8, cursor="hand2")
            label.pack()
            bar = tk.Frame(item, bg=bg, height=3)
            bar.pack(fill="x")
            for w in (item, label):
                w.bind("<Button-1>", lambda _e, k=key: self.select(k, focus=True))
            item.bind("<space>", lambda _e, k=key: self.select(k))
            item.bind("<Return>", lambda _e, k=key: self.select(k))
            item.bind("<Left>", lambda _e: self._move(-1))
            item.bind("<Right>", lambda _e: self._move(1))
            self._items[key] = (item, label, bar)
        self._bg = bg

    def _move(self, step: int) -> None:
        i = (self._keys.index(self._selected) + step) % len(self._keys)
        self.select(self._keys[i], focus=True)

    def select(self, key: str, *, focus: bool = False) -> None:
        for k, (item, label, bar) in self._items.items():
            on = k == key
            label.configure(fg=FG if on else FG_MUTED)
            bar.configure(bg=ACCENT if on else self._bg)
        changed = key != self._selected
        self._selected = key
        if focus:
            self._items[key][0].focus_set()
        if changed:
            self._on_select(key)

    @property
    def selected(self) -> str | None:
        return self._selected


class SearchEntry(tk.Entry):
    """Entry with a hint label overlaid while the field is empty. The hint is
    a separate widget, so `textvariable` only ever holds what the user typed."""

    def __init__(self, parent, *, hint: str, textvariable: tk.StringVar):
        super().__init__(parent, textvariable=textvariable, bg=BG_ELEV, fg=FG,
                         insertbackground=ACCENT, font=FONT_UI, relief="flat",
                         highlightthickness=2, highlightbackground=BORDER,
                         highlightcolor=ACCENT, bd=0)
        self._var = textvariable
        self._hint = tk.Label(self, text=hint, bg=BG_ELEV, fg=FG_DIM, font=FONT_UI,
                              cursor="xterm")
        self._hint.bind("<Button-1>", lambda e: self.focus_set())
        textvariable.trace_add("write", lambda *_: self._sync())
        self._sync()

    def _sync(self) -> None:
        if self._var.get():
            self._hint.place_forget()
        else:
            self._hint.place(x=10, rely=0.5, anchor="w")
