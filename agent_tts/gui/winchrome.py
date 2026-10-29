"""Windows-specific window setup. Every helper silently no-ops elsewhere."""
import ctypes
import tkinter as tk


def enable_dark_titlebar(root: tk.Tk) -> None:
    """Ask Windows DWM to paint the title bar dark. Windows 10 1809+."""
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value), ctypes.sizeof(value),
        )
    except Exception:
        pass


def set_app_user_model_id(app_id: str = "AgentTTS.Dashboard.1") -> None:
    """Tell Windows this process is its own app, not a child of pythonw.exe,
    so the taskbar shows our icon. Must run BEFORE the first Tk window."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        pass


def enable_dpi_awareness() -> None:
    """Opt into per-monitor DPI v2 so canvas widgets render crisp on HiDPI
    displays. Must run BEFORE tk.Tk() is created."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass
