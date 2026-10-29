"""Text normalization pipeline between parser and synth."""
import re


# ---------------------------------------------------------------------------
# Markdown stripping. Runs first so subsequent rules see plain prose.
# The parser already isolates fenced code blocks and aside blockquotes;
# this layer handles inline markdown that leaks into voiced text:
# emphasis, links, headers, list markers, stray blockquote arrows.
# Inline expression tags like `[pause]` or `[skeptical]` are deliberately
# preserved — the link rule requires `](url)` to follow, which single
# bracket pairs don't have.
# ---------------------------------------------------------------------------
_MARKDOWN_RULES: tuple[tuple[re.Pattern, str], ...] = (
    # Bold+italic combined: ***text*** / ___text___
    (re.compile(r"\*\*\*([^*]+)\*\*\*"), r"\1"),
    (re.compile(r"___([^_]+)___"), r"\1"),
    # Bold: **text** / __text__
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),
    (re.compile(r"__([^_]+)__"), r"\1"),
    # Italic: *text* / _text_ (avoid matching inside words)
    (re.compile(r"(?<![\w*])\*([^\s*][^*]*[^\s*])\*(?![\w*])"), r"\1"),
    (re.compile(r"(?<![\w_])_([^\s_][^_]*[^\s_])_(?![\w_])"), r"\1"),
    # Inline code: `code`
    (re.compile(r"`([^`]+)`"), r"\1"),
    # Strikethrough: ~~text~~
    (re.compile(r"~~([^~]+)~~"), r"\1"),
    # Image: ![alt](url) -> alt
    (re.compile(r"!\[([^\]]*)\]\([^)]+\)"), r"\1"),
    # Inline link: [text](url) -> text
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),
    # Reference link: [text][ref] -> text
    (re.compile(r"\[([^\]]+)\]\[[^\]]*\]"), r"\1"),
    # Headers: leading # ## ### at start of line
    (re.compile(r"^\s*#{1,6}\s+", re.MULTILINE), ""),
    # Stray blockquote markers (parser already routes asides; defends edges)
    (re.compile(r"^\s*>\s?", re.MULTILINE), ""),
    # Unordered list markers
    (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), ""),
    # Ordered list markers
    (re.compile(r"^\s*\d+\.\s+", re.MULTILINE), ""),
    # Horizontal rules
    (re.compile(r"^\s*[-*_]{3,}\s*$", re.MULTILINE), ""),
)


def strip_markdown(text: str) -> str:
    for pattern, replacement in _MARKDOWN_RULES:
        text = pattern.sub(replacement, text)
    return text


_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U0001F900-\U0001F9FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "]"
)

_ABBREV_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\be\.g\.", re.IGNORECASE), "for example"),
    (re.compile(r"\bi\.e\.", re.IGNORECASE), "that is"),
    (re.compile(r"\betc\.", re.IGNORECASE), "et cetera"),
    (re.compile(r"\bvs\.", re.IGNORECASE), "versus"),
    (re.compile(r"\bw/"), "with"),
    (re.compile(r" & "), " and "),
)

_HASH_CANDIDATE_RE = re.compile(r"\b[A-Za-z0-9]{16,}\b")

# ---------------------------------------------------------------------------
# Number helpers — deterministic US English; no dependency on num2words.
# Scope: 0..999_999 for integers, 1000..9999 for year formatting.
# ---------------------------------------------------------------------------
_ONES = (
    "zero", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
    "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
)
_TENS = (
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
)
_ORDINAL_ONES = (
    "", "first", "second", "third", "fourth", "fifth", "sixth",
    "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth",
    "thirteenth", "fourteenth", "fifteenth", "sixteenth",
    "seventeenth", "eighteenth", "nineteenth", "twentieth",
)
_ORDINAL_TENS = {20: "twentieth", 30: "thirtieth"}
_MONTHS = (
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _int_to_words(n: int) -> str:
    if n < 0:
        return "negative " + _int_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, u = divmod(n, 10)
        return _TENS[t] if u == 0 else f"{_TENS[t]}-{_ONES[u]}"
    if n < 1000:
        h, rest = divmod(n, 100)
        if rest == 0:
            return f"{_ONES[h]} hundred"
        return f"{_ONES[h]} hundred {_int_to_words(rest)}"
    if n < 1_000_000:
        th, rest = divmod(n, 1000)
        if rest == 0:
            return f"{_int_to_words(th)} thousand"
        return f"{_int_to_words(th)} thousand {_int_to_words(rest)}"
    # Beyond scope — spell digit-by-digit rather than invent words.
    return " ".join(_ONES[int(d)] for d in str(n))


def _year_to_words(n: int) -> str:
    if 2000 <= n <= 2009:
        rem = n - 2000
        return "two thousand" if rem == 0 else f"two thousand {_ONES[rem]}"
    if 1000 <= n <= 9999:
        hi, lo = divmod(n, 100)
        hi_w = _int_to_words(hi)
        if lo == 0:
            return f"{hi_w} hundred"
        if lo < 10:
            return f"{hi_w} oh {_ONES[lo]}"
        return f"{hi_w} {_int_to_words(lo)}"
    return _int_to_words(n)


def _day_ordinal(d: int) -> str:
    if 1 <= d <= 20:
        return _ORDINAL_ONES[d]
    if d in _ORDINAL_TENS:
        return _ORDINAL_TENS[d]
    t, u = divmod(d, 10)
    return f"{_TENS[t]}-{_ORDINAL_ONES[u]}"


# ---------------------------------------------------------------------------
# Rules.
# ---------------------------------------------------------------------------
def strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text)


