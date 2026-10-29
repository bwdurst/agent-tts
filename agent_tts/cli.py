import argparse
import atexit
import sys
import threading
from pathlib import Path

import requests
from dotenv import load_dotenv

from agent_tts import config as cfgmod
from agent_tts import parser as parsermod
from agent_tts import player
from agent_tts.normalize import normalize
from agent_tts.parser import ASIDE, CODE, Block
from agent_tts.tts.factory import ProviderPool


_SYNTH_ERRORS = (RuntimeError, ValueError, OSError, requests.RequestException)


def _play_blocks(blocks: list[Block], cfg, pool, pq=None) -> None:
    """Synth and play a list of blocks. Uses PlayerQueue if provided,
    otherwise plays synchronously via player.play()."""
    for i, b in enumerate(blocks, 1):
        if b.speaker == CODE:
            if cfg.code_blocks == "skip":
                print(f"  _code (skipped)")
                continue
            sp = cfg.speaker("_default")
        elif b.speaker == ASIDE:
            if cfg.aside_blocks == "skip":
                print(f"  _aside (skipped)")
                continue
            sp = cfg.speaker("_default")
        else:
            sp = cfg.speaker(b.speaker)

        if sp.muted:
            print(f"  {b.speaker:10s} | (muted)")
            continue
        label = b.speaker
        preview = b.text[:60].replace("\n", " ")
        print(f"  {label:10s} | {preview}", flush=True)
        synth_text = normalize(b.text, b.speaker, cfg.pronunciations)
        try:
            audio_path = pool.synth(synth_text, sp)
        except _SYNTH_ERRORS as e:
            print(f"  synth failed for {label}: {e}", file=sys.stderr)
            continue
        if pq:
            pq.enqueue(audio_path, speaker=label)
        else:
            player.play(audio_path)


def _run_file(args, cfg) -> int:
    """M1 mode: parse a file and play it synchronously."""
    if args.text:
        if not args.speaker:
            print("error: --text requires --speaker", file=sys.stderr)
            return 2
        speaker = args.speaker.upper() if args.speaker.upper() in cfg.speakers else args.speaker
        blocks = [Block(speaker=speaker, text=args.text)]
    elif args.file:
        text = args.file.read_text(encoding="utf-8")
        blocks = parsermod.parse(text, parsermod.speaker_names(cfg.speakers))
    else:
        print("error: provide a file or --text/--speaker", file=sys.stderr)
        return 2

    print(f"[parsed {len(blocks)} block(s)]")
    for i, b in enumerate(blocks, 1):
        preview = b.text[:80].replace("\n", " ")
        print(f"  {i:2d}. {b.speaker:10s} | {preview}")

    if args.dry_run:
        return 0

    pool = ProviderPool(cfg)
    pool.preflight()

    for i, b in enumerate(blocks, 1):
        if b.speaker == CODE:
            if cfg.code_blocks == "skip":
                print(f"[{i}] _code (skipped)")
                continue
            sp = cfg.speaker("_default")
        elif b.speaker == ASIDE:
            if cfg.aside_blocks == "skip":
                print(f"[{i}] _aside (skipped)")
                continue
            sp = cfg.speaker("_default")
        else:
            sp = cfg.speaker(b.speaker)

        if sp.muted:
            print(f"[{i}] {b.speaker} (muted)")
            continue
        print(f"[{i}] {b.speaker} -> synth…", end="", flush=True)
        synth_text = normalize(b.text, b.speaker, cfg.pronunciations)
        audio_path = pool.synth(synth_text, sp)
        print(" play…", end="", flush=True)
        player.play(audio_path)
        print(" done.")

    return 0


def _run_live(args, cfg) -> int:
    """M2 mode: tail a Claude Code JSONL transcript and speak new assistant messages."""
    from agent_tts import hotkeys
    from agent_tts.ingest import transcript

    pool = ProviderPool(cfg)
    pool.preflight()

    if args.session:
        jsonl_path = Path(args.session)
        session_dir = None
    else:
        session_dir = transcript.find_session_dir()
        jsonl_path = transcript.find_latest_session(session_dir)

    print(f"[live] tailing {jsonl_path.name}")
    print(f"[live] auto-switches to new sessions when detected")
    print(f"[live] Ctrl+Shift+.  skip current block")
    print(f"[live] Ctrl+Shift+/  flush queue")
    print(f"[live] Ctrl+C        exit")

    pq = player.PlayerQueue()
    stop_event = threading.Event()

    hotkeys.register(on_skip=pq.skip, on_flush=pq.flush)
    atexit.register(hotkeys.unregister)
    pq.start()

    try:
        for text in transcript.tail(jsonl_path, from_end=True, stop_event=stop_event, session_dir=session_dir):
            blocks = parsermod.parse(text, parsermod.speaker_names(cfg.speakers))
            if not blocks:
                continue
            print(f"\n[new message: {len(blocks)} block(s)]")
            _play_blocks(blocks, cfg, pool, pq=pq)
    except KeyboardInterrupt:
        print("\n[live] shutting down…")
    finally:
        pq.stop()
        hotkeys.unregister()

    return 0


def main() -> int:
    load_dotenv()

    ap = argparse.ArgumentParser(prog="agent_tts", description="Speak agent dialogue.")
    ap.add_argument("file", type=Path, nargs="?", help="Dialogue file to read and speak.")
    ap.add_argument("--config", type=Path, default=Path("voices.yaml"))
    ap.add_argument("--dry-run", action="store_true", help="Parse and print blocks; don't synth.")
    ap.add_argument("--text", type=str, help="One-off line to speak (requires --speaker).")
    ap.add_argument(
        "--speaker",
        type=str,
        help="Speaker name for --text (KIRA, CADE, ROOK, SAGE, VEX, or _default).",
    )
    ap.add_argument("--live", action="store_true", help="Tail Claude Code's session transcript.")
    ap.add_argument("--gui", action="store_true", help="Launch the TTS dashboard GUI.")
    ap.add_argument("--session", type=str, help="Path to a specific .jsonl session file.")
    args = ap.parse_args()

    cfgmod.ensure_user_config(args.config)
    cfg = cfgmod.load(args.config)

    if args.gui:
        from agent_tts.gui import launch
        launch(config_path=args.config, session=args.session)
        return 0
    try:
        if args.live or args.session:
            return _run_live(args, cfg)
        return _run_file(args, cfg)
    except _SYNTH_ERRORS as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
