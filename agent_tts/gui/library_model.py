"""Per-provider voice library state, independent of Tk.

The Voice Library has one tab per provider. Each tab owns its own catalog,
load state, error and filters so switching tabs never refetches or loses a
search, and one vendor failing (missing key, 401) leaves the others usable.
"""
from dataclasses import dataclass, field

from agent_tts import voice_library
from agent_tts.tts.base import Voice
from agent_tts.tts.factory import PROVIDERS

TAB_LABELS = {"xai": "xAI", "elevenlabs": "ElevenLabs", "cartesia": "Cartesia"}
# Chip rows in display order. A category shows only when the catalog offers
# at least two distinct values, since a one-value filter can't narrow anything.
FILTER_CATEGORIES = ("gender", "accent", "language")


def tab_order() -> list[str]:
    """Provider ids in tab order: the known three first, then any others."""
    known = [p for p in TAB_LABELS if p in PROVIDERS]
    return known + [p for p in PROVIDERS if p not in TAB_LABELS]


def tab_label(provider: str) -> str:
    return TAB_LABELS.get(provider, provider)


def describe_error(provider: str, exc: Exception) -> str:
    """Plain-language reason a tab can't list voices, with the next step."""
    label = tab_label(provider)
    env_var = PROVIDERS[provider].env_var if provider in PROVIDERS else "API key"
    text = str(exc)
    if isinstance(exc, RuntimeError) and "not set" in text:
        return f"{label} is not set up. Add {env_var} to .env and restart the app."
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403):
        return (f"{label} rejected the API key ({status}). Check {env_var} in .env"
                f" and that the key can list voices.")
    if status:
        return f"{label} returned an error ({status}). Try again in a moment."
    return f"Couldn't reach {label}: {text}"


@dataclass
class TabState:
    provider: str
    voices: list[Voice] = field(default_factory=list)
    loaded: bool = False
    loading: bool = False
    error: str | None = None
    filters: dict[str, set[str]] = field(default_factory=dict)

    @property
    def needs_fetch(self) -> bool:
        return not self.loaded and not self.loading

    def start_load(self) -> None:
        self.loading = True
        self.error = None

    def finish_load(self, voices: list[Voice]) -> None:
        self.voices = voices
        self.loaded = True
        self.loading = False
        self.error = None

    def fail_load(self, message: str) -> None:
        self.loading = False
        self.error = message

    def categories(self) -> dict[str, list[str]]:
        """Chip values per category worth showing for this catalog."""
        out = {}
        for category in FILTER_CATEGORIES:
            values = voice_library.label_values(self.voices, category)
            if len(values) >= 2:
                out[category] = values
        return out

    def toggle_filter(self, category: str, value: str, on: bool) -> None:
        active = self.filters.setdefault(category, set())
        (active.add if on else active.discard)(value)

    def visible(self, search: str, favorites: list[str]) -> list[Voice]:
        return voice_library.filter_voices(
            self.voices, search=search, active_filters=self.filters, favorites=favorites)


class LibraryModel:
    """All tabs plus the selected one."""

    def __init__(self) -> None:
        self.tabs = {p: TabState(p) for p in tab_order()}
        self.selected = next(iter(self.tabs))

    def select(self, provider: str) -> TabState:
        if provider not in self.tabs:
            raise ValueError(f"unknown provider {provider!r}")
        self.selected = provider
        return self.tabs[provider]

    @property
    def current(self) -> TabState:
        return self.tabs[self.selected]
