import re
from dataclasses import dataclass

SPEAKERS = ("KIRA", "TANIS", "CADE", "ROOK", "SAGE", "VEX", "NARRATOR")
SPEAKER_RE = re.compile(r"^(KIRA|TANIS|CADE|ROOK|SAGE|VEX|NARRATOR): (.*)$")
# Language tag is captured so we can tell "aside" blocks (displayed only,
# not voiced) from generic code blocks.
FENCE_RE = re.compile(r"^```(\w*)")

# Any of these language tags on a fence → treated as an "aside" block:
# content visible in the chat but skipped by TTS when aside_blocks is 'skip'.
ASIDE_LANGS = {"aside", "detail", "silent", "written"}

DEFAULT = "_default"
CODE = "_code"
ASIDE = "_aside"


@dataclass
class Block:
    speaker: str
    text: str


def parse(text: str) -> list[Block]:
    lines = text.splitlines()
    has_any_prefix = any(SPEAKER_RE.match(l) for l in lines)

    blocks: list[Block] = []
    current_speaker: str | None = None
    buffer: list[str] = []
    in_fence = False
    fence_kind: str = CODE  # CODE or ASIDE, set when the fence opens

    def flush():
        nonlocal current_speaker, buffer
        if current_speaker is not None:
            text = "\n".join(buffer).strip()
            if text:
                blocks.append(Block(current_speaker, text))
        current_speaker = None
        buffer = []

    for line in lines:
        if in_fence:
            if FENCE_RE.match(line):
                body = "\n".join(buffer).strip()
                if body:
                    blocks.append(Block(fence_kind, body))
                buffer = []
                current_speaker = None
                in_fence = False
            else:
                buffer.append(line)
            continue

        if line.lstrip().startswith(">"):
            flush()
            detail = line.lstrip()[1:].lstrip()
            if detail:
                blocks.append(Block(ASIDE, detail))
            continue

        fence_match = FENCE_RE.match(line)
        if fence_match:
            flush()
            in_fence = True
            lang = fence_match.group(1).lower()
            fence_kind = ASIDE if lang in ASIDE_LANGS else CODE
            continue

        m = SPEAKER_RE.match(line)
        if m:
            flush()
            current_speaker = m.group(1)
            buffer = [m.group(2)]
            continue

        if current_speaker is None:
            if has_any_prefix:
                continue
            current_speaker = DEFAULT
            buffer = [line]
        else:
            buffer.append(line)

    flush()
    return blocks