def expand_abbreviations(text: str) -> str:
    for pattern, replacement in _ABBREV_RULES:
        text = pattern.sub(replacement, text)
    return text


_DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")


def normalize_dates(text: str) -> str:
    def _repl(m: re.Match) -> str:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return m.group(0)
        return f"{_MONTHS[mo]} {_day_ordinal(d)}, {_year_to_words(y)}"

    return _DATE_RE.sub(_repl, text)


# Optional leading 'version ' so "version v1.2.3" doesn't double-prefix.
_VERSION_RE = re.compile(
    r"\b(?:version\s+)?v(\d+(?:\.\d+)+)\b", re.IGNORECASE
)


def normalize_versions(text: str) -> str:
    def _repl(m: re.Match) -> str:
        parts = m.group(1).split(".")
        words = " point ".join(_int_to_words(int(p)) for p in parts)
        return f"version {words}"

    return _VERSION_RE.sub(_repl, text)


# Units are case-sensitive (conventional casing). Order in alternation
# matters: longer tokens first so "ms" wins over "s", "min" over nothing.
_UNIT_MAP: dict[str, tuple[str, str]] = {
    "MB":  ("megabyte", "megabytes"),
    "GB":  ("gigabyte", "gigabytes"),
    "KB":  ("kilobyte", "kilobytes"),
    "ms":  ("millisecond", "milliseconds"),
    "min": ("minute", "minutes"),
    "hr":  ("hour", "hours"),
    "px":  ("pixel", "pixels"),
    "s":   ("second", "seconds"),
    "%":   ("percent", "percent"),
}
_UNIT_RE = re.compile(
    r"(?<!\w)(\d+)(min|MB|GB|KB|ms|hr|px|s|%)(?!\w)"
)


def normalize_units(text: str) -> str:
    def _repl(m: re.Match) -> str:
        n_str, unit = m.group(1), m.group(2)
        n = int(n_str)
        # Decade shorthand guard: "1990s", "1980s" are decades, not seconds.
        if unit == "s" and n >= 1000:
            return m.group(0)
        singular, plural = _UNIT_MAP[unit]
        word = singular if n == 1 else plural
        return f"{_int_to_words(n)} {word}"

    return _UNIT_RE.sub(_repl, text)


_DECIMAL_RE = re.compile(r"(?<!\w)(-?)(\d+)\.(\d+)(?!\w)")
_INT_RE = re.compile(r"(?<!\w)(-?)(\d+)(?!\w)")


def normalize_numbers(text: str) -> str:
    def _dec(m: re.Match) -> str:
        sign, intp, decp = m.group(1), m.group(2), m.group(3)
        sign_w = "negative " if sign == "-" else ""
        int_w = _int_to_words(int(intp))
        dec_w = " ".join(_ONES[int(d)] for d in decp)
        return f"{sign_w}{int_w} point {dec_w}"

    text = _DECIMAL_RE.sub(_dec, text)

    def _int(m: re.Match) -> str:
        sign, n_str = m.group(1), m.group(2)
        n = int(n_str)
        # Keep larger ints literal — TTS handles them fine and spelling
        # every 4-digit count ("one thousand nine hundred twenty") is rarely
        # what a listener wants.
        if n > 20:
            return m.group(0)
        sign_w = "negative " if sign == "-" else ""
        return f"{sign_w}{_ONES[n]}"

    text = _INT_RE.sub(_int, text)
    return text


def shorten_hashes(text: str) -> str:
    def _repl(m: re.Match) -> str:
        s = m.group(0)
        has_digit = any(c.isdigit() for c in s)
        has_upper = any(c.isupper() for c in s)
        has_lower = any(c.islower() for c in s)
        # Word-like tokens (pure lowercase or pure uppercase with no digits)
        # pass through — avoids mangling real long words.
        if has_digit or (has_upper and has_lower):
            return f"ID ending in {s[-4:]}"
        return s

    return _HASH_CANDIDATE_RE.sub(_repl, text)


def apply_pronunciation_overrides(
    text: str,
    agent: str,
    pronunciations: dict[str, dict[str, str]],
) -> str:
    if not pronunciations:
        return text
    merged: dict[str, str] = {}
    merged.update(pronunciations.get("global") or {})
    merged.update(pronunciations.get(agent) or {})
    for source, target in merged.items():
        text = re.sub(rf"\b{re.escape(source)}\b", target, text)
    return text


def normalize(
    text: str,
    agent: str,
    pronunciations: dict[str, dict[str, str]] | None = None,
) -> str:
    text = strip_markdown(text)
    text = strip_emoji(text)
    text = expand_abbreviations(text)
    text = normalize_dates(text)
    text = normalize_versions(text)
    text = normalize_units(text)
    text = normalize_numbers(text)
    text = shorten_hashes(text)
    text = apply_pronunciation_overrides(text, agent, pronunciations or {})
    return text
