"""Hotkey bindings: parsing, registration with custom keys, and the unavailable-key message."""
import ctypes
import queue
import threading

import pytest

from agent_tts import hotkeys


def test_defaults_read_as_win_function_keys():
    assert {n: hotkeys.format_binding(*b) for n, b in hotkeys.DEFAULT_BINDINGS.items()} == {
        "start": "Win+F8", "stop": "Win+F9", "skip": "Win+F10", "flush": "Win+F7"}


def test_defaults_follow_their_own_rules_and_are_distinct():
    for name, binding in hotkeys.DEFAULT_BINDINGS.items():
        assert hotkeys.parse_binding(hotkeys.format_binding(*binding)) == binding, name
        assert hotkeys.default_label(name) == hotkeys.format_binding(*binding)
    assert len(set(hotkeys.DEFAULT_BINDINGS.values())) == len(hotkeys.DEFAULT_BINDINGS)
    assert all(mods == hotkeys.MOD_WIN for mods, _ in hotkeys.DEFAULT_BINDINGS.values())


@pytest.mark.parametrize("spec", ["Ctrl+Shift+,", "Win+F8", "Ctrl+Alt+F5", "Win+Up", "Alt+7", "Ctrl+Shift+Space", "Shift+F5"])
def test_parse_and_format_round_trip(spec):
    assert hotkeys.format_binding(*hotkeys.parse_binding(spec)) == spec


@pytest.mark.parametrize("spec", ["", "Shift", "Ctrl+", "F5", "A", "Ctrl+Hyper+A", "Ctrl+Q+R", "Ctrl+Nope",
                                  "Shift+A", "Ctrl+C", "Ctrl+Z", "Ctrl+Backspace", "Alt+F4", "Alt+Space",
                                  "Ctrl+Shift+F12", "Ctrl+Alt+Q", "Ctrl+Alt+Shift+7"])
def test_bad_bindings_are_rejected(spec):
    with pytest.raises(ValueError):
        hotkeys.parse_binding(spec)


def run_register(monkeypatch, bindings=None, fail=(), **handlers):
    """Register against a fake user32 and return the RegisterHotKey calls and error messages."""
    messages = queue.Queue()
    calls, errors = [], []
    done = threading.Event()
    expected = len(handlers) + 2  # skip and flush are always given

    class FakeUser32:
        def PeekMessageW(self, *args):
            return 0

        def RegisterHotKey(self, hwnd, ident, mods, vk):
            calls.append((ident, mods, vk))
            if len(calls) == expected - sum(1 for b in (bindings or {}).values() if b is None):
                done.set()
            return 0 if ident in fail else 1

        def UnregisterHotKey(self, hwnd, ident):
            return 1

        def PostThreadMessageW(self, tid, message, *args):
            messages.put(message)
            return 1

        def GetMessageW(self, ptr, *args):
            message = messages.get(timeout=1)
            msg = ctypes.cast(ptr, ctypes.POINTER(hotkeys.wintypes.MSG)).contents
            msg.message = message
            return 0 if message == hotkeys.WM_QUIT else 1

    monkeypatch.setattr(hotkeys, "_user32", FakeUser32())
    hotkeys.register(lambda: None, lambda: None, errors.append, bindings=bindings, **handlers)
    assert done.wait(1)
    hotkeys.unregister()
    return calls, errors


def test_custom_bindings_are_registered_and_unbound_actions_are_skipped(monkeypatch):
    bindings = {"start": hotkeys.parse_binding("Ctrl+Alt+F5"), "stop": None}
    calls, errors = run_register(monkeypatch, bindings, on_start=lambda: None, on_stop=lambda: None)
    by_id = {ident: (mods & ~hotkeys.MOD_NOREPEAT, vk) for ident, mods, vk in calls}
    assert by_id[3] == hotkeys.parse_binding("Ctrl+Alt+F5")
    assert 4 not in by_id  # stop is unbound
    assert by_id[1] == hotkeys.DEFAULT_BINDINGS["skip"] and by_id[2] == hotkeys.DEFAULT_BINDINGS["flush"]
    assert all(mods & hotkeys.MOD_NOREPEAT for _, mods, _ in calls) and not errors


def test_actions_without_a_handler_never_claim_their_keys(monkeypatch):
    calls, _ = run_register(monkeypatch)
    assert sorted(ident for ident, _, _ in calls) == [1, 2]  # the CLI and Tk have no start or stop


def test_unavailable_key_is_reported_with_its_combination(monkeypatch):
    calls, errors = run_register(monkeypatch, fail=(3,), on_start=lambda: None)
    assert len(errors) == 1
    assert "Start hotkey Win+F8" in errors[0] and "Hotkeys" in errors[0]
