import time

import pytest
import requests
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from agent_tts import credentials
from agent_tts.ui_qt.providers_dialog import ProvidersDialog, describe_failure


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("XAI_API_KEY", "ELEVENLABS_API_KEY", "CARTESIA_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


def test_save_stores_checks_and_clears_the_field(app):
    calls = []
    dialog = ProvidersDialog(check=lambda provider, key: calls.append((provider, key)) or "Key works (3 voices available).")
    changed = []
    dialog.keys_changed.connect(changed.append)
    row = dialog._rows["cartesia"]
    assert row["status"].text() == "Not set up" and not row["remove"].isEnabled()
    row["field"].setText("  my-key  ")
    row["save"].click()
    assert credentials.lookup("CARTESIA_API_KEY") == ("my-key", credentials.SAVED)
    assert row["field"].text() == ""  # the key is never shown again
    assert changed == ["cartesia"]
    wait_for(lambda: row["result"].text().startswith("Key works"))
    assert calls == [("cartesia", "my-key")]
    assert row["remove"].isEnabled() and "saved" in row["status"].text()
    assert "my-key" not in row["status"].text() + row["result"].text()


def test_failed_check_keeps_the_key_and_says_so(app):
    def reject(provider, key):
        response = requests.Response()
        response.status_code = 401
        raise requests.HTTPError(response=response)

    dialog = ProvidersDialog(check=reject)
    row = dialog._rows["elevenlabs"]
    row["field"].setText("bad")
    row["save"].click()
    wait_for(lambda: "check failed" in row["result"].text())
    assert "401" in row["result"].text() and "voices_read" in row["result"].text()
    assert credentials.lookup("ELEVENLABS_API_KEY") == ("bad", credentials.SAVED)


def test_remove_deletes_only_the_saved_key(app, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "env-key")
    credentials.save("XAI_API_KEY", "app-key")
    dialog = ProvidersDialog(check=lambda *a: "ok")
    row = dialog._rows["xai"]
    assert "environment/.env key is ignored" in row["status"].text()
    changed = []
    dialog.keys_changed.connect(changed.append)
    row["remove"].click()
    assert credentials.lookup("XAI_API_KEY") == ("env-key", credentials.ENVIRONMENT)
    assert "environment or .env" in row["status"].text()
    assert changed == ["xai"] and not row["remove"].isEnabled()


def test_empty_key_is_refused(app):
    dialog = ProvidersDialog(check=lambda *a: "ok")
    row = dialog._rows["xai"]
    row["save"].click()
    assert row["result"].text() == "Enter a key first."
    assert credentials.lookup("XAI_API_KEY") is None
    assert describe_failure("xai", requests.Timeout()) == "Provider timed out. Try again."
