"""Shared audio cache: provider-namespaced keys, path layout, LRU eviction.

Keys include the provider name so identical text and voice id on two vendors
never collide. Eviction is least-recently-used by mtime; a cache hit touches
the file so frequently replayed lines survive.
"""
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

AUDIO_EXTS = (".mp3", ".wav")
_KEY_STEM = re.compile(r"[0-9a-f]{64}")  # what key() produces; nothing else is ours to delete


def key(
    provider: str,
    text: str,
    voice_id: str,
    settings: dict[str, Any],
    output_format: str = "",
) -> str:
    blob = json.dumps(
        {
            "provider": provider,
            "text": text,
            "voice_id": voice_id,
            "settings": settings,
            "output_format": output_format,
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def path_for(cache_dir: Path, key_hex: str, ext: str = "mp3") -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{key_hex}.{ext}"


def touch(path: Path) -> None:
    """Mark a cache entry as recently used. Best effort: a concurrent
    eviction may have removed it."""
    try:
        os.utime(path, None)
    except OSError:
        pass


def evict(cache_dir: Path, max_mb: int, keep: set[Path] | None = None) -> int:
    """Delete least-recently-used audio files until the cache fits in
    `max_mb`. Only top-level files this cache wrote (audio named by a
    64-character hex key) count; subfolders such as voice_previews and any
    other audio in the folder are left alone. `keep` is never deleted. Returns the
    number of files removed. A non-positive limit disables eviction."""
    if max_mb <= 0 or not cache_dir.is_dir():
        return 0
    entries = []
    for p in cache_dir.iterdir():
        if p.suffix.lower() not in AUDIO_EXTS or not _KEY_STEM.fullmatch(p.stem):
            continue
        try:
            st = p.stat()
        except OSError:
            continue  # removed by a concurrent eviction
        if p.is_file():
            entries.append((st.st_mtime, st.st_size, p))
    total = sum(size for _, size, _ in entries)
    limit = max_mb * 1024 * 1024
    removed = 0
    for _, size, p in sorted(entries, key=lambda e: e[0]):
        if total <= limit:
            break
        if keep and p in keep:
            continue
        try:
            p.unlink(missing_ok=True)
        except OSError:
            continue  # still open in the player; try again on a later write
        total -= size
        removed += 1
    return removed
