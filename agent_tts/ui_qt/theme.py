"""Colors for the Qt dashboard: graphite surfaces (set in __main__), one blue accent, a color per speaker."""
ACCENT = "#5aa9ff"
ACCENT_DEEP = "#3d7fd1"
OK = "#7fd99a"
DANGER = "#f08a8a"
MUTED = "#8f92a3"

from agent_tts.palette import SPEAKER_COLORS  # shared with the Tk dashboard

STYLE = f"""
QPushButton#primary {{
    background: {ACCENT_DEEP}; color: #ffffff; border: 1px solid {ACCENT};
    border-radius: 3px; padding: 4px 14px; font-weight: 600;
}}
QPushButton#primary:hover {{ background: #4f93e6; }}
QPushButton#primary:disabled {{ background: #303440; color: #818796; border: 1px solid #3a3f4d; }}
QPushButton#stopButton:enabled {{
    background: #7a3140; color: #ffffff; border: 1px solid #b5495c;
    border-radius: 3px; padding: 4px 14px;
}}
QPushButton#stopButton:enabled:hover {{ background: #8f3b4d; }}
"""


def speaker_color(name: str) -> str:
    """Color for a speaker's name; unlisted speakers (including NARRATOR) are neutral."""
    return SPEAKER_COLORS.get(name, MUTED)
