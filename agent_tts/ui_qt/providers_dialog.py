"""Providers dialog: enter, check, and remove API keys without editing files.

Keys go to the operating system's credential store (see agent_tts.credentials)
and are never shown again, logged, or written to voices.yaml.
"""
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from agent_tts import credentials
from agent_tts.application.controller import error_message
from agent_tts.tts.factory import provider_class

PROVIDER_LABELS = {"xai": "xAI", "elevenlabs": "ElevenLabs", "cartesia": "Cartesia"}


def check_key(provider: str, key: str) -> str:
    """Ask the provider for its voice list. Returns a short success message or raises."""
    adapter = provider_class(provider)(key, "mp3", Path(tempfile.gettempdir()) / "agent_tts_keycheck")
    count = len(adapter.list_voices())
    return f"Key works ({count} voices available)."


def describe_failure(provider: str, exc: Exception) -> str:
    message = error_message(exc)
    if provider == "elevenlabs" and "401" in message:
        message += " ElevenLabs keys need the voices_read permission to list voices; speech can still work without it."
    return message


class ProvidersDialog(QDialog):
    keys_changed = Signal(str)  # provider name, after a save or remove
    _checked = Signal(str, int, bool, str)

    def __init__(self, parent=None, *, check=check_key):
        super().__init__(parent)
        self.setWindowTitle("Providers")
        self.setMinimumWidth(560)
        self._check = check
        self._rows = {}
        layout = QVBoxLayout(self)
        intro = QLabel("Paste an API key to activate a provider. Keys are stored in Windows Credential Manager, "
                       "not in voices.yaml or any file in this folder. A key saved here is used instead of one "
                       "from your environment or .env.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        for provider, label in PROVIDER_LABELS.items():
            layout.addWidget(self._build_row(provider, label))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
        self._checked.connect(self._show_check)
        for provider in PROVIDER_LABELS:
            self._refresh(provider)

    def _build_row(self, provider, label):
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        grid = QGridLayout(frame)
        name = QLabel(label)
        font = name.font()
        font.setBold(True)
        name.setFont(font)
        status = QLabel()
        status.setWordWrap(True)
        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setPlaceholderText(f"Paste {provider_class(provider).env_var}")
        field.setAccessibleName(f"{label} API key")
        save = QPushButton("Save and test")
        remove = QPushButton("Remove")
        result = QLabel()
        result.setWordWrap(True)
        grid.addWidget(name, 0, 0)
        grid.addWidget(status, 0, 1, 1, 2)
        grid.addWidget(field, 1, 0, 1, 2)
        row = QHBoxLayout()
        row.addWidget(save)
        row.addWidget(remove)
        grid.addLayout(row, 1, 2)
        grid.addWidget(result, 2, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        field.returnPressed.connect(lambda p=provider: self._save(p))
        save.clicked.connect(lambda _=False, p=provider: self._save(p))
        remove.clicked.connect(lambda _=False, p=provider: self._remove(p))
        self._rows[provider] = {"status": status, "field": field, "save": save, "remove": remove,
                                "result": result, "seq": 0}
        return frame

    def _refresh(self, provider):
        row = self._rows[provider]
        saved, env = credentials.status(provider_class(provider).env_var)
        if saved:
            text = "Active: key saved in Windows Credential Manager"
            if env:
                text += " (the environment/.env key is ignored)"
        elif env:
            text = "Active: using the key from your environment or .env"
        else:
            text = "Not set up"
        row["status"].setText(text)
        row["remove"].setEnabled(saved)

    def _save(self, provider):
        row = self._rows[provider]
        if not row["save"].isEnabled():
            return  # a check is still running; Enter in the field must not bypass the disabled button
        key = row["field"].text().strip()
        if not key:
            row["result"].setText("Enter a key first.")
            return
        try:
            credentials.save(provider_class(provider).env_var, key)
        except (credentials.CredentialError, ValueError) as exc:
            row["result"].setText(str(exc))
            return
        row["field"].clear()
        row["save"].setEnabled(False)
        row["seq"] += 1
        row["result"].setText("Saved. Checking the key…")
        self._refresh(provider)
        self.keys_changed.emit(provider)
        threading.Thread(target=self._run_check, args=(provider, key, row["seq"]), daemon=True,
                         name=f"tts-keycheck-{provider}").start()

    def _run_check(self, provider, key, seq):
        try:
            outcome = (True, self._check(provider, key))
        except Exception as exc:  # noqa: BLE001 - worker/UI error boundary
            outcome = (False, describe_failure(provider, exc))
        try:
            self._checked.emit(provider, seq, *outcome)
        except RuntimeError:
            pass  # the dialog was closed and deleted while the check ran

    def _show_check(self, provider, seq, ok, message):
        row = self._rows[provider]
        if seq != row["seq"]:
            return  # the key was removed or replaced after this check started
        row["save"].setEnabled(True)
        row["result"].setText(message if ok else f"Saved, but the check failed. {message}")

    def _remove(self, provider):
        row = self._rows[provider]
        try:
            credentials.delete(provider_class(provider).env_var)
        except credentials.CredentialError as exc:
            row["result"].setText(str(exc))
            return
        row["seq"] += 1  # any check still running is now out of date
        row["save"].setEnabled(True)
        row["result"].setText("Removed.")
        self._refresh(provider)
        self.keys_changed.emit(provider)
