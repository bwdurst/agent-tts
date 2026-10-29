"""Windowless launcher for the Qt dashboard (relaunches itself under .venv pythonw)."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
os.chdir(root)
runtime = root / ".venv" / "Scripts" / "pythonw.exe"
if Path(sys.executable).resolve() != runtime.resolve():
    if not runtime.exists():
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "Install requirements-qt.txt into .venv first.", "Agent TTS", 0x10)
        raise SystemExit(1)
    subprocess.Popen([str(runtime), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=root)
else:
    from agent_tts.logging_setup import setup_logging
    log_path = setup_logging()
    try:
        from agent_tts.ui_qt.__main__ import main
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - windowed bootstrap must report missing dependencies
        sys.excepthook(*sys.exc_info())
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f"Agent TTS could not start. See {log_path}", "Agent TTS", 0x10)
