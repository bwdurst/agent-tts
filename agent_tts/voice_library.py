"""Voice library fetch + local filtering across providers. GUI-agnostic so
it can be exercised directly by tests. Voice parsing lives in each provider
adapter; this module owns filtering, favorites ordering, and previews."""
import os
import re
import threading
from pathlib import Path

import requests

from agent_tts.tts.base import Provider, Voice

__all__ = ["Voice", "download_preview", "fetch_voices", "filter_voices", "label_values"]


def fetch_voices(provider: Provider) -> list[Voice]:
    """Pull the voice catalog for one provider. Raises on auth / network
    errors; the GUI layer catches and surfaces them so the user sees a real
    message, not silent failure."""
    return provider.list_voices()


def label_values(voices: list[Voice], key: str) -> list[str]:
    """Deduplicated, sorted list of all non-empty values seen for a given
    label key. Drives filter-chip population."""
    seen: set[str] = set()
    for v in voices:
        val = v.labels.get(key)
        if val:
            seen.add(val)
    return sorted(seen, key=str.lower)


def filter_voices(
    voices: list[Voice],
    *,
    search: str = "",
    active_filters: dict[str, set[str]] | None = None,
    favorites: list[str] | None = None,
) -> list[Voice]:
    """Apply search + label filters, then sort favorites first.

    Search is case-insensitive name-substring. Filters are ANDed across
    label keys and ORed within a single key (standard faceted-search
    semantics). Favorites are floated to the top while preserving the
    post-filter ordering within each band."""
    active_filters = active_filters or {}
    fav_set = set(favorites or [])

    q = search.strip().lower()
    pattern = re.compile(re.escape(q), re.IGNORECASE) if q else None

    def matches(v: Voice) -> bool:
        if pattern and not pattern.search(v.name):
            return False
        for key, allowed in active_filters.items():
            if not allowed:
                continue
            got = v.labels.get(key, "")
            if got not in allowed:
                return False
        return True

    filtered = [v for v in voices if matches(v)]
    fav = [v for v in filtered if v.voice_id in fav_set]
    rest = [v for v in filtered if v.voice_id not in fav_set]
    return fav + rest


def download_preview(url: str, dest: Path, timeout: float | tuple[float, float] = (5, 30)) -> Path:
    """Download the stock preview audio to disk. If `dest` already exists and
    is non-empty, skip — preview URLs per voice are stable. Returns the
    path for the player. Raises ValueError if the voice has no preview URL."""
    if not url:
        raise ValueError("voice has no preview URL")
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(f"{dest.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temp.write_bytes(resp.content)
        os.replace(temp, dest)
    finally:
        temp.unlink(missing_ok=True)
    return dest
