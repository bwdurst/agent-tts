"""Hotkeys dialog: click a field and press the combination you want.

Bindings are a per-user preference, so they live in the app's QSettings (not
voices.yaml). A combination is captured from the native Windows virtual-key
code, which is what RegisterHotKey needs and is independent of Shift state.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from agent_tts import hotkeys

ACTIONS = (("start", "Start listening"), ("stop", "Stop listening"),
           ("skip", "Skip current line"), ("flush", "Clear queued speech"))
_MODIFIER_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
                  Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock}


def load_bindings(settings):
    """Saved bindings, falling back to the default for any action that is missing or unreadable."""
    bindings = {}
    for name, default in hotkeys.DEFAULT_BINDINGS.items():
        stored = settings.value(f"hotkey/{name}", None)
        if stored is None:
            bindings[name] = default
        elif str(stored) == "":
            bindings[name] = None  # deliberately unbound
        else:
            try:
                bindings[name] = hotkeys.parse_binding(str(stored))
            except ValueError:
                bindings[name] = default
    return bindings


def save_bindings(settings, bindings):
    for name, binding in bindings.items():
        settings.setValue(f"hotkey/{name}", "" if binding is None else hotkeys.format_binding(*binding))


def describe(binding):
    return "Not set" if binding is None else hotkeys.format_binding(*binding)


class KeyCaptureEdit(QLineEdit):
    """Read-only field that records the next key combination pressed in it."""

    problem = Signal(str)  # why the last key press was refused, or "" when it was accepted

    def __init__(self, binding=None, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Click, then press a combination")
        self.message = ""
        self.binding = None
        self.set_binding(binding)

    def set_binding(self, binding):
        self.binding = binding
        self.setText("" if binding is None else hotkeys.format_binding(*binding))
        self.message = ""

    def capture(self, modifiers, vk):
        """Record (Qt modifiers, Windows virtual key). Returns an error message or ''."""
        mods = 0
        for qt_flag, bit in ((Qt.KeyboardModifier.ControlModifier, hotkeys.MOD_CTRL),
                             (Qt.KeyboardModifier.AltModifier, hotkeys.MOD_ALT),
                             (Qt.KeyboardModifier.ShiftModifier, hotkeys.MOD_SHIFT),
                             (Qt.KeyboardModifier.MetaModifier, hotkeys.MOD_WIN)):
            if modifiers & qt_flag:
                mods |= bit
        if mods == 0 and vk in (hotkeys.VK_BACKSPACE, hotkeys.VK_DELETE):
            self.set_binding(None)  # Backspace or Delete alone clears the field
            self.problem.emit("")
            return ""
        try:
            label = hotkeys.format_binding(mods, vk)
            hotkeys.parse_binding(label)  # rejects "no modifier"
        except ValueError as exc:
            self.message = str(exc)
            self.problem.emit(self.message)
            return self.message
        self.set_binding((mods, vk))
        self.problem.emit("")
        return ""

    def keyPressEvent(self, event):
        if event.key() in _MODIFIER_KEYS or event.isAutoRepeat():
            return  # wait for the real key
        if not event.modifiers() and event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.ignore()  # let the dialog cancel or press Save
            return
        self.capture(event.modifiers(), event.nativeVirtualKey())
        event.accept()


class HotkeysDialog(QDialog):
    def __init__(self, bindings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hotkeys")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        intro = QLabel("Global hotkeys work in any application while Agent TTS is open. Click a field and press "
                       "the combination you want; Backspace or Delete clears it. Your current hotkeys are paused while "
                       "this window is open. A combination another program already uses is reported in the "
                       "status line after you save.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.fields = {}
        for name, label in ACTIONS:
            field = KeyCaptureEdit(bindings.get(name))
            field.setAccessibleName(f"{label} hotkey")
            self.fields[name] = field
            field.problem.connect(lambda text: self.problem.setText(text))
            form.addRow(label, field)
        layout.addLayout(form)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        row = QHBoxLayout()
        defaults = QPushButton("Restore defaults")
        defaults.clicked.connect(self._restore_defaults)
        row.addWidget(defaults)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)

    @property
    def bindings(self):
        return {name: field.binding for name, field in self.fields.items()}

    def _restore_defaults(self):
        for name, field in self.fields.items():
            field.set_binding(hotkeys.DEFAULT_BINDINGS[name])
        self.problem.clear()

    def _accept(self):
        seen = {}
        for name, label in ACTIONS:
            binding = self.fields[name].binding
            if binding is None:
                continue
            if binding in seen:
                self.problem.setText(f"{describe(binding)} is used for both '{seen[binding]}' and '{label}'.")
                return
            seen[binding] = label
        self.problem.clear()
        self.accept()
