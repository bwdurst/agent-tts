"""Windowless launcher for Agent TTS Dashboard.
Runs via pythonw.exe (no console window) — pin the shortcut to your taskbar.
"""
import os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.argv = ["agent_tts", "--gui"]
from agent_tts.cli import main
main()
