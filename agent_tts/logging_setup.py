"""File diagnostics for windowed launches (no transcript or credentials)."""
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging() -> Path:
    folder = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AgentTTS" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "agent-tts.log"
    logger = logging.getLogger("agent_tts")
    if logger.handlers:
        return path
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    def report(kind, value, traceback):
        logger.error("Unhandled exception", exc_info=(kind, value, traceback))

    sys.excepthook = report
    threading.excepthook = lambda args: report(args.exc_type, args.exc_value, args.exc_traceback)
    logger.info("Application starting; Python %s", sys.version.split()[0])
    return path
