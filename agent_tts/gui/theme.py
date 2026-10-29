"""Design tokens for the dashboard: dark surfaces, one blue accent, Segoe UI.

Text tiers were raised from the original palette: the dimmest grey measured
about 2.7:1 against the card surface, below the 4.5:1 floor for body text.
"""

BG          = "#121318"   # app background (cooler near-black)
BG_CARD     = "#1a1b24"   # surface (transcript panel, settings panel)
BG_ELEV     = "#232531"   # elevated surface (input fields, slider trough, button rest)
BG_HOVER    = "#2c2f3e"   # button hover
BORDER      = "#2e3142"
FG          = "#e8e9f0"   # primary text
FG_MUTED    = "#a9acbd"   # secondary (slider labels)
FG_DIM      = "#8a8da0"   # tertiary (placeholder, helper); >= 4.5:1 on BG_CARD
ACCENT      = "#3b82f6"   # the one accent color
ACCENT_HOVER = "#60a5fa"
ACCENT_FILL = "#2563eb"   # accent as a button fill; white text reaches 5:1
DANGER      = "#f38ba8"
OK          = "#a6e3a1"

SPEAKER_COLORS = {
    "KIRA":  "#ff9aa0",
    "CADE":  "#8ab4ff",
    "ROOK":  "#9fdf8e",
    "TANIS": "#7fd6d0",
    "SAGE":  "#f9d574",
    "VEX":   "#d3a2f5",
    "_default": "#8f92a3",
    "_code":    "#8a8da0",
}

STAR_ON = "★"
STAR_OFF = "☆"
STAR_COLOR_ON = "#f5c77a"
STAR_COLOR_OFF = FG_DIM

FONT_UI       = ("Segoe UI", 10)
FONT_UI_SMALL = ("Segoe UI", 9)
FONT_UI_BOLD  = ("Segoe UI Semibold", 10)
FONT_TITLE    = ("Segoe UI Semibold", 14)
FONT_SECTION  = ("Segoe UI Semibold", 11)
FONT_MONO     = ("Cascadia Mono", 9)
FONT_BODY     = ("Segoe UI", 10)
FONT_SPEAKER  = ("Segoe UI Semibold", 10)

# Minimum height of an interactive control in pixels. Tk pads text by the
# label's pady, so buttons are sized to land near this on a 100% display.
CLICK_PX = 36


def blend(c1: str, c2: str, t: float) -> str:
    """Linearly interpolate between two '#rrggbb' hex colors. t=0.0 returns
    c1 unchanged; t=1.0 returns c2. Used to build per-speaker body tints
    that carry speaker identity without sacrificing readability."""
    a = c1.lstrip("#")
    b = c2.lstrip("#")
    r = int(round(int(a[0:2], 16) * (1 - t) + int(b[0:2], 16) * t))
    g = int(round(int(a[2:4], 16) * (1 - t) + int(b[2:4], 16) * t))
    bl = int(round(int(a[4:6], 16) * (1 - t) + int(b[4:6], 16) * t))
    return f"#{r:02x}{g:02x}{bl:02x}"
