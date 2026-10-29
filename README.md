# Agent TTS

A Windows app that reads AI coding agents' replies aloud, one voice per agent.

It watches the local transcript files that Claude Code and Codex write, picks out lines that start with an agent's name in capitals (`KIRA: ...`), and speaks each one through xAI, ElevenLabs, or Cartesia. Each speaker can use a different provider and voice. A dashboard lets you assign voices, preview them, and tune per-speaker settings.

Agent TTS does not depend on any particular set of agents. Anything that begins its spoken lines with `NAME: ` can be voiced. The reusable team it was built alongside is [agent-team](https://github.com/bwdurst/agent-team), whose personas use exactly this prefix convention.

## Requirements

- Windows 10 or 11. Playback uses Windows MCI (`winmm.dll`) and global hotkeys use the Win32 API.
- Python 3.14 (tested with 3.14.3). Earlier 3.x versions are untested.
- An API key from at least one provider. Speech usage is billed by the provider, separately from any AI model subscription.

## Install

```powershell
git clone https://github.com/bwdurst/agent-tts.git
cd agent-tts
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-qt.txt
copy .env.example .env
```

Put a key in `.env` for each provider you plan to use. Only providers assigned in `voices.yaml` need one.

| Provider | Variable | Notes |
| --- | --- | --- |
| xAI | `XAI_API_KEY` | Default provider in the shipped `voices.yaml`. |
| ElevenLabs | `ELEVENLABS_API_KEY` | Needs `text_to_speech`; add `voices_read` to browse voices in the dashboard. |
| Cartesia | `CARTESIA_API_KEY` | |

Never commit `.env`. It is in `.gitignore`.

## Run

Qt dashboard (Claude and Codex input):

```powershell
.\.venv\Scripts\pythonw.exe launch_tts_qt.pyw
```

The original Tkinter dashboard (Claude input only) needs only `requirements.txt`:

```powershell
python -m agent_tts --gui
```

In the dashboard, choose a listener source, press **Start**, and talk to your agent. Its next reply is spoken once it lands in the transcript. Browse the provider voice libraries, preview a voice, assign it to a speaker, then **Save**. Saving writes `voices.yaml`.

Keyboard: `Ctrl+Shift+.` skips the current clip and `Ctrl+Shift+/` flushes everything queued.

Command line:

```powershell
python -m agent_tts --dry-run test-dialogue.txt        # parse a file, no API calls
python -m agent_tts --text "Hello" --speaker KIRA      # speak one line
python -m agent_tts --live                             # tail the newest Claude Code session
```

## How it works

```
Claude Code / Codex transcript files (local JSONL)
        |  tailed by agent_tts.ingest.transcript
        v
agent_tts.parser        NAME: blocks -> [Block(speaker, text), ...]
        |
        v
agent_tts.tts           per-speaker provider (xai | elevenlabs | cartesia) + on-disk cache
        |
        v
agent_tts.player        Windows MCI playback queue
```

Claude transcripts are read from `~/.claude/projects`. Codex rollouts are read from `$CODEX_HOME/sessions`, defaulting to `~/.codex/sessions`. This is a local-file integration and depends on those applications' file formats, so a format change in either can break it. Codex replies are voiced when complete. Reasoning, tool output, and user messages are never spoken.

### Writing agents so they sound right

- Start every spoken paragraph with the agent's uppercase name, a colon, and a space, at the start of the line.
- Text with no prefix is skipped when the reply contains any prefix.
- Code blocks and tool output are not voiced by default (`code_blocks: skip`).
- Markdown blockquotes (`>`) are treated as written asides and are not voiced by default (`aside_blocks: skip`). Put detail you want to read but not hear there.
- Speakers must be listed in `voices.yaml`. Built-in names are `KIRA`, `TANIS`, `CADE`, `ROOK`, `SAGE`, `VEX`, and `NARRATOR`. To add one, add it to `SPEAKERS` in `agent_tts/parser.py` and to `voices.yaml`.

## Configuring voices

Each speaker names a provider, a voice id, and provider-specific settings, so one session can mix vendors:

```yaml
speakers:
  KIRA:
    provider: xai
    voice_id: eve
    settings: {speed: 1.1}
  ROOK:
    provider: cartesia
    voice_id: <voice uuid>
    settings: {model_id: sonic-3.6, emotion: calm}
  CADE:
    provider: elevenlabs
    voice_id: <voice id>
    settings: {model_id: eleven_multilingual_v2, stability: 0.7}
```

| Provider | Settings | Inline tags |
| --- | --- | --- |
| `xai` | `speed` (0.7 to 1.5), `text_normalization`, `language` | `[pause]`, `[laugh]`, `<whisper>` passed through |
| `elevenlabs` | `model_id`, `stability`, `similarity_boost`, `style`, `speed`, `use_speaker_boost` | kept only for `eleven_v3` |
| `cartesia` | `model_id`, `language`, `speed`, `volume`, `emotion` | `[laughter]` kept, others stripped |

Settings outside a provider's schema are ignored. A speaker whose `voice_id` is `TODO_PICK_VOICE` fails with a clear message instead of calling the API. `output_format` accepts `mp3` or `wav`. Synthesized audio is cached under `cache_dir`, keyed by provider, text, voice, settings, and format, and trimmed to `cache_max_mb` by least-recently-used eviction.

Voice catalogs are bounded. If a provider's paging does not finish (a repeating or missing cursor, too many pages, or a 35 second deadline), the dashboard reports an error instead of showing a partial list as complete.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-qt-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The suite runs without network access. It does not cover audio quality or live provider behavior. Qt window tests create real windows, and Windows may print a harmless COM warning (`0x8001010D`) while they run.

## Troubleshooting

- **No sound, no error.** The speaker's voice id is probably stale; provider catalogs change. Re-pick a voice with **Browse** and Save.
- **`..._API_KEY not set`.** The speaker's provider has no key in `.env`.
- **ElevenLabs shows 401 in the voice browser.** The key lacks `voices_read`. Synthesis works with `text_to_speech` alone.
- **Filler words ("em", "hmm") before lines.** `lead_in_text` in `voices.yaml` is non-empty. Set it to `''`.
- **A hotkey does nothing.** Another application owns it. Use the buttons.

## Platform and scope

The parser, provider adapters, configuration, and cache are portable. Audio playback and hotkeys are Windows-only, so a macOS or Linux port would need a new `player.py` and `hotkeys.py`.

## License

[MIT](LICENSE).
