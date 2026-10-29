"""Standard Qt widgets, model-based voice rows, and a queued worker bridge."""
from PySide6.QtCore import (
    QObject,
    QSettings,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from agent_tts.application.controller import Controller
from agent_tts.application.drafts import Drafts, FileChangedError
from agent_tts.tts.factory import provider_class
from agent_tts.ui_qt.voice_model import (
    COLUMNS,
    PreviewDelegate,
    VoiceModel,
    browse_voices,
    display_label,
)
from agent_tts.voice_library import label_values

PROVIDER_LABELS = {"xai": "xAI", "elevenlabs": "ElevenLabs", "cartesia": "Cartesia"}
TEST_TEXT = "Testing, one, two, three. That's elegant. Wait, that's wrong. Let's see what you can do."


class Bridge(QObject):
    result = Signal(object)


class Window(QMainWindow):
    def __init__(self, config_path, session=None, *, enable_hotkeys=True,
                 settings=None, controller_options=None):
        super().__init__()
        self.setWindowTitle("Agent TTS — Qt rebuild")
        self.setMinimumSize(920, 700)
        self.resize(1180, 820)
        self.drafts = Drafts(config_path)
        self.settings = settings or QSettings("AgentTTS", "QtCandidate")
        self._loading_editor = False
        self._filters = {}
        self._catalogs = {}
        self._followed_sessions = {}
        self._catalog_messages = {}
        self._table_provider = None
        self._table_headers = {}
        self._configured_tables = set()
        self.bridge = Bridge(self)
        self.controller = Controller(self.drafts, self.bridge.result.emit, self._notify,
                                     enable_hotkeys=enable_hotkeys, **(controller_options or {}))
        self.bridge.result.connect(self._receive)
        self._build(session)
        self._load_editor()
        self._restore_layout()
        QTimer.singleShot(0, lambda: self.controller.fetch_catalog(self.provider))

    @Slot(object)
    def _receive(self, result):
        self.controller.receive(result)

    def _build(self, session):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        controls = QHBoxLayout()
        title = QLabel("Agent TTS")
        font = title.font()
        font.setPointSize(17)
        font.setBold(True)
        title.setFont(font)
        controls.addWidget(title)
        controls.addStretch()
        self.start_button = QPushButton("Start listening")
        self.stop_button = QPushButton("Stop")
        self.skip_button = QPushButton("Skip")
        self.flush_button = QPushButton("Flush")
        for button in (self.start_button, self.stop_button, self.skip_button, self.flush_button):
            controls.addWidget(button)
            button.setMinimumHeight(32)
        self.start_button.clicked.connect(lambda: self.controller.start(self.session.text().strip() or None, self.source.currentData(), self.progress_audio.isChecked()))
        self.stop_button.clicked.connect(self.controller.stop)
        self.skip_button.clicked.connect(self.controller.skip)
        self.flush_button.clicked.connect(self.controller.flush)
        self.skip_button.setToolTip("Skip current audio — Ctrl+Shift+.")
        self.flush_button.setToolTip("Discard queued and in-flight audio — Ctrl+Shift+/")
        self.stop_button.setEnabled(False)
        layout.addLayout(controls)
        source = QHBoxLayout()
        self.source = QComboBox()
        self.source.addItem("Claude + Codex", "both")
        self.source.addItem("Claude", "claude")
        self.source.addItem("Codex", "codex")
        self.source.setCurrentIndex(max(0, self.source.findData(self.settings.value("listen_source", "both"))))
        self.source.setToolTip("Listen to new replies from the selected apps")
        source.addWidget(self.source)
        self.progress_audio = QCheckBox("Codex progress")
        self.progress_audio.setToolTip("Also speak Codex progress updates; otherwise speak completed replies only")
        source.addWidget(self.progress_audio)
        self.session = QLineEdit(session or "")
        self.session.setPlaceholderText("Automatic — follow new replies in each selected app")
        self.browse_session = QPushButton("Browse…")
        self.browse_session.clicked.connect(self._browse_session)
        source.addWidget(self.session, 1)
        source.addWidget(self.browse_session)
        layout.addLayout(source)
        self.status = QLabel("Ready — choose a voice or start listening")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

        self.body_split = QSplitter(Qt.Orientation.Vertical)
        self.body_split.setChildrenCollapsible(False)
        self.body_split.setHandleWidth(8)
        transcript_box = QGroupBox("Live transcript")
        transcript_layout = QVBoxLayout(transcript_box)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setMaximumBlockCount(2000)
        self.transcript.setPlaceholderText("New assistant dialogue appears here while listening. Tests use unsaved speaker settings.")
        transcript_layout.addWidget(self.transcript)
        transcript_box.setMinimumHeight(100)
        self.body_split.addWidget(transcript_box)

        self.voice_split = QSplitter(Qt.Orientation.Horizontal)
        self.voice_split.setChildrenCollapsible(False)
        self.voice_split.setHandleWidth(8)
        self.voice_split.addWidget(self._build_editor())
        self.voice_split.addWidget(self._build_library())
        self.voice_split.setSizes([430, 700])
        self.body_split.addWidget(self.voice_split)
        self.body_split.setSizes([180, 530])
        layout.addWidget(self.body_split, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Saved voices are used for live listening")

    def _build_editor(self):
        group = QGroupBox("Speaker settings")
        group.setMinimumWidth(330)
        box = QVBoxLayout(group)
        self.speaker = QComboBox()
        self.speaker.addItems(list(self.drafts.speakers))
        self.speaker.currentTextChanged.connect(self._load_editor)
        box.addWidget(self.speaker)
        self.dirty_label = QLabel()
        box.addWidget(self.dirty_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        form_box = QVBoxLayout(content)
        basic = QFormLayout()
        self.editor_provider = QComboBox()
        for key, label in PROVIDER_LABELS.items():
            self.editor_provider.addItem(label, key)
        self.editor_provider.currentIndexChanged.connect(self._provider_changed)
        self.voice_id = QLineEdit()
        self.voice_id.textEdited.connect(self._edit_values)
        basic.addRow("Provider", self.editor_provider)
        basic.addRow("Voice ID", self.voice_id)
        form_box.addLayout(basic)
        self.settings_form = QFormLayout()
        form_box.addLayout(self.settings_form)
        form_box.addStretch()
        scroll.setWidget(content)
        box.addWidget(scroll, 1)
        self.test_text = QPlainTextEdit(TEST_TEXT)
        self.test_text.setMaximumHeight(80)
        self.test_text.setAccessibleName("Voice test text")
        box.addWidget(self.test_text)
        buttons = QHBoxLayout()
        self.revert_button = QPushButton("Revert")
        self.save_button = QPushButton("Save speaker")
        self.test_button = QPushButton("Test voice")
        self.revert_button.clicked.connect(self._revert)
        self.save_button.clicked.connect(self._save)
        self.test_button.clicked.connect(self._test)
        for button in (self.revert_button, self.save_button, self.test_button):
            buttons.addWidget(button)
        box.addLayout(buttons)
        return group

    def _build_library(self):
        group = QGroupBox("Voice library")
        group.setMinimumWidth(350)
        box = QVBoxLayout(group)
        top = QHBoxLayout()
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        for label in PROVIDER_LABELS.values():
            self.tabs.addTab(label)
        self.tabs.currentChanged.connect(self._tab_changed)
        top.addWidget(self.tabs, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(lambda: self.controller.fetch_catalog(self.provider, refresh=True))
        top.addWidget(self.refresh_button)
        box.addLayout(top)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search names, descriptions, languages…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        box.addWidget(self.search)
        filters = QHBoxLayout()
        self.filters_button = QToolButton()
        self.filters_button.setText("Filters")
        self.filters_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.filters_menu = QMenu(self.filters_button)
        self.filters_button.setMenu(self.filters_menu)
        self.filter_menus = {}
        for key in ("gender", "language", "accent", "age", "category"):
            self.filter_menus[key] = self.filters_menu.addMenu(key.title())
        filters.addWidget(self.filters_button)
        self.favorites_only = QCheckBox("Favorites only")
        self.favorites_only.toggled.connect(self._filter)
        filters.addWidget(self.favorites_only)
        filters.addStretch()
        self.columns_button = QToolButton()
        self.columns_button.setText("Columns")
        self.columns_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.columns_button.setMenu(QMenu(self.columns_button))
        filters.addWidget(self.columns_button)
        self.reset_filters = QPushButton("Reset")
        self.reset_filters.setToolTip("Clear search and all filters")
        self.reset_filters.clicked.connect(self._clear_filters)
        filters.addWidget(self.reset_filters)
        box.addLayout(filters)
        self.filter_summary = QLabel()
        self.filter_summary.setWordWrap(True)
        self.filter_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.filter_summary.hide()
        box.addWidget(self.filter_summary)
        self.library_status = QLabel("Loading voices…")
        self.library_status.setWordWrap(True)
        self.library_status.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(self.library_status)
        self.voice_model = VoiceModel(self)
        self.voice_proxy = QSortFilterProxyModel(self)
        self.voice_proxy.setSourceModel(self.voice_model)
        self.voice_proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.voice_list = QTableView()
        self.voice_list.setAccessibleName("Voice catalog")
        self.voice_list.setModel(self.voice_proxy)
        self.voice_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.voice_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.voice_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.voice_list.setShowGrid(False)
        self.voice_list.setAlternatingRowColors(True)
        self.voice_list.setWordWrap(False)
        self.voice_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.voice_list.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.voice_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.voice_list.verticalHeader().hide()
        self.voice_list.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.voice_list.verticalHeader().setDefaultSectionSize(30)
        header = self.voice_list.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setMinimumSectionSize(32)
        header.setSectionsMovable(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((36, 160, 85, 105, 110, 85, 110, 260, 100)):
            self.voice_list.setColumnWidth(column, width)
        for column in (4, 5, 6, 8):
            self.voice_list.setColumnHidden(column, True)
        self.column_actions = {}
        for column, (_, label) in enumerate(COLUMNS):
            action = self.columns_button.menu().addAction("Favorites" if column == 0 else label)
            action.setCheckable(True)
            action.setChecked(not self.voice_list.isColumnHidden(column))
            action.setEnabled(column not in (1, 8))  # Keep the voice name visible.
            action.toggled.connect(lambda checked, c=column: self._set_column_visible(c, checked))
            self.column_actions[column] = action
        self.voice_list.setItemDelegateForColumn(8, PreviewDelegate(self.voice_list))
        self.voice_list.setSortingEnabled(True)
        self.voice_list.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        self.voice_list.selectionModel().currentChanged.connect(self._selection_changed)
        self.voice_list.doubleClicked.connect(lambda index: self._assign() if index.column() not in (0, 8) else None)
        self.voice_list.clicked.connect(lambda index: self._favorite() if index.column() == 0 else self._preview() if index.column() == 8 else None)
        self.catalog_stack = QStackedWidget()
        self.catalog_stack.addWidget(self.voice_list)
        self.empty_catalog = QLabel("Loading voices…")
        self.empty_catalog.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_catalog.setWordWrap(True)
        self.empty_catalog.setTextFormat(Qt.TextFormat.PlainText)
        self.catalog_stack.addWidget(self.empty_catalog)
        box.addWidget(self.catalog_stack, 1)
        self.detail_title = QLabel("Select a voice")
        title_font = self.detail_title.font()
        title_font.setBold(True)
        self.detail_title.setFont(title_font)
        box.addWidget(self.detail_title)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.details.setMinimumHeight(55)
        self.details.setMaximumHeight(75)
        self.details.setPlaceholderText("Voice details and assignment information appear here.")
        box.addWidget(self.details)
        actions = QHBoxLayout()
        self.assign_button = QPushButton("Assign to speaker")
        self.favorite_button = QPushButton("Favorite")
        self.preview_button = QPushButton("Preview")
        self.assign_button.clicked.connect(self._assign)
        self.favorite_button.clicked.connect(self._favorite)
        self.preview_button.clicked.connect(self._preview)
        for button in (self.assign_button, self.favorite_button, self.preview_button):
            actions.addWidget(button)
            button.setEnabled(False)
        box.addLayout(actions)
        return group

    @property
    def provider(self):
        return list(PROVIDER_LABELS)[self.tabs.currentIndex()]

    @property
    def selected_voice(self):
        index = self.voice_proxy.mapToSource(self.voice_list.currentIndex())
        if index.isValid() and index.row() < len(self.voice_model.voices):
            return self.voice_model.voices[index.row()]
        return None

    def _load_editor(self, *_):
        self._loading_editor = True
        draft = self.drafts.speakers[self.speaker.currentText()]
        self.editor_provider.setCurrentIndex(self.editor_provider.findData(draft.provider))
        self.voice_id.setText(draft.voice_id)
        while self.settings_form.rowCount():
            self.settings_form.removeRow(0)
        self.setting_controls = {}
        for key, spec in provider_class(draft.provider).settings_schema.items():
            value = draft.settings.get(key, spec.default)
            if spec.kind == "float":
                control = QDoubleSpinBox()
                control.setRange(spec.lo if spec.lo is not None else -10000,
                                 spec.hi if spec.hi is not None else 10000)
                control.setDecimals(3)
                control.setSingleStep(0.05)
                control.setValue(float(value))
                control.valueChanged.connect(self._edit_values)
            elif spec.kind == "bool":
                control = QCheckBox()
                control.setChecked(spec.coerce(value))
                control.toggled.connect(self._edit_values)
            elif spec.kind == "choice":
                control = QComboBox()
                control.addItems(spec.choices)
                control.setCurrentText(str(value))
                control.currentTextChanged.connect(self._edit_values)
            else:
                control = QLineEdit(str(value))
                control.textEdited.connect(self._edit_values)
            control.setAccessibleName(key.replace("_", " "))
            self.setting_controls[key] = control
            self.settings_form.addRow(key.replace("_", " ").title(), control)
        self._loading_editor = False
        self._update_dirty()

    def _edit_values(self, *_):
        if self._loading_editor:
            return
        draft = self.drafts.speakers[self.speaker.currentText()]
        draft.voice_id = self.voice_id.text()
        for key, control in self.setting_controls.items():
            if isinstance(control, QDoubleSpinBox):
                value = control.value()
            elif isinstance(control, QCheckBox):
                value = control.isChecked()
            elif isinstance(control, QComboBox):
                value = control.currentText()
            else:
                value = control.text()
            draft.settings[key] = value
        self._update_dirty()

    def _provider_changed(self, *_):
        if self._loading_editor:
            return
        draft = self.drafts.speakers[self.speaker.currentText()]
        provider = self.editor_provider.currentData()
        if provider != draft.provider:
            if QMessageBox.question(self, "Change provider", "Reset this speaker's voice and settings for the new provider?") != QMessageBox.StandardButton.Yes:
                self._load_editor()
                return
            draft.provider, draft.voice_id, draft.settings = provider, "", {}
        self._load_editor()
        self.tabs.setCurrentIndex(list(PROVIDER_LABELS).index(provider))

    def _update_dirty(self):
        names = self.drafts.dirty
        current_dirty = self.speaker.currentText() in names
        self.dirty_label.setText("Unsaved: " + ", ".join(sorted(names)) if names else "All speaker settings saved")
        self.save_button.setEnabled(current_dirty)
        self.revert_button.setEnabled(current_dirty)
        self.assign_button.setText(f"Assign to {self.speaker.currentText()}")

    def _write_action(self, action):
        try:
            action()
        except FileChangedError:
            answer = QMessageBox.question(self, "File changed on disk",
                "voices.yaml changed on disk. Reload it? This discards all unsaved speaker edits.")
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    self.drafts.reload()
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    QMessageBox.warning(self, "Could not reload", str(exc))
                    return False
                self.speaker.blockSignals(True)
                self.speaker.clear()
                self.speaker.addItems(list(self.drafts.speakers))
                self.speaker.blockSignals(False)
                self._load_editor()
                self._filter()
            return False
        except Exception as exc:  # noqa: BLE001 - worker/UI error boundary
            QMessageBox.warning(self, "Could not save", str(exc))
            return False
        return True

    def _save(self):
        name = self.speaker.currentText()
        if self._write_action(lambda: self.drafts.save_speaker(name)):
            self._load_editor()
            self.statusBar().showMessage(f"Saved {name}", 5000)

    def _revert(self):
        self.drafts.revert(self.speaker.currentText())
        self._load_editor()

    def _test(self):
        text = self.test_text.toPlainText().strip()
        if text:
            self.controller.test_speaker(self.speaker.currentText(), text)

    def _tab_changed(self, *_):
        self._remember_columns()
        self._table_provider = self.provider
        self._apply_columns()
        self._filters.clear()
        self._rebuild_filters()
        self._filter()
        self.controller.fetch_catalog(self.provider)

    def _rebuild_filters(self):
        voices = self._catalogs.get(self.provider, [])
        for key, menu in self.filter_menus.items():
            menu.clear()
            values = sorted({v.category for v in voices if v.category}) if key == "category" else label_values(voices, key)
            for value in sorted(values, key=lambda value, key=key: display_label(key, value).casefold()):
                action = menu.addAction(display_label(key, value))
                action.setCheckable(True)
                action.setChecked(value in self._filters.get(key, set()))
                action.toggled.connect(lambda checked, k=key, v=value: self._toggle_filter(k, v, checked))
            menu.setEnabled(bool(values))
            if not values:
                menu.setToolTip("Not supplied by this provider")

    def _toggle_filter(self, key, value, checked):
        values = self._filters.setdefault(key, set())
        values.add(value) if checked else values.discard(value)
        self._filter()

    def _clear_filters(self):
        self._filters.clear()
        self.search.clear()
        self.favorites_only.setChecked(False)
        self._rebuild_filters()
        self._filter()

    def _filter(self, *_):
        selected = self.selected_voice
        voices = self._catalogs.get(self.provider, [])
        shown = browse_voices(voices, self.search.text(), self._filters,
                              self.drafts.saved.voice_library_favorites, self.favorites_only.isChecked())
        self.voice_model.replace(shown, self.drafts.saved.voice_library_favorites)
        if selected:
            for row, voice in enumerate(shown):
                if voice.voice_id == selected.voice_id:
                    self.voice_list.setCurrentIndex(self.voice_proxy.mapFromSource(self.voice_model.index(row, 1)))
                    break
        message = self._catalog_messages.get(self.provider)
        count_text = f"{len(voices):,} voices" if len(shown) == len(voices) else f"{len(shown):,} of {len(voices):,} voices"
        self.library_status.setText(message or count_text)
        self.refresh_button.setEnabled(self.provider not in self.controller._catalog_loading)
        self.catalog_stack.setCurrentIndex(0 if shown else 1)
        self.empty_catalog.setText(message or ("No matching voices\nTry a different search or reset your filters." if voices
                                              else "No voices available for this provider."))
        active = [f"{key.title()}: {', '.join(sorted(display_label(key, value) for value in values))}"
                  for key, values in self._filters.items() if values]
        count = sum(len(values) for values in self._filters.values())
        self.filters_button.setText(f"Filters ({count})" if count else "Filters")
        self.filter_summary.setText("  •  ".join(active))
        self.filter_summary.setVisible(bool(active))
        self.reset_filters.setEnabled(bool(count or self.search.text() or self.favorites_only.isChecked()))
        self._selection_changed()

    def _selection_changed(self, *_):
        voice = self.selected_voice
        for button in (self.assign_button, self.favorite_button):
            button.setEnabled(voice is not None)
        self.preview_button.setEnabled(bool(voice))
        if voice and not voice.preview_url:
            self.preview_button.setToolTip("Generate a short sample using this provider (uses API credits)")
        else:
            self.preview_button.setToolTip("Play this voice's provider sample")
        if self.controller.listening:
            self.preview_button.setToolTip(self.preview_button.toolTip() + "; queues after pending dialogue")
        if voice:
            self.detail_title.setText(voice.name)
            assigned = [name for name, draft in self.drafts.speakers.items()
                        if draft.provider == self.provider and draft.voice_id == voice.voice_id]
            usage = "Assigned to: " + ", ".join(assigned) if assigned else "Not assigned to a speaker"
            description = voice.labels.get("description") or voice.labels.get("use_case") or ""
            attributes = " • ".join(display_label(key, voice.labels[key])
                                    for key in ("gender", "language", "accent", "age") if voice.labels.get(key))
            self.details.setPlainText("\n".join(part for part in (
                description, attributes, usage, f"Voice ID: {voice.voice_id}") if part))
            favorite = voice.voice_id in self.drafts.saved.voice_library_favorites
            self.favorite_button.setText("Unfavorite" if favorite else "Favorite")
        else:
            self.detail_title.setText("Select a voice")
            self.details.clear()

    def _assign(self, *_):
        voice = self.selected_voice
        if voice is None:
            return
        draft = self.drafts.speakers[self.speaker.currentText()]
        if draft.provider != self.provider:
            if QMessageBox.question(self, "Change provider", "Assign this voice and reset the speaker's provider settings?") != QMessageBox.StandardButton.Yes:
                return
            draft.provider, draft.settings = self.provider, {}
        draft.voice_id = voice.voice_id
        self._load_editor()
        self._selection_changed()

    def _favorite(self):
        voice = self.selected_voice
        if voice and self._write_action(lambda: self.drafts.toggle_favorite(voice.voice_id)):
            self._filter()

    def _preview(self):
        voice = self.selected_voice
        if voice:
            self.controller.preview(self.provider, voice)

    def _browse_session(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Claude or Codex session", "", "Session transcripts (*.jsonl)")
        if path:
            self.session.setText(path)

    def _notify(self, kind, data):
        if kind == "state":
            if data:
                self._followed_sessions.clear()
            self.start_button.setEnabled(not data)
            self.stop_button.setEnabled(data)
            self.session.setEnabled(not data)
            self.source.setEnabled(not data)
            self.progress_audio.setEnabled(not data)
            self.browse_session.setEnabled(not data)
            self.test_button.setEnabled(not data)
            tooltip = "Stop listening to audition." if data else "Play the current unsaved settings"
            self.test_button.setToolTip(tooltip)
            self.voice_model.listening = data
            self.voice_list.viewport().update()
            self._selection_changed()
        elif kind == "status":
            self.status.setText(data)
        elif kind == "session":
            origin, _, path = data.partition(": ")
            self._followed_sessions[origin] = path
            details = "\n".join(f"{name}: {value}" for name, value in self._followed_sessions.items())
            self.status.setText("Listening — " + " + ".join(self._followed_sessions))
            self.status.setToolTip(details)
            self.statusBar().showMessage("Following: " + " | ".join(self._followed_sessions))
            self.statusBar().setToolTip(details)
        elif kind == "transcript":
            self.transcript.appendPlainText(f"{data[0]}: {data[1]}\n")
        elif kind in ("error", "log"):
            self.transcript.appendPlainText(f"[{kind}] {data}\n")
            if kind == "error":
                self.status.setText(data)
        elif kind == "player":
            event, name = data
            if event == "playing":
                self.status.setText(f"Speaking — {name}")
            elif event == "error":
                self.transcript.appendPlainText("[error] Audio playback failed. See the application log.")
            else:
                self.status.setText("Listening — waiting for dialogue" if self.controller.listening else "Ready")
        elif kind == "catalog_loading":
            self._catalog_messages[data] = "Loading voices…"
            if data == self.provider:
                self._filter()
        elif kind in ("catalog", "catalog_error"):
            provider, value = data
            if kind == "catalog":
                self._catalogs[provider] = value
                self._catalog_messages.pop(provider, None)
            else:
                self._catalog_messages[provider] = value
            if provider == self.provider:
                if provider not in self._configured_tables and kind == "catalog":
                    self._apply_columns()
                    self._configured_tables.add(provider)
                self._rebuild_filters()
                self._filter()

    def _set_column_visible(self, column, visible):
        self.voice_list.setColumnHidden(column, not visible)
        self._stretch_columns()
        if column == 7 and visible:
            self.voice_list.setColumnWidth(1, 160)

    def _stretch_columns(self):
        header = self.voice_list.horizontalHeader()
        description_visible = not self.voice_list.isColumnHidden(7)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive if description_visible else QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch if description_visible else QHeaderView.ResizeMode.Interactive)

    def _remember_columns(self):
        if self._table_provider:
            self._table_headers[self._table_provider] = self.voice_list.horizontalHeader().saveState()

    def _apply_columns(self):
        state = self._table_headers.get(self.provider)
        if state is None:
            state = self.settings.value("voice_table/" + self.provider)
        if state is not None:
            self.voice_list.horizontalHeader().restoreState(state)
        else:
            voices = self._catalogs.get(self.provider, [])
            for column, (key, _) in enumerate(COLUMNS):
                if column in (0, 1):
                    visible = True
                elif key in ("gender", "language", "accent"):
                    visible = any(v.labels.get(key) for v in voices)
                elif key == "description":
                    visible = any(v.labels.get("description") or v.labels.get("use_case") for v in voices)
                else:
                    visible = False
                self.voice_list.setColumnHidden(column, not visible)
        self.voice_list.setColumnHidden(1, False)
        self.voice_list.setColumnHidden(8, False)
        header = self.voice_list.horizontalHeader()
        header.moveSection(header.visualIndex(8), 2)
        self.voice_list.setColumnWidth(8, 110)
        self._stretch_columns()
        if state is None and not self.voice_list.isColumnHidden(7):
            self.voice_list.setColumnWidth(1, 160)
        for column, action in self.column_actions.items():
            action.blockSignals(True)
            action.setChecked(not self.voice_list.isColumnHidden(column))
            action.blockSignals(False)

    def _restore_layout(self):
        self._table_provider = self.provider
        self._apply_columns()
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        for key, splitter in (("body", self.body_split), ("voices", self.voice_split)):
            state = self.settings.value(key)
            if state is not None:
                splitter.restoreState(state)

    def closeEvent(self, event):
        if self.drafts.dirty:
            names = ", ".join(sorted(self.drafts.dirty))
            answer = QMessageBox.question(self, "Unsaved speaker settings",
                f"Discard unsaved edits to {names} and close? Choose No to save speakers first.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._remember_columns()
        for provider, header in self._table_headers.items():
            self.settings.setValue("voice_table/" + provider, header)
        self.settings.setValue("listen_source", self.source.currentData())
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("body", self.body_split.saveState())
        self.settings.setValue("voices", self.voice_split.saveState())
        self.controller.close()
        event.accept()
