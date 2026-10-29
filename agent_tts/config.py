import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_tts.tts.factory import PROVIDERS


@dataclass
class SpeakerConfig:
    provider: str
    voice_id: str
    settings: dict[str, Any]


@dataclass
class Config:
    provider: str  # default provider for speakers that don't name one
    output_format: str
    lead_in_text: str
    cache_dir: Path
    cache_max_mb: int
    code_blocks: str  # "skip" | "narrate"
    aside_blocks: str  # "skip" | "narrate"
    speakers: dict[str, SpeakerConfig]
    pronunciations: dict[str, dict[str, str]] = field(default_factory=dict)
    voice_library_favorites: list[str] = field(default_factory=list)

    def speaker(self, name: str) -> SpeakerConfig:
        return self.speakers.get(name) or self.speakers["_default"]


def _expand(path_str: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path_str)))


def save(cfg: "Config", path: str | Path = "voices.yaml") -> None:
    """Write the current config back to voices.yaml, preserving structure."""
    speakers = {}
    for name, sc in cfg.speakers.items():
        speakers[name] = {
            "provider": sc.provider,
            "voice_id": sc.voice_id,
            "settings": sc.settings,
        }

    data = {
        "provider": cfg.provider,
        "output_format": cfg.output_format,
        "lead_in_text": cfg.lead_in_text,
        "cache_dir": str(cfg.cache_dir),
        "cache_max_mb": cfg.cache_max_mb,
        "code_blocks": cfg.code_blocks,
        "aside_blocks": cfg.aside_blocks,
        "speakers": speakers,
        "pronunciations": cfg.pronunciations,
        "voice_library_favorites": list(cfg.voice_library_favorites),
    }
    path = Path(path)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as f:
            temp_path = Path(f.name)
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            f.flush()
            os.fsync(f.fileno())
        load(temp_path)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def load(path: str | Path = "voices.yaml") -> Config:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # An ElevenLabs-era file names an eleven_* model and no provider.
    legacy_default = "elevenlabs" if str(data.get("model", "")).startswith("eleven") else "xai"
    default_provider = data.get("provider", legacy_default)
    # Legacy files have no per-speaker provider; speakers fall back to the
    # file's default provider. The top-level `model` only selects that
    # default for old ElevenLabs files; models are per-speaker `model_id`.
    speakers = {
        name: SpeakerConfig(
            provider=s.get("provider") or default_provider,
            voice_id=s["voice_id"],
            settings=s.get("settings", {}) or {},
        )
        for name, s in data["speakers"].items()
    }
    for label, prov in [("provider", default_provider)] + [
        (f"speaker {n!r}", sc.provider) for n, sc in speakers.items()
    ]:
        if prov not in PROVIDERS:
            raise ValueError(f"voices.yaml {label}: unknown provider {prov!r}; use one of {sorted(PROVIDERS)}")
    if "_default" not in speakers:
        raise ValueError("voices.yaml must define a '_default' speaker")

    raw_pron = data.get("pronunciations") or {}
    pronunciations: dict[str, dict[str, str]] = {
        section: dict(rules or {}) for section, rules in raw_pron.items()
    }

    favorites_raw = data.get("voice_library_favorites") or []
    favorites: list[str] = [str(v) for v in favorites_raw if v]

    return Config(
        provider=default_provider,
        output_format=data.get("output_format", "mp3"),
        lead_in_text=data.get("lead_in_text", ""),
        cache_dir=_expand(data["cache_dir"]),
        cache_max_mb=int(data.get("cache_max_mb", 500)),
        code_blocks=data.get("code_blocks", "skip"),
        aside_blocks=data.get("aside_blocks", "skip"),
        speakers=speakers,
        pronunciations=pronunciations,
        voice_library_favorites=favorites,
    )
