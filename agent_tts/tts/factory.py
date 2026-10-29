"""Provider registry and per-speaker routing.

`ProviderPool` builds each vendor adapter lazily from the environment (so a
missing key only fails for speakers that actually use that vendor) and routes
a speaker's line to the adapter named in voices.yaml.
"""
from typing import TYPE_CHECKING

from agent_tts.tts.base import Provider
from agent_tts.tts.cartesia_provider import CartesiaProvider
from agent_tts.tts.elevenlabs_provider import ElevenLabsProvider
from agent_tts.tts.xai_provider import XAIProvider

if TYPE_CHECKING:
    from pathlib import Path

    from agent_tts.config import Config, SpeakerConfig

PROVIDERS: dict[str, type[Provider]] = {
    cls.name: cls for cls in (XAIProvider, ElevenLabsProvider, CartesiaProvider)
}


def provider_class(name: str) -> type[Provider]:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ValueError(
            f"unknown provider {name!r}; choose from {sorted(PROVIDERS)}"
        ) from None


def create(
    name: str,
    output_format: str,
    cache_dir: "Path",
    lead_in_text: str = "",
    cache_max_mb: int = 0,
) -> Provider:
    return provider_class(name).from_env(output_format, cache_dir, lead_in_text, cache_max_mb)


class ProviderPool:
    def __init__(self, cfg: "Config"):
        self.cfg = cfg
        self._instances: dict[str, Provider] = {}

    def get(self, name: str) -> Provider:
        if name not in self._instances:
            self._instances[name] = create(
                name,
                self.cfg.output_format,
                self.cfg.cache_dir,
                self.cfg.lead_in_text,
                self.cfg.cache_max_mb,
            )
        return self._instances[name]

    def synth(self, text: str, speaker: "SpeakerConfig"):
        return self.get(speaker.provider).synth(text, speaker.voice_id, speaker.settings)

    def preflight(self, speakers: "list[SpeakerConfig] | None" = None) -> None:
        """Build the adapter for every provider in use so a missing key or
        bad output_format surfaces before playback starts. Raises
        RuntimeError or ValueError."""
        used = {s.provider for s in (speakers or self.cfg.speakers.values())}
        for name in sorted(used):
            self.get(name)
