import threading
import time

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from agent_tts import config
from agent_tts.tts.base import Voice
from agent_tts.ui_qt.window import Window
from tests.test_application import FakePlayer


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    yield instance


@pytest.fixture
def window(app, make_cfg, tmp_path, monkeypatch):
    path = tmp_path / "voices.yaml"
    config.save(make_cfg(), path)

    class Pool:
        def __init__(self, cfg):
            pass

        def get(self, provider):
            return self

        def list_voices(self):
            time.sleep(0.02)
            return [Voice(str(i), f"Voice {i:04}", "test", {"gender": "female" if i % 2 else "male"}, "") for i in range(1000)]

    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    widget = Window(path, enable_hotkeys=False, settings=settings,
                    controller_options={"player_factory": FakePlayer, "pool_factory": Pool})
    widget.show()
    deadline = time.monotonic() + 2
    while widget.voice_model.rowCount() != 1000 and time.monotonic() < deadline:
        QTest.qWait(10)
    assert widget.voice_model.rowCount() == 1000
    yield widget
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    widget.close()
    widget.controller._synth_thread.join(1)
    app.processEvents()


def test_model_filter_and_native_splitters(window):
    window.resize(920, 700)
    QTest.qWait(30)
    assert window.width() == 920
    assert window.height() == 700
    split = window.voice_split
    before = split.sizes()
    handle = split.handle(1)
    position = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=position)
    QTest.mouseMove(handle, position + QPoint(60, 0), 20)
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton)
    assert split.sizes() != before
    assert min(split.sizes()) >= 330
    window.search.setText("Voice 099")
    assert window.voice_model.rowCount() == 11
    window._toggle_filter("gender", "female", True)
    assert window.voice_model.rowCount() == 6


def test_drafts_survive_speaker_switch_and_save_only_selected(window):
    window.voice_id.setText("rex")
    window._edit_values()
    window.speaker.setCurrentText("ROOK")
    window.voice_id.setText("draft-rook")
    window._edit_values()
    window.speaker.setCurrentText("KIRA")
    assert window.voice_id.text() == "rex"
    window._save()
    saved = config.load(window.drafts.path)
    assert saved.speakers["KIRA"].voice_id == "rex"
    assert saved.speakers["ROOK"].voice_id == "voice-uuid"
    assert window.drafts.dirty == {"ROOK"}


def test_worker_bridge_delivery_is_on_ui_thread(window):
    from agent_tts.application.controller import Result
    seen = []
    original = window.controller.notify

    def notify(kind, data):
        seen.append(threading.get_ident())
        original(kind, data)

    window.controller.notify = notify
    worker = threading.Thread(target=lambda: window.bridge.result.emit(Result(0, "status", "worker result")))
    worker.start()
    worker.join()
    QTest.qWait(20)
    assert seen == [threading.get_ident()]
    assert window.status.text() == "worker result"


def test_listening_allows_previews_but_disables_speaker_tests(window):
    window.voice_list.setCurrentIndex(window.voice_proxy.index(0, 1))
    window.controller.listening = True
    window._notify("state", True)
    assert not window.test_button.isEnabled()
    assert window.preview_button.isEnabled()
    assert "queues after pending dialogue" in window.preview_button.toolTip()
    assert window.test_button.toolTip() == "Stop listening to audition."
    window.transcript.setPlainText("\n".join(str(i) for i in range(2200)))
    assert window.transcript.document().blockCount() == 2000


def test_assign_provider_reset_favorite_and_revert(window, monkeypatch):
    window.speaker.setCurrentText("ROOK")
    window.voice_list.setCurrentIndex(window.voice_proxy.index(7, 1))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window._assign()
    draft = window.drafts.speakers["ROOK"]
    assert draft.provider == "xai" and draft.voice_id == "7"
    assert draft.settings == {}
    window._favorite()
    saved = config.load(window.drafts.path)
    assert saved.voice_library_favorites == ["7"]
    assert saved.speakers["ROOK"].provider == "cartesia"
    window._revert()
    assert window.drafts.speakers["ROOK"].voice_id == "voice-uuid"


def test_scrolled_transcript_does_not_jump_to_bottom(window):
    window.transcript.setPlainText("\n".join(str(i) for i in range(300)))
    scrollbar = window.transcript.verticalScrollBar()
    scrollbar.setValue(50)
    window._notify("transcript", ("KIRA", "New dialogue"))
    assert scrollbar.value() == 50


