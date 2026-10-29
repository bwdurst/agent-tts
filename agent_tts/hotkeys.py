"""Windows hotkeys, registered and released on their owning message thread."""
import ctypes
import logging
import threading
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32")
_kernel32 = ctypes.WinDLL("kernel32")
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
MOD_CTRL, MOD_SHIFT, MOD_NOREPEAT = 0x0002, 0x0004, 0x4000
VK_PERIOD, VK_SLASH = 0xBE, 0xBF
WM_QUIT, WM_HOTKEY = 0x0012, 0x0312
_thread = None
_thread_id = None
_stop_event = threading.Event()
_lock = threading.Lock()


def register(on_skip, on_flush, on_error=None):
    """Start once. Callbacks execute on the worker; GUI callers must emit signals."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            raise RuntimeError("Hotkey thread is still running")
        _stop_event.clear()
        _thread = threading.Thread(target=_run, args=(on_skip, on_flush, on_error),
                                   daemon=True, name="tts-hotkeys")
        _thread.start()


def _run(on_skip, on_flush, on_error):
    global _thread_id
    msg = wintypes.MSG()
    _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
    _thread_id = _kernel32.GetCurrentThreadId()
    registered = []
    try:
        for ident, key, label in ((1, VK_PERIOD, "Skip"), (2, VK_SLASH, "Flush")):
            if _user32.RegisterHotKey(None, ident, MOD_CTRL | MOD_SHIFT | MOD_NOREPEAT, key):
                registered.append(ident)
            else:
                message = f"{label} hotkey unavailable; another app may own it. Use the button."
                logging.getLogger(__name__).warning(message)
                if on_error:
                    on_error(message)
        while not _stop_event.is_set():
            if _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) <= 0:
                break
            if msg.message == WM_HOTKEY:
                callback = {1: on_skip, 2: on_flush}.get(msg.wParam)
                if callback:
                    callback()
    finally:
        for ident in registered:
            _user32.UnregisterHotKey(None, ident)
        _thread_id = None


def stop():
    _stop_event.set()
    tid = _thread_id
    if tid is not None:
        _user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)


def join(timeout=2.0):
    if _thread is not None and _thread is not threading.current_thread():
        _thread.join(timeout)


def unregister():
    stop()
    join()
