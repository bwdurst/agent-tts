"""Mouse-wheel scrolling that follows the pointer.

Tk gives <MouseWheel> to the focused widget on some Windows builds and to
nothing at all for Canvas, so per-region bind_all/unbind_all on Enter/Leave
(the old approach) drops events whenever the pointer crosses a child widget.
One router bound once on the root finds the scrollable region under the
pointer by walking up from the widget there, so only that region scrolls.
"""
import tkinter as tk
from tkinter import ttk

from agent_tts.gui.theme import BG_CARD

_ATTR = "_wheel_scroll"


def wheel_steps(delta: int) -> int:
    """Scroll units for a Windows wheel delta (120 per notch). Sub-notch
    deltas from precision touchpads still move at least one unit."""
    if delta == 0:
        return 0
    notches = delta / 120
    steps = int(notches * 3)
    if steps == 0:
        steps = 1 if notches > 0 else -1
    return -steps


def register(widget: tk.Misc, scroller: tk.Misc | None = None) -> None:
    """Mark `widget` (and, by ancestry, everything inside it) as scrolled by
    `scroller`'s yview_scroll. `scroller` defaults to `widget`."""
    setattr(widget, _ATTR, scroller or widget)


def _target(widget: tk.Misc | None):
    while widget is not None:
        found = getattr(widget, _ATTR, None)
        if found is not None:
            return found
        widget = widget.master
    return None


def _on_wheel(root: tk.Misc, event: tk.Event) -> None:
    try:
        under = root.winfo_containing(event.x_root, event.y_root)
    except (KeyError, tk.TclError):
        return  # popdown/combobox lists are not tracked by Tk's name table
    scroller = _target(under)
    if scroller is None:
        return
    lo, hi = scroller.yview()
    if lo <= 0.0 and hi >= 1.0:
        return  # content fits; nothing to scroll
    scroller.yview_scroll(wheel_steps(event.delta), "units")


def install(root: tk.Misc) -> None:
    """Bind the router once and strip the widget classes' own wheel handlers."""
    root.bind_all("<MouseWheel>", lambda e: _on_wheel(root, e))
    # Remove the class-level handlers instead of breaking them: a "break" in
    # the class step would also skip the bind_all router above. Text would
    # otherwise scroll twice; a Combobox would change its value on every
    # wheel notch while the user is only scrolling the page.
    root.unbind_class("Text", "<MouseWheel>")
    root.unbind_class("Treeview", "<MouseWheel>")
    root.unbind_class("TCombobox", "<MouseWheel>")


class ScrollFrame(tk.Frame):
    """A vertically scrolling container. Put content in `.body`. The body
    tracks the canvas width so children fill horizontally, and the scrollbar
    hides itself when everything fits."""

    def __init__(self, parent, *, bg: str = BG_CARD):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0,
                                yscrollincrement=16)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(side="left", fill="both", expand=True)
        self._bar_shown = False

        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self._body_size = None
        self._canvas_width = None
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        register(self, self.canvas)

    def _on_body(self, e) -> None:
        size = (e.width, e.height)
        if size == self._body_size:
            return
        self._body_size = size
        box = self.canvas.bbox("all")
        self.canvas.configure(scrollregion=box)
        # A shrinking body (new, shorter list) must not leave the view parked
        # past its end.
        if box and (box[3] - box[1]) <= self.canvas.winfo_height():
            self.canvas.yview_moveto(0)

    def _on_canvas(self, e) -> None:
        if e.width == self._canvas_width:
            return
        self._canvas_width = e.width
        self.canvas.itemconfigure(self._window, width=e.width)

    def _on_scroll(self, lo, hi) -> None:
        self.scrollbar.set(lo, hi)
        need = not (float(lo) <= 0.0 and float(hi) >= 1.0)
        if need and not self._bar_shown:
            self.scrollbar.pack(side="right", fill="y")
            self._bar_shown = True
        elif not need and self._bar_shown:
            self.scrollbar.pack_forget()
            self._bar_shown = False

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0)
