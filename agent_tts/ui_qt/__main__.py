"""Run the Qt dashboard: python -m agent_tts.ui_qt [--config ...] [--session ...]."""
import argparse
import ctypes
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from agent_tts.logging_setup import setup_logging
from agent_tts.ui_qt.window import Window


def main():
    parser = argparse.ArgumentParser(description="Agent TTS Qt candidate")
    parser.add_argument("--config", type=Path, default=Path("voices.yaml"))
    parser.add_argument("--session")
    parser.add_argument("--no-hotkeys", action="store_true")
    args = parser.parse_args()
    log_path = setup_logging()
    load_dotenv()
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AgentTTS.Dashboard.1")
    app = QApplication(sys.argv)
    app.setApplicationName("Agent TTS")
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[2] / "assets" / "icon.ico")))
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {"Window": "#20222a", "WindowText": "#eeeeef", "Base": "#171920",
              "AlternateBase": "#292c36", "Text": "#eeeeef", "Button": "#303440",
              "ButtonText": "#eeeeef", "Highlight": "#3269c6", "HighlightedText": "#ffffff",
              "ToolTipBase": "#eeeeef", "ToolTipText": "#171920", "PlaceholderText": "#a0a5b3"}
    for role, color in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#818796"))
    app.setPalette(palette)
    try:
        window = Window(args.config, args.session, enable_hotkeys=not args.no_hotkeys)
    except Exception:  # noqa: BLE001 - log windowed startup failures
        sys.excepthook(*sys.exc_info())
        QMessageBox.critical(None, "Agent TTS could not start", f"Check the configuration and log:\n{log_path}")
        return 1
    window.show()
    QTimer.singleShot(0, lambda: logging.getLogger(__name__).info("Qt window shown; event loop ready"))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
