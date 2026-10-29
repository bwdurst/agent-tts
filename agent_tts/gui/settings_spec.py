"""Map a provider's settings spec to the controls a speaker card shows.

GUI-agnostic so the mapping is testable without a display. The provider's
`settings_schema` is the single source of truth: a control exists only for
settings the provider declares, and slider ranges come from the spec's own
lo/hi, so xAI speed reaches 1.5 and Cartesia volume reaches 2.0.
"""
from dataclasses import dataclass
from typing import Any

from agent_tts.tts.base import SettingSpec
from agent_tts.tts.factory import provider_class

# Display order. Settings not listed follow in schema order.
_ORDER = ("model_id", "stability", "similarity_boost", "style", "speed", "volume",
          "emotion", "language", "use_speaker_boost", "text_normalization")
_LABELS = {
    "model_id": "model",
    "similarity_boost": "similarity",
    "use_speaker_boost": "speaker boost",
    "text_normalization": "normalize text",
}


@dataclass(frozen=True)
class Control:
    name: str
    label: str
    widget: str  # "slider" | "toggle" | "choice" | "text"
    default: Any
    lo: float | None = None
    hi: float | None = None
    step: float = 0.01
    choices: tuple[str, ...] = ()


def _control(name: str, spec: SettingSpec) -> Control:
    label = _LABELS.get(name, name.replace("_", " "))
    if spec.kind == "float" and spec.lo is not None and spec.hi is not None:
        return Control(name, label, "slider", spec.default, spec.lo, spec.hi)
    if spec.kind == "bool":
        return Control(name, label, "toggle", spec.default)
    if spec.kind == "choice":
        return Control(name, label, "choice", spec.default, choices=spec.choices)
    return Control(name, label, "text", spec.default)


def controls_for(provider: str) -> list[Control]:
    """Controls for `provider`, in display order. Raises ValueError for an
    unknown provider (same as provider_class)."""
    schema = provider_class(provider).settings_schema
    names = [n for n in _ORDER if n in schema] + [n for n in schema if n not in _ORDER]
    return [_control(n, schema[n]) for n in names]


def initial_values(provider: str, controls: list[Control], settings: dict[str, Any]) -> dict[str, Any]:
    """Starting value per control: the saved setting when valid, otherwise the
    provider default, so the card matches what live playback sends."""
    schema = provider_class(provider).settings_schema
    out: dict[str, Any] = {}
    for c in controls:
        # The provider's own coerce, so the card shows what playback sends
        # (for example a quoted "false" is False).
        try:
            value = schema[c.name].coerce(settings.get(c.name))
        except (TypeError, ValueError):
            value = c.default
        out[c.name] = "" if value is None else value
    return out


def settings_to_save(controls: list[Control], values: dict[str, Any],
                     existing: dict[str, Any]) -> dict[str, Any]:
    """Settings dict to write for a speaker. A value is written when the file
    already carries that key or it differs from the provider default, which
    keeps voices.yaml free of defaults the user never touched. Keys the
    controls don't cover (for example hand-edited ones) are preserved."""
    out = dict(existing)
    for c in controls:
        value = values[c.name]
        if c.widget == "slider":
            value = round(float(value), 2)
        if c.name in existing or value != c.default:
            out[c.name] = value
    return out
