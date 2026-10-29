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
MOD_ALT, MOD_CTRL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000
VK_F7, VK_F8, VK_F9, VK_F10 = 0x76, 0x77, 0x78, 0x79
VK_BACKSPACE, VK_DELETE = 0x08, 0x2E
# (name, registration id, label). Only actions with a handler are registered,
# so a caller that has no start/stop (the CLI and the Tk dashboard) never
# claims those keys.
HOTKEYS = (("start", 3, "Start"), ("stop", 4, "Stop"), ("skip", 1, "Skip"), ("flush", 2, "Flush"))
# Win+F7..F10, side by side: flush, start, stop, skip. Windows keeps most Win-key
# combinations for itself, so applications such as Teams, Office and VS Code do
# not bind them; Ctrl/Shift/Alt combinations are what those applications use.
DEFAULT_BINDINGS = {
    "start": (MOD_WIN, VK_F8),
    "stop": (MOD_WIN, VK_F9),
    "skip": (MOD_WIN, VK_F10),
    "flush": (MOD_WIN, VK_F7),
}

_MODIFIER_NAMES = (("Ctrl", MOD_CTRL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT), ("Win", MOD_WIN))
_OEM_KEYS = {",": 0xBC, ".": 0xBE, "/": 0xBF, ";": 0xBA, "=": 0xBB, "-": 0xBD, "`": 0xC0,
             "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE}
_NAMED_KEYS = {"Space": 0x20, "Enter": 0x0D, "Backspace": 0x08, "Insert": 0x2D, "Delete": 0x2E,
               "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22,
               "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28}
_LABEL_TO_VK = {**_OEM_KEYS, **_NAMED_KEYS,
                **{chr(c): c for c in range(0x30, 0x3A)}, **{chr(c): c for c in range(0x41, 0x5B)},
                **{f"F{n}": 0x70 + n - 1 for n in range(1, 25)}}
_VK_TO_LABEL = {vk: label for label, vk in _LABEL_TO_VK.items()}


def default_label(name):
    """The default key for an action as text, e.g. "Win+F10" (for hints in the CLI and Tk dashboard)."""
    return format_binding(*DEFAULT_BINDINGS[name])


def format_binding(mods, vk):
    """(modifier mask, virtual key) -> "Win+F8"."""
    label = _VK_TO_LABEL.get(vk)
    if label is None:
        raise ValueError(f"Unsupported key (code {vk:#x}).")
    return "+".join([name for name, bit in _MODIFIER_NAMES if mods & bit] + [label])


_F_KEYS = range(0x70, 0x88)
_VK_F4, _VK_F12 = 0x73, 0x7B
# Exact (modifiers, key) pairs that are editing or window shortcuts everywhere.
_RESERVED = ({(MOD_CTRL, ord(c)) for c in "ACVXYZS"}
             | {(MOD_CTRL, 0x08), (MOD_CTRL, 0x2E), (MOD_ALT, _VK_F4), (MOD_ALT, 0x20)})


def _refusal(mods, vk):
    """Why this combination must not be a global hotkey, or None.

    A registered combination is taken from every application, so it must not be
    something people type or use as a standard shortcut."""
    if vk == _VK_F12:
        return "F12 is reserved by Windows for debuggers."
    if (mods, vk) in _RESERVED:
        return "That is a standard editing or window shortcut; binding it would break it in every program."
    if not mods & (MOD_CTRL | MOD_ALT | MOD_WIN) and vk not in _F_KEYS:
        return "Shift alone would take over typing. Add Ctrl, Alt or Win."
    if mods & MOD_CTRL and mods & MOD_ALT and vk not in _F_KEYS and vk not in _NAMED_KEYS.values():
        return "Ctrl+Alt is AltGr on many keyboards and would take over typing. Use Ctrl+Shift or Win instead."
    return None


def parse_binding(spec):
    """"Win+F8" -> (modifier mask, virtual key). A global hotkey needs a modifier."""
    parts = [p.strip() for p in str(spec).split("+")]
    if parts and parts[-1] == "" and len(parts) >= 2:  # "Ctrl++" would be a '+' key; not supported
        raise ValueError("Unsupported key.")
    *names, key = parts
    mods = 0
    for name in names:
        bit = dict(_MODIFIER_NAMES).get(name)
        if bit is None:
            raise ValueError(f"Unknown modifier {name!r}.")
        mods |= bit
    vk = _LABEL_TO_VK.get(key)
    if vk is None:
        raise ValueError(f"Unsupported key {key!r}.")
    if not mods:
        raise ValueError("Include Ctrl, Alt, Shift or Win so the key does not steal normal typing.")
    refusal = _refusal(mods, vk)
    if refusal:
        raise ValueError(refusal)
    return mods, vk
WM_QUIT, WM_HOTKEY = 0x0012, 0x0312
_thread = None
_thread_id = None
_stop_event = threading.Event()
_lock = threading.Lock()


def register(on_skip, on_flush, on_error=None, *, on_start=None, on_stop=None, bindings=None):
    """Start once. Callbacks execute on the worker; GUI callers must emit signals.

    `bindings` maps an action name to (modifiers, key) or None to leave it unbound;
    missing names use DEFAULT_BINDINGS."""
    global _thread
    handlers = {"skip": on_skip, "flush": on_flush, "start": on_start, "stop": on_stop}
    with _lock:
        if _thread is not None and _thread.is_alive():
            raise RuntimeError("Hotkey thread is still running")
        _stop_event.clear()
        _thread = threading.Thread(target=_run, args=({k: v for k, v in handlers.items() if v}, on_error, {**DEFAULT_BINDINGS, **(bindings or {})}),
                                   daemon=True, name="tts-hotkeys")
        _thread.start()


def _run(handlers, on_error, bindings):
    global _thread_id
    msg = wintypes.MSG()
    _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
    _thread_id = _kernel32.GetCurrentThreadId()
    registered = []
    try:
        callbacks = {}
        for name, ident, label in HOTKEYS:
            if name not in handlers or bindings.get(name) is None:
                continue
            mods, key = bindings[name]
            callbacks[ident] = handlers[name]
            if _user32.RegisterHotKey(None, ident, mods | MOD_NOREPEAT, key):
                registered.append(ident)
            else:
                message = (f"{label} hotkey {format_binding(mods, key)} is unavailable; "
                           "another app may own it. Change it under Hotkeys… or use the button.")
                logging.getLogger(__name__).warning(message)
                if on_error:
                    on_error(message)
        while not _stop_event.is_set():
            if _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) <= 0:
                break
            if msg.message == WM_HOTKEY:
                callback = callbacks.get(msg.wParam)
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