def test_sorting_keeps_assignment_and_favorite_bound_to_voice(window):
    window.voice_list.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    window.voice_list.setCurrentIndex(window.voice_proxy.index(0, 1))
    assert window.selected_voice.voice_id == "999"
    window._assign()
    assert window.drafts.speakers["KIRA"].voice_id == "999"
    window._favorite()
    assert window.selected_voice.voice_id == "999"
    assert config.load(window.drafts.path).voice_library_favorites == ["999"]
    window.favorites_only.setChecked(True)
    assert window.voice_model.rowCount() == 1
    assert window.selected_voice.voice_id == "999"
    window._favorite()
    assert window.voice_model.rowCount() == 0
    assert window.selected_voice is None
    assert not window.assign_button.isEnabled()
    assert window.catalog_stack.currentWidget() == window.empty_catalog


def test_searches_metadata_combines_facets_and_resets(window):
    window.search.setText("female 099")
    assert window.voice_model.rowCount() == 6
    window._toggle_filter("category", "test", True)
    assert window.voice_model.rowCount() == 6
    window._toggle_filter("gender", "male", True)
    assert window.voice_model.rowCount() == 0
    assert "No matching voices" in window.empty_catalog.text()
    window._clear_filters()
    assert window.voice_model.rowCount() == 1000
    assert not window.filter_summary.isVisible()


def test_provider_column_choices_survive_tab_switch(window):
    assert not window.voice_list.isColumnHidden(2)  # Gender is available.
    assert window.voice_list.isColumnHidden(3)  # No language in fixture metadata.
    window.column_actions[5].setChecked(True)
    window.tabs.setCurrentIndex(2)
    QTest.qWait(60)
    assert window.voice_list.isColumnHidden(5)
    window.tabs.setCurrentIndex(0)
    assert not window.voice_list.isColumnHidden(5)


def test_table_star_click_toggles_selected_voice(window):
    index = window.voice_proxy.index(3, 0)
    point = window.voice_list.visualRect(index).center()
    QTest.mouseClick(window.voice_list.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert config.load(window.drafts.path).voice_library_favorites == ["3"]


def test_metadata_display_and_search_use_readable_language_names(window):
    from agent_tts.ui_qt.voice_model import display_label
    assert display_label("accent", "MX") == "Mexico"
    assert display_label("accent", "SA") == "Saudi Arabia"
    voices = [Voice("voice-a", "Alice", "public",
                    {"gender": "feminine", "language": "en", "accent": "US",
                     "description": "Calm documentary narrator"}, "")]
    window._notify("catalog", ("xai", voices))
    window.search.setText("female English documentary")
    assert window.voice_model.rowCount() == 1
    assert window.voice_model.data(window.voice_model.index(0, 3)) == "English"
    assert window.voice_model.data(window.voice_model.index(0, 4)) == "United States"
    window._toggle_filter("language", "en", True)
    assert window.voice_model.rowCount() == 1
    assert "Language: English" in window.filter_summary.text()


def test_row_preview_uses_sorted_voice_without_assignment(window, monkeypatch):
    window.controller.listening = True
    window._notify("state", True)
    calls = []
    monkeypatch.setattr(window.controller, "preview", lambda provider, voice: calls.append((provider, voice.voice_id)))
    window.voice_list.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    index = window.voice_proxy.index(0, 8)
    assert not window.voice_list.isColumnHidden(8)
    QTest.mouseClick(window.voice_list.viewport(), Qt.MouseButton.LeftButton,
                    pos=window.voice_list.visualRect(index).center())
    assert calls == [("xai", "999")]
    assert window.preview_button.isEnabled()
    assert not window.drafts.dirty
    assert "API credits" in window.preview_button.toolTip()


def test_silent_checkbox_disables_voice_controls_and_saves_without_a_voice(window):
    window.speaker.setCurrentText("KIRA")
    assert window.voice_id.isEnabled() and window.test_button.isEnabled()
    window.muted.setChecked(True)
    assert not window.voice_id.isEnabled() and not window.test_button.isEnabled()
    assert not window.editor_provider.isEnabled()
    assert "KIRA" in window.drafts.dirty
    window.voice_id.setEnabled(True)
    window.voice_id.setText("")
    window._edit_values()
    window._save()
    assert config.load(window.drafts.path).speakers["KIRA"].muted is True
    window.muted.setChecked(False)
    assert window.voice_id.isEnabled() and window.test_button.isEnabled()


def test_hint_shown_when_no_provider_has_a_key(window, monkeypatch):
    for var in ("XAI_API_KEY", "ELEVENLABS_API_KEY", "CARTESIA_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    window._update_key_hint()
    assert "Providers" in window.status.text()
