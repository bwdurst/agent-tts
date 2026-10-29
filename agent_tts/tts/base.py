"""Provider interface for Agent TTS.

A provider turns text plus a voice id into an audio file. Each provider
declares the settings it understands (`settings_schema`); the base class
validates and fills defaults so only effective settings reach the request
and the cache key. Providers implement `_request` (network call returning
audio bytes) and `list_voices`; caching, text preparation, and eviction live
here so adapters stay small.
"""
import os
import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_tts.tts import cache

PLACEHOLDER_VOICE = "TODO_PICK_VOICE"

class CatalogLimitError(ValueError):
    """Provider pagination did not yield a complete bounded catalog."""

# Expression markup the voice protocol and xAI use. Only these are stripped for
# engines that would read them aloud; other brackets and angle-bracket text in
# prose (generics, JSX names, "[see notes]") are left alone.
EXPRESSION_TAGS = (
    "pause", "long-pause", "laugh", "laughter", "chuckle", "giggle", "cry", "sigh",
    "gasp", "hmm", "thoughtful", "exhale", "inhale", "breath", "tsk", "cough",
    "clear-throat", "analytical", "serious", "determined", "focused", "excited",
    "skeptical", "curious", "warm", "whispers", "whisper", "sarcastic", "angry",
    "delighted", "proud", "nervous", "laughs", "sighs",
)
WRAPPING_TAGS = (
    "whisper", "slow", "fast", "soft", "loud", "emphasis", "singing", "sing-song",
    "build-intensity", "decrease-intensity", "higher-pitch", "lower-pitch",
)
_BRACKET_TAG_RE = re.compile(r"\[(?:%s)\]" % "|".join(map(re.escape, EXPRESSION_TAGS)), re.I)
_WRAP_TAG_RE = re.compile(r"</?(?:%s)>" % "|".join(map(re.escape, WRAPPING_TAGS)), re.I)


@dataclass
class Voice:
    voice_id: str
    name: str
    category: str
    labels: dict[str, str]
    preview_url: str

    @property
    def description(self) -> str:
        # Character first (description/use_case), then demographics, then
        # accent. Empty fields drop off the end cleanly.
        parts = []
        for key in ("description", "use_case", "age", "gender", "accent", "language"):
            val = self.labels.get(key)
            if val:
                parts.append(str(val))
        return ", ".join(parts) if parts else self.category


@dataclass(frozen=True)
class SettingSpec:
    kind: str  # "float" | "bool" | "str" | "choice"
    default: Any
    lo: float | None = None
    hi: float | None = None
    choices: tuple[str, ...] = ()

    def coerce(self, value: Any) -> Any:
        """Return `value` converted to this spec's type, clamped to range.
        Raises ValueError for values that cannot be interpreted."""
        if value is None:
            return self.default
        if self.kind == "float":
            v = float(value)
            if self.lo is not None:
                v = max(self.lo, v)
            if self.hi is not None:
                v = min(self.hi, v)
            return round(v, 3)
        if self.kind == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if self.kind == "choice":
            v = str(value)
            if v not in self.choices:
                raise ValueError(f"{v!r} not in {list(self.choices)}")
            return v
        return str(value)


def strip_tags(text: str, keep: tuple[str, ...] = ()) -> str:
    """Remove inline `[expression]` and wrapping `<tag>` markup the target
    engine would otherwise read aloud. Tags in `keep` (e.g. "[laughter]")
    survive."""
    def _bracket(m: re.Match) -> str:
        return m.group(0) if m.group(0).lower() in keep else ""

    text = _BRACKET_TAG_RE.sub(_bracket, text)
    text = _WRAP_TAG_RE.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


class Provider(ABC):
    name: str = ""
    env_var: str = ""
    audio_codecs: tuple[str, ...] = ("mp3", "wav")
    settings_schema: dict[str, SettingSpec] = {}

    def __init__(
        self,
        api_key: str,
        output_format: str,
        cache_dir: Path,
        lead_in_text: str = "",
        cache_max_mb: int = 0,
    ):
        self.api_key = api_key
        self.output_format = output_format or "mp3"
        self.codec = self._codec_for(self.output_format)
        self.cache_dir = cache_dir
        self.lead_in_text = lead_in_text
        self.cache_max_mb = cache_max_mb
        self.cache_keep = lambda: set()

    @classmethod
    def from_env(cls, *args, **kwargs) -> "Provider":
        key = os.environ.get(cls.env_var)
        if not key:
            raise RuntimeError(f"{cls.env_var} not set (check .env)")
        return cls(key, *args, **kwargs)

    def _codec_for(self, output_format: str) -> str:
        # Accepts "mp3", "wav", and legacy ElevenLabs strings like
        # "mp3_44100_128"; the leading token picks the codec.
        codec = (output_format or "mp3").lower().split("_")[0]
        if codec not in self.audio_codecs:
            raise ValueError(
                f"output_format {output_format!r} not supported by {self.name}; "
                f"use one of {list(self.audio_codecs)}"
            )
        return codec

    def resolve_settings(self, settings: dict[str, Any] | None) -> dict[str, Any]:
        """Effective settings: schema defaults overlaid with the caller's
        values. Keys outside the schema (for example ElevenLabs sliders left
        on an xAI speaker) are dropped, so they never reach the request or
        fragment the cache."""
        given = settings or {}
        out: dict[str, Any] = {}
        for name, spec in self.settings_schema.items():
            try:
                out[name] = spec.coerce(given.get(name))
            except (TypeError, ValueError) as e:
                raise ValueError(f"{self.name} setting {name!r}: {e}") from e
        return out

    def prepare_text(self, text: str, settings: dict[str, Any]) -> str:
        """Hook for engine-specific markup handling. Default: pass through."""
        return text

    def synth(self, text: str, voice_id: str, settings: dict[str, Any] | None = None) -> Path:
        if not voice_id or voice_id == PLACEHOLDER_VOICE:
            raise ValueError(
                f"no voice assigned (voice_id is {voice_id or 'empty'}); "
                f"pick a {self.name} voice in voices.yaml or the GUI"
            )
        eff = self.resolve_settings(settings)
        synth_text = self.prepare_text(self.lead_in_text + text, eff)
        k = cache.key(self.name, synth_text, voice_id, eff, self.output_format)
        out = cache.path_for(self.cache_dir, k, ext=self.codec)
        if out.exists() and out.stat().st_size > 0:
            cache.touch(out)
            return out
        audio = self._request(synth_text, voice_id, eff)
        if not audio:
            raise RuntimeError(f"{self.name} returned empty audio")
        # Write beside the target and rename so a concurrent reader or an
        # interrupted write never leaves a truncated file in the cache.
        tmp = out.with_name(f"{out.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_bytes(audio)
        os.replace(tmp, out)
        cache.evict(self.cache_dir, self.cache_max_mb, keep={out} | self.cache_keep())
        return out

    @abstractmethod
    def _request(self, text: str, voice_id: str, settings: dict[str, Any]) -> bytes:
        """POST to the vendor and return raw audio bytes. Raises on HTTP errors."""

    @abstractmethod
    def list_voices(self) -> list[Voice]:
        """Voice catalog for this account. Raises on auth or network errors."""
