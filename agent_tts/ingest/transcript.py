"""Tail a Claude Code JSONL session transcript and yield assistant text blocks.

Automatically detects when a new session starts (new .jsonl file appears in
the project directory) and switches to tailing the latest one.
"""
import json
import os
import re
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

_CLAUDE_DIR = Path(os.path.expanduser("~")) / ".claude" / "projects"
_CODEX_DIR = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
_POLL_INTERVAL_S = 0.5
_SESSION_CHECK_INTERVAL = 5.0


def _encode_cwd(cwd: str) -> str:
    """Encode an absolute path into the project-directory name format
    that Claude Code uses under ~/.claude/projects/."""
    return re.sub(r"[^a-zA-Z0-9-]", "-", cwd)


def find_session_dir(cwd: Path | None = None) -> Path:
    cwd = cwd or Path.cwd()
    encoded = _encode_cwd(str(cwd))
    d = _CLAUDE_DIR / encoded
    if not d.exists():
        raise FileNotFoundError(f"No Claude project dir for CWD: {d}")
    return d


def find_latest_session(session_dir: Path) -> Path:
    jsonl_files = sorted(session_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not jsonl_files:
        raise FileNotFoundError(f"No .jsonl files in {session_dir}")
    return jsonl_files[-1]


def session_files(source="claude"):
    if source == "codex":
        return _CODEX_DIR.glob("**/rollout-*.jsonl")
    return _CLAUDE_DIR.glob("*/*.jsonl")


def find_latest_session_anywhere(source="claude") -> Path:
    files = list(session_files(source))
    if not files:
        raise FileNotFoundError(f"No {source.title()} session transcripts found")
    return max(files, key=lambda p: p.stat().st_mtime)


def _record_id(event):
    payload = event.get("payload")
    value = event.get("uuid") or (payload.get("id") if isinstance(payload, dict) else None)
    return value if isinstance(value, str) else None


def _extract_assistant_text(event: dict, include_progress=False) -> str | None:
    """Accept visible assistant text only; tolerate incomplete/malformed records."""
    if not isinstance(event, dict):
        return None
    if event.get("type") == "response_item":
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "message" or payload.get("role") != "assistant":
            return None
        phase = payload.get("phase")
        allowed = (None, "final", "final_answer", "commentary") if include_progress else (None, "final", "final_answer")
        if phase not in allowed:
            return None
        content = payload.get("content")
        text_type = "output_text"
    elif event.get("type") == "assistant":
        message = event.get("message")
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        text_type = "text"
    else:
        return None
    if not isinstance(content, list):
        return None
    texts = [c["text"] for c in content if isinstance(c, dict) and c.get("type") == text_type
             and isinstance(c.get("text"), str)]
    return "\n".join(texts) or None


def tail(
    jsonl_path: Path,
    *,
    from_end: bool = True,
    poll_interval: float = _POLL_INTERVAL_S,
    stop_event=None,
    session_dir: Path | None = None,
    scan_all_projects: bool = False,
    on_ready=None,
    source="claude",
    include_progress=False,
) -> Iterator[str]:
    """Yield assistant text blocks as they're appended to the JSONL file.

    If session_dir is provided, auto-switches to newer files within that dir.
    If scan_all_projects is True, auto-switches to the globally-newest .jsonl
    across every project under ~/.claude/projects/.
    """
    seen_uuids: set[str] = set()
    current_path = jsonl_path
    # Snapshot other sessions before listening so switching reads new records,
    # not their old history, and does not discard the response that triggered it.
    candidates = (session_files(source) if scan_all_projects else
                  session_dir.glob("*.jsonl") if session_dir else [])
    positions = {}
    if from_end:
        for path in candidates:
            try:
                positions[path] = path.stat().st_size
            except FileNotFoundError:
                pass
    initial = True

    def remember(position):
        positions[current_path] = position

    def check_newer() -> Path | None:
        if scan_all_projects:
            return _check_newer_global(current_path, source)
        if session_dir:
            return _check_newer(session_dir, current_path)
        return None

    while True:
        if stop_event and stop_event.is_set():
            return

        yield from _tail_one_file(
            current_path,
            seen_uuids=seen_uuids,
            from_end=from_end,
            poll_interval=poll_interval,
            stop_event=stop_event,
            check_newer=check_newer,
            on_ready=on_ready,
            start_position=None if initial else positions.get(current_path, 0),
            on_position=remember,
            include_progress=include_progress,
        )
        initial = False

        if stop_event and stop_event.is_set():
            return

        newer = check_newer()
        if newer:
            current_path = newer
            from_end = False
            continue
        break


def _check_newer(session_dir: Path, current: Path) -> Path | None:
    try:
        latest = find_latest_session(session_dir)
        if latest != current:
            return latest
    except FileNotFoundError:
        pass
    return None


def _check_newer_global(current: Path, source="claude") -> Path | None:
    try:
        latest = find_latest_session_anywhere(source)
        if latest != current and latest.stat().st_mtime > current.stat().st_mtime:
            return latest
    except FileNotFoundError:
        pass
    return None


def _tail_one_file(
    jsonl_path: Path,
    *,
    seen_uuids: set[str],
    from_end: bool,
    poll_interval: float,
    stop_event,
    check_newer,
    on_ready=None,
    start_position=None,
    on_position=None,
    include_progress=False,
) -> Iterator[str]:
    """Tail a single JSONL file. Returns when a newer session file is detected
    or stop_event is set."""
    next_check = time.monotonic() + _SESSION_CHECK_INTERVAL

    with open(jsonl_path, "r", encoding="utf-8") as f:
        if start_position is not None:
            f.seek(start_position if start_position <= jsonl_path.stat().st_size else 0)
        elif from_end:
            while True:
                position = f.tell()
                line = f.readline()
                if not line or not line.endswith("\n"):
                    f.seek(position)
                    break
                try:
                    ev = json.loads(line)
                    uuid = _record_id(ev) if isinstance(ev, dict) else None
                    if uuid:
                        seen_uuids.add(uuid)
                except (json.JSONDecodeError, KeyError):
                    pass

        if on_position:
            on_position(f.tell())
        if on_ready:
            on_ready(jsonl_path)
        while True:
            if stop_event and stop_event.is_set():
                return

            if time.monotonic() >= next_check:
                next_check = time.monotonic() + _SESSION_CHECK_INTERVAL
                if check_newer():
                    return
            position = f.tell()
            if jsonl_path.stat().st_size < position:
                f.seek(0)
                position = 0
            line = f.readline()
            if not line or not line.endswith("\n"):
                # Retry partial records after the writer completes its line.
                f.seek(position)
                if stop_event:
                    stop_event.wait(poll_interval)
                else:
                    time.sleep(poll_interval)
                continue

            if on_position:
                on_position(f.tell())
            line = line.strip()
            if not line:
                continue

            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            uuid = _record_id(ev) if isinstance(ev, dict) else None
            if uuid and uuid in seen_uuids:
                continue
            if uuid:
                seen_uuids.add(uuid)

            text = _extract_assistant_text(ev, include_progress)
            if text:
                yield text


def _end_of_complete_lines(path):
    with path.open("rb") as stream:
        stream.seek(0, 2)
        end = stream.tell()
        while end:
            start = max(0, end - 4096)
            stream.seek(start)
            chunk = stream.read(end - start)
            newline = chunk.rfind(b"\n")
            if newline >= 0:
                return start + newline + 1
            end = start
        return 0


def follow(source, *, stop_event, on_ready=None, on_error=None, poll_interval=.5, include_progress=False):
    """Read new messages from all local sessions, including concurrently active agents.

    Capture offsets once at startup. Newly created files start at zero; existing
    files start after their last complete record. A broken file cannot stop the
    other sessions or source. Read a bounded batch per file for fairness.
    """
    positions = {}
    seen = set()
    started = datetime.now(UTC)
    failures = set()
    for path in session_files(source):
        try:
            positions[path] = _end_of_complete_lines(path)
        except OSError:
            pass
    if on_ready:
        on_ready(f"{source.title()}: watching local sessions")
    while not stop_event.is_set():
        try:
            paths = list(session_files(source))
        except OSError as exc:
            if on_error:
                on_error(f"Cannot scan {source.title()} sessions: {type(exc).__name__}")
            stop_event.wait(poll_interval)
            continue
        for path in paths:
            if stop_event.is_set():
                return
            try:
                size = path.stat().st_size
                offset = positions.get(path, 0)
                if size == offset:
                    continue
                if size < offset:
                    offset = 0
                with path.open("rb") as stream:
                    stream.seek(offset)
                    for _ in range(500):
                        if stop_event.is_set():
                            return
                        line = stream.readline()
                        if not line or not line.endswith(b"\n"):
                            break
                        positions[path] = stream.tell()
                        try:
                            event = json.loads(line)
                        except (ValueError, UnicodeError):
                            continue
                        if not isinstance(event, dict):
                            continue
                        # New forks can contain historical messages copied from
                        # another rollout. Do not replay inherited history.
                        stamp = event.get("timestamp")
                        if isinstance(stamp, str):
                            try:
                                moment = datetime.fromisoformat(stamp)
                                if moment.tzinfo is not None and moment < started:
                                    continue
                            except ValueError:
                                pass
                        ident = _record_id(event)
                        if ident and ident in seen:
                            continue
                        if ident:
                            seen.add(ident)
                        text = _extract_assistant_text(event, include_progress)
                        if text:
                            if on_ready:
                                on_ready(f"{source.title()}: {path}")
                            yield text
                failures.discard(path)
            except OSError as exc:
                if path not in failures and on_error:
                    on_error(f"Cannot read {source.title()} session {path.name}: {type(exc).__name__}")
                failures.add(path)
        stop_event.wait(poll_interval)
