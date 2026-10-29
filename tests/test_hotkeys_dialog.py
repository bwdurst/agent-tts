import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QDialog

from agent_tts import hotkeys
from agent_tts.ui_qt.hotkeys_dialog import HotkeysDialog, KeyCaptureEdit, load_bindings, save_bindings

CTRL, SHIFT = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier
NO_MODS = Qt.KeyboardModifier.NoModifier


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)


def test_settings_round_trip_and_fall_back_to_defaults(settings):
    assert load_bindings(settings) == hotkeys.DEFAULT_BINDINGS
    bindings = {**hotkeys.DEFAULT_BINDINGS, "start": hotkeys.parse_binding("Ctrl+Alt+F5"), "flush": None}
    save_bindings(settings, bindings)
    assert load_bindings(settings) == bindings
    settings.setValue("hotkey/skip", "garbage")  # an unreadable entry must not break start-up
    assert load_bindings(settings)["skip"] == hotkeys.DEFAULT_BINDINGS["skip"]


def test_capture_records_a_combination_and_rejects_a_bare_key(app):
    field = KeyCaptureEdit()
    problems = []
    field.problem.connect(problems.append)
    assert field.capture(CTRL | SHIFT, 0x74) == ""  # F5
    assert field.text() == "Ctrl+Shift+F5" and field.binding == hotkeys.parse_binding("Ctrl+Shift+F5")
    assert "Include Ctrl" in field.capture(NO_MODS, 0x41)  # a bare letter would steal typing
    assert field.binding == hotkeys.parse_binding("Ctrl+Shift+F5") and problems[-1].startswith("Include Ctrl")
    assert "Unsupported" in field.capture(CTRL, 0x13)  # Pause is not offered
    assert field.capture(NO_MODS, hotkeys.VK_BACKSPACE) == "" and field.binding is None and field.text() == ""


def test_duplicate_combinations_are_refused_and_defaults_restore(app):
    dialog = HotkeysDialog(dict(hotkeys.DEFAULT_BINDINGS))
    dialog.fields["stop"].set_binding(dialog.fields["start"].binding)
    dialog._accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "Win+F8" in dialog.problem.text() and "Start listening" in dialog.problem.text()
    dialog._restore_defaults()
    assert dialog.bindings == hotkeys.DEFAULT_BINDINGS and dialog.problem.text() == ""
    dialog.fields["flush"].set_binding(None)  # unbinding an action is allowed
    dialog._accept()
    assert dialog.result() == QDialog.DialogCode.Accepted and dialog.bindings["flush"] is None


def test_escape_still_cancels_the_dialog_from_a_capture_field(app):
    from PySide6.QtTest import QTest

    dialog = HotkeysDialog(dict(hotkeys.DEFAULT_BINDINGS))
    dialog.show()
    field = dialog.fields["start"]
    field.setFocus()
    QTest.keyClick(field, Qt.Key.Key_Escape)
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert field.binding == hotkeys.DEFAULT_BINDINGS["start"]  # Escape was not captured as a key
