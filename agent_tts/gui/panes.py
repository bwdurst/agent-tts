"""Deferred dividers using a composited overlay, never Tk's sash proxy."""
import tkinter as tk


class GuidePanedWindow(tk.PanedWindow):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._overlay = None
        self._drag = None
        for button in (1, 2):
            self.bind(f"<ButtonPress-{button}>", self._press)
            self.bind(f"<B{button}-Motion>", self._motion)
            self.bind(f"<ButtonRelease-{button}>", self._release)
        self.bind("<Escape>", self._cancel)
        self.bind("<Unmap>", self._cancel)

    def _press(self, event):
        hit = self.identify(event.x, event.y)
        if not hit:
            return "break"
        index = int(hit[0])
        self._cancel()
        horizontal = str(self.cget("orient")) == "horizontal"
        sx, sy = self.sash_coord(index)
        self._drag = dict(index=index, horizontal=horizontal,
                          origin=event.x if horizontal else event.y,
                          start=sx if horizontal else sy,
                          position=sx if horizontal else sy,
                          focus=self.focus_get())
        self._overlay = tk.Toplevel(self, takefocus=False, bg=self.cget("proxybackground"))
        self._overlay.withdraw()
        self._overlay.overrideredirect(True)
        self._overlay.transient(self.winfo_toplevel())
        # A layered top-level is composed by Windows rather than painted into
        # the editor/list HWNDs. Moving it cannot deposit Tk proxy pixels there.
        self._overlay.attributes("-alpha", 0.85)
        self._show_guide()
        self._overlay.deiconify()
        self.grab_set()
        self.focus_set()
        return "break"  # never enter Tk's Panedwindow proxy handlers

    def _show_guide(self):
        position = self._drag["position"]
        if self._drag["horizontal"]:
            width, height = 3, self.winfo_height()
            x, y = self.winfo_rootx() + position, self.winfo_rooty()
        else:
            width, height = self.winfo_width(), 3
            x, y = self.winfo_rootx(), self.winfo_rooty() + position
        self._overlay.geometry(f"{width}x{height}+{x}+{y}")

    def _motion(self, event):
        if self._drag is None:
            return "break"
        drag = self._drag
        horizontal, index = drag["horizontal"], drag["index"]
        axis = 0 if horizontal else 1
        panes = self.panes()
        sash_width = self.winfo_pixels(self.cget("sashwidth"))
        low = (self.sash_coord(index - 1)[axis] + sash_width) if index else 0
        high = (self.sash_coord(index + 1)[axis] if index + 2 < len(panes)
                else self.winfo_width() if horizontal else self.winfo_height())
        low += self.winfo_pixels(self.panecget(panes[index], "minsize"))
        high -= self.winfo_pixels(self.panecget(panes[index + 1], "minsize")) + sash_width
        pointer = event.x if horizontal else event.y
        drag["position"] = max(low, min(high, drag["start"] + pointer - drag["origin"]))
        self._show_guide()
        return "break"

    def _release(self, event):
        if self._drag is not None:
            self._motion(event)
            drag = self._drag
            x, y = self.sash_coord(drag["index"])
            if drag["horizontal"]:
                x = drag["position"]
            else:
                y = drag["position"]
            self._cancel()
            self.sash_place(drag["index"], x, y)
        return "break"

    def _cancel(self, _event=None):
        if self._overlay is not None:
            self._overlay.destroy()
            self._overlay = None
        if self._drag is not None:
            if self.grab_current() is self:
                self.grab_release()
            focus = self._drag["focus"]
            self._drag = None
            if focus is not None and focus.winfo_exists():
                focus.focus_set()
        return "break"

    def destroy(self):
        self._cancel()
        super().destroy()
