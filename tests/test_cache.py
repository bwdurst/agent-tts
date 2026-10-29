import os

from agent_tts.tts import cache


def test_key_namespaced_by_provider():
    a = cache.key("xai", "hi", "v", {}, "mp3")
    b = cache.key("cartesia", "hi", "v", {}, "mp3")
    assert a != b


def test_key_varies_with_format_and_settings():
    base = cache.key("xai", "hi", "v", {"speed": 1.0}, "mp3")
    assert base != cache.key("xai", "hi", "v", {"speed": 1.1}, "mp3")
    assert base != cache.key("xai", "hi", "v", {"speed": 1.0}, "wav")
    assert base == cache.key("xai", "hi", "v", {"speed": 1.0}, "mp3")


def _write(d, name, size, mtime):
    p = d / name
    p.write_bytes(b"x" * size)
    os.utime(p, (mtime, mtime))
    return p


def test_evict_removes_least_recently_used(tmp_path):
    mb = 1024 * 1024
    old = _write(tmp_path, "old.mp3", mb, 1000)
    mid = _write(tmp_path, "mid.mp3", mb, 2000)
    new = _write(tmp_path, "new.wav", mb, 3000)
    removed = cache.evict(tmp_path, max_mb=2)
    assert removed == 1
    assert not old.exists() and mid.exists() and new.exists()


def test_evict_never_removes_keep_and_ignores_subdirs_and_other_files(tmp_path):
    mb = 1024 * 1024
    keep = _write(tmp_path, "keep.mp3", 2 * mb, 1000)
    other = _write(tmp_path, "other.mp3", mb, 2000)
    notes = _write(tmp_path, "notes.txt", 5 * mb, 500)
    sub = tmp_path / "voice_previews"
    sub.mkdir()
    prev = _write(sub, "p.mp3", 5 * mb, 400)
    cache.evict(tmp_path, max_mb=1, keep={keep})
    assert keep.exists()
    assert not other.exists()
    assert notes.exists() and prev.exists()


def test_evict_disabled_and_missing_dir(tmp_path):
    p = _write(tmp_path, "a.mp3", 10, 1)
    assert cache.evict(tmp_path, max_mb=0) == 0
    assert p.exists()
    assert cache.evict(tmp_path / "nope", max_mb=1) == 0


def test_touch_refreshes_recency(tmp_path):
    p = _write(tmp_path, "a.mp3", 10, 1000)
    cache.touch(p)
    assert p.stat().st_mtime > 1000


def test_evict_protects_all_pending_and_playing_files(tmp_path):
    mb = 1024 * 1024
    playing = _write(tmp_path, "playing.mp3", mb, 1000)
    pending = _write(tmp_path, "pending.mp3", mb, 2000)
    unused = _write(tmp_path, "unused.mp3", mb, 3000)
    cache.evict(tmp_path, 1, keep={playing, pending})
    assert playing.exists() and pending.exists()
    assert not unused.exists()
