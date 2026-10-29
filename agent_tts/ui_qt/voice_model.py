"""A lightweight table model: no per-voice widgets."""
from PySide6.QtCore import QAbstractTableModel, QLocale, QModelIndex, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionViewItem,
)

COLUMNS = (
    ("favorite", "★"), ("name", "Voice"), ("gender", "Gender"),
    ("language", "Language"), ("accent", "Accent"), ("age", "Age"),
    ("category", "Category"), ("description", "Description"), ("preview", "Preview"),
)


def display_label(key, value):
    """Readable provider metadata; retain unknown values instead of guessing."""
    value = str(value)
    if not value:
        return ""
    if key == "gender":
        return {"feminine": "Female", "masculine": "Male"}.get(value.casefold(), value.title())
    if key == "language":
        locale = QLocale(value.replace("-", "_"))
        if locale.language() != QLocale.Language.C:
            label = QLocale.languageToString(locale.language())
            if "_" in value or "-" in value:
                label += f" ({QLocale.territoryToString(locale.territory())})"
            return label
    if key == "accent" and len(value) == 2:
        territory = QLocale.codeToTerritory(value.upper())
        if territory != QLocale.Country.AnyTerritory:
            return QLocale.territoryToString(territory)
        return value.upper()
    return value.replace("_", " ").title()


class VoiceModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.voices = []
        self.listening = False
        self.favorites = set()
        self._name_font = QFont()
        self._name_font.setBold(True)

    def rowCount(self, parent=QModelIndex()):  # noqa: B008 - Qt model API
        return 0 if parent.isValid() else len(self.voices)

    def columnCount(self, parent=QModelIndex()):  # noqa: B008 - Qt model API
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if section == 0 and role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section][1]
        if section == 0 and role == Qt.ItemDataRole.ToolTipRole:
            return "Favorites — click a star to save or remove a favorite"
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.voices):
            return None
        voice = self.voices[index.row()]
        key = COLUMNS[index.column()][0]
        if key == "favorite":
            value = "★" if voice.voice_id in self.favorites else "☆"
        elif key == "name":
            value = voice.name
        elif key == "category":
            value = voice.category
        elif key == "description":
            value = voice.labels.get("description") or voice.labels.get("use_case") or ""
        elif key == "preview":
            value = "Preview"
        else:
            value = display_label(key, voice.labels.get(key, ""))
        if role == Qt.ItemDataRole.DisplayRole:
            return value or "—"
        if role == Qt.ItemDataRole.UserRole:
            if key == "favorite":
                return int(voice.voice_id in self.favorites)
            return str(value).casefold()
        if role == Qt.ItemDataRole.FontRole and key == "name":
            return self._name_font
        if role == Qt.ItemDataRole.TextAlignmentRole and key == "favorite":
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.ToolTipRole:
            if key == "favorite":
                return "Remove favorite" if voice.voice_id in self.favorites else "Add favorite"
            if key == "preview":
                hint = ("Play provider sample" if voice.preview_url else
                        "Generate a short sample using this provider (uses API credits)")
                return hint + ("; queues after pending dialogue" if self.listening else "")
            if key == "name":
                return f"{voice.name}\n{voice.voice_id}"
            return str(value) or "Not supplied by this provider"
        return None

    def replace(self, voices, favorites):
        self.beginResetModel()
        self.voices = voices
        self.favorites = set(favorites)
        self.endResetModel()


def browse_voices(voices, search, filters, favorites, favorites_only=False):
    """Search every metadata field. Facets are AND across groups, OR within."""
    terms = search.casefold().split()
    favorite_ids = set(favorites)
    result = []
    for voice in voices:
        if favorites_only and voice.voice_id not in favorite_ids:
            continue
        if any(allowed and (voice.category if key == "category" else voice.labels.get(key, "")) not in allowed
               for key, allowed in filters.items()):
            continue
        haystack = " ".join([voice.name, voice.voice_id, voice.category,
                             *(str(value) for value in voice.labels.values()),
                             *(display_label(key, voice.labels.get(key, ""))
                               for key in ("gender", "language", "accent", "age"))]).casefold()
        if all(term in haystack for term in terms):
            result.append(voice)
    return result


class PreviewDelegate(QStyledItemDelegate):
    """Paint only visible buttons, keeping large catalogs lightweight."""
    def paint(self, painter, option, index):
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, option.widget)
        button = QStyleOptionButton()
        button.rect = option.rect.adjusted(4, 3, -4, -3)
        button.text = "Preview"
        button.state = QStyle.StateFlag.State_Enabled
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_PushButton, button, painter, option.widget)
