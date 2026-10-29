"""Keep native window movement independent of expensive descendant layout.

Tk on Windows resizes each child HWND individually. A short trailing debounce
keeps the window border responsive during a continuous resize, then lays out
the contents once the pointer pauses. Position-only events do no work.
"""
import tkinter as tk


class ResizeSurface(tk.Frame):
    SETTLE_MS = 150

    def __init__(self, root: tk.Tk, **kwargs):
        super().__init__(root, **kwargs)
        self._window_root = root
        self._size: tuple[int, int] | None = None
        self._pending_size: tuple[int, int] | None = None
        self._job: str | None = None
        self.place(x=0, y=0, width=1, height=1)
        self._binding = root.bind("<Configure>", self._configure_root, add="+")
        self.bind("<Destroy>", self._cleanup, add="+")

    def _configure_root(self, event) -> None:
        if event.widget is not self._window_root:
            return
        size = (event.width, event.height)
        if size == self._pending_size or size == self._size and self._job is None:
            return
        self._pending_size = size
        if self._job is not None:
            self.after_cancel(self._job)
        if self._size is None:
            self._apply_size()
        else:
            self._job = self.after(self.SETTLE_MS, self._apply_size)

    def _apply_size(self) -> None:
        self._job = None
        self._size = self._pending_size
        self._pending_size = None
        if self._size is not None:
            self.place_configure(width=self._size[0], height=self._size[1])

    def _cleanup(self, event) -> None:
        if event.widget is not self:
            return
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        self._window_root.unbind("<Configure>", self._binding)
