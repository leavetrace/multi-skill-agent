"""Deterministic language utilities (CONTRACTS §6, WP1 spec §4.1).

Everything here is pure string processing: we never spend an LLM call on work code can do
exactly (normalization, digit mapping, script hints, token estimates, JSON extraction).
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from skillagent.core.types import LangHint

__all__ = [
    "detect_lang_hint",
    "estimate_tokens",
    "extract_json_object",
    "normalize_lang_code",
    "normalize_persian",
    "strip_think",
    "to_ascii_digits",
    "to_persian_digits",
    "truncate_to_tokens",
]

ZWNJ = "‌"
_TATWEEL = "ـ"

# Arabic code points that have a distinct standard Persian form.
_PERSIAN_CHAR_MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک"})
_ZWNJ_RUN = re.compile(f"{ZWNJ}{{2,}}")
_ZWNJ_NEAR_SPACE = re.compile(rf"{ZWNJ}+(?=\s)|(?<=\s){ZWNJ}+")

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_TO_ASCII = str.maketrans(
    {d: str(i % 10) for i, d in enumerate(_PERSIAN_DIGITS + _ARABIC_INDIC_DIGITS)} | {"٫": "."}
)
_TO_PERSIAN = str.maketrans({str(i): d for i, d in enumerate(_PERSIAN_DIGITS)})
_THOUSANDS_BETWEEN_DIGITS = re.compile(r"(?<=\d)٬(?=\d)")
_DOT_BETWEEN_DIGITS = re.compile(r"(?<=[0-9])\.(?=[0-9])")


def normalize_persian(text: str) -> str:
    """Map Arabic letter variants to Persian and clean ZWNJ/tatweel.

    Arabic `ي`/`ك` look identical to Persian `ی`/`ک` but are different code points, which
    breaks matching, BM25 and output checks. Digits are deliberately left alone: the
    original digits must survive for translation/summarization.
    """
    text = text.translate(_PERSIAN_CHAR_MAP).replace(_TATWEEL, "")
    text = _ZWNJ_RUN.sub(ZWNJ, text)
    return _ZWNJ_NEAR_SPACE.sub("", text)


def to_ascii_digits(text: str) -> str:
    """Persian/Arabic-Indic digits → ASCII, `٫` → `.`, and drop `٬` between digits.

    Produces the "calculation view" of a prompt so `۱٬۲۰۰ × ۳٫۵` becomes `1200 × 3.5`.
    """
    return _THOUSANDS_BETWEEN_DIGITS.sub("", text.translate(_TO_ASCII))


def to_persian_digits(text: str) -> str:
    """ASCII digits → Persian digits and a decimal `.` between digits → `٫`."""
    return _DOT_BETWEEN_DIGITS.sub("٫", text).translate(_TO_PERSIAN)


def _is_arabic_script(ch: str) -> bool:
    cp = ord(ch)
    return 0x0600 <= cp <= 0x06FF or 0xFB50 <= cp <= 0xFDFF or 0xFE70 <= cp <= 0xFEFF


def _is_latin_letter(ch: str) -> bool:
    return ch.isalpha() and unicodedata.name(ch, "").startswith("LATIN")


def detect_lang_hint(text: str) -> LangHint:
    """Script-ratio hint over letters only.

    This is a cheap prior for the router, not a language identifier: Finglish (Persian in
    Latin script) reads as `en` here on purpose, and the router decides `response_language`.
    Letters of other scripts (Cyrillic, CJK…) are ignored rather than guessed.
    """
    arabic = latin = 0
    for ch in text:
        if not ch.isalpha():
            continue
        if _is_arabic_script(ch):
            arabic += 1
        elif _is_latin_letter(ch):
            latin += 1
    total = arabic + latin
    if total == 0:
        return "unknown"
    share = arabic / total
    if share >= 0.85:
        return "fa"
    if share <= 0.15:
        return "en"
    return "mixed"


def estimate_tokens(text: str) -> int:
    """Conservative, language-aware token estimate (no tokenizer download needed).

    BPE tokenizers trained mostly on Latin text need ~4 chars/token for English but only
    ~2–3 chars/token for Persian (Persian tokenizes ~2–3× worse), and roughly one token per
    1–2 chars for other scripts/emoji. Over-estimating is the safe side: budgets reject or
    truncate a little early instead of overflowing a free-tier context or TPM limit.
    Whitespace is not counted (BPE merges it into neighbouring tokens).
    """
    if not text:
        return 0
    latin = arabic = other = 0
    for ch in text:
        if ch.isspace():
            continue
        if ch.isascii() or _is_latin_letter(ch):
            latin += 1
        elif _is_arabic_script(ch):
            arabic += 1
        else:
            other += 1
    return max(1, math.ceil(latin / 4 + arabic / 2.5 + other / 1.5))


_SENTENCE_END = ".!?؟"


def _is_sentence_boundary(text: str, i: int) -> bool:
    """A boundary char ends a sentence only if whitespace (or the end) follows it.

    This keeps `3.5` or `e.g.x` from being treated as sentence ends, so truncation can
    never split a token-like word.
    """
    ch = text[i]
    if ch == "\n":
        return True
    return ch in _SENTENCE_END and (i + 1 == len(text) or text[i + 1].isspace())


def truncate_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    """Fit `text` into `max_tokens` (by `estimate_tokens`), cutting at a clean boundary.

    Prefers the last sentence boundary, then the last whitespace; never cuts mid-word. A
    single word longer than the whole budget yields `""` (still flagged truncated) rather
    than a broken fragment.
    """
    if estimate_tokens(text) <= max_tokens:
        return text, False
    if max_tokens <= 0:
        return "", True
    # Largest prefix length that fits; the estimate is monotone in prefix length.
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate_tokens(text[:mid]) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    limit = lo
    for i in range(limit - 1, -1, -1):
        if _is_sentence_boundary(text, i) and (cut := text[: i + 1].rstrip()):
            return cut, True
    for i in range(limit, 0, -1):
        if i < len(text) and text[i].isspace() and (cut := text[:i].rstrip()):
            return cut, True
    return "", True


# --- language codes -------------------------------------------------------------------

# fmt: off
_ISO_639_1_TABLE = (
    "aa ab ae af ak am an ar as av ay az ba be bg bi bm bn bo br bs ca ce ch co cr cs cu cv "
    "cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho "
    "hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku "
    "kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn "
    "no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm "
    "sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi "
    "vo wa wo xh yi yo za zh zu"
)
_ISO_639_1 = frozenset(_ISO_639_1_TABLE.split())

# ISO 639-2/3 three-letter codes for the languages we expect, mapped to their 639-1 form.
_ISO_639_3 = {
    "fas": "fa", "per": "fa", "eng": "en", "deu": "de", "ger": "de", "fra": "fr",
    "fre": "fr", "ara": "ar", "spa": "es", "tur": "tr", "zho": "zh", "chi": "zh",
    "rus": "ru", "ita": "it", "jpn": "ja", "kor": "ko", "por": "pt", "nld": "nl",
    "dut": "nl", "hin": "hi", "urd": "ur", "heb": "he", "ell": "el", "gre": "el",
    "pol": "pl", "swe": "sv", "ukr": "uk", "aze": "az", "kur": "ku", "pus": "ps",
}

_LANG_NAMES = {
    # English names
    "persian": "fa", "farsi": "fa", "english": "en", "german": "de", "french": "fr",
    "arabic": "ar", "spanish": "es", "turkish": "tr", "chinese": "zh", "mandarin": "zh",
    "russian": "ru", "italian": "it", "japanese": "ja", "korean": "ko",
    "portuguese": "pt", "dutch": "nl", "hindi": "hi", "urdu": "ur", "hebrew": "he",
    "greek": "el", "polish": "pl", "swedish": "sv", "ukrainian": "uk",
    "azerbaijani": "az", "azeri": "az", "kurdish": "ku", "pashto": "ps",
    # Endonyms commonly typed in Latin script
    "deutsch": "de", "français": "fr", "francais": "fr", "español": "es", "espanol": "es",
    "italiano": "it", "türkçe": "tr", "turkce": "tr",
    # Persian names (looked up after normalize_persian, with spaces/ZWNJ removed)
    "فارسی": "fa", "پارسی": "fa", "انگلیسی": "en", "آلمانی": "de", "فرانسوی": "fr",
    "عربی": "ar", "ترکی": "tr", "ترکیاستانبولی": "tr", "اسپانیایی": "es", "اسپانیولی": "es",
    "روسی": "ru", "چینی": "zh", "ایتالیایی": "it", "ژاپنی": "ja", "کرهای": "ko",
    "پرتغالی": "pt", "هلندی": "nl", "هندی": "hi", "اردو": "ur", "عبری": "he",
    "یونانی": "el", "لهستانی": "pl", "سوئدی": "sv", "اوکراینی": "uk",
    "ترکیآذربایجانی": "az", "آذری": "az", "کردی": "ku", "پشتو": "ps",
}
# fmt: on

_REGION_SUFFIX = re.compile(r"^([a-z]{2,3})[-_][a-z0-9]{2,8}$")


def normalize_lang_code(value: object) -> str:
    """Map a code or language name (English or Persian) to a lowercase ISO 639-1 code.

    LLMs return "Persian", "Farsi", "فارسی", "fa-IR" or "FA" interchangeably; normalizing
    here means every downstream comparison is a plain string equality. Raises ValueError
    (not TypeError) so pydantic reports it as a normal validation error.
    """
    if not isinstance(value, str):
        raise ValueError(f"language must be a string, got {type(value).__name__}")
    key = normalize_persian(value).strip().lower()
    key = re.sub(r"^(?:زبان|the)\s+", "", key).removesuffix(" language")
    compact = re.sub(rf"[\s{ZWNJ}]+", "", key)
    if compact in _LANG_NAMES:
        return _LANG_NAMES[compact]
    if key in _LANG_NAMES:
        return _LANG_NAMES[key]
    if match := _REGION_SUFFIX.match(key):
        key = match.group(1)
    if key in _ISO_639_1:
        return key
    if key in _ISO_639_3:
        return _ISO_639_3[key]
    raise ValueError(
        f"unknown language {value!r}; use an ISO 639-1 code such as 'en', 'fa', 'de', 'fr'"
    )


# --- model-output cleanup -------------------------------------------------------------

_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN_UNTERMINATED = re.compile(r"^\s*<think\b[^>]*>.*\Z", re.IGNORECASE | re.DOTALL)
_THINK_ORPHAN_CLOSE = re.compile(r"^.*</think\s*>", re.IGNORECASE | re.DOTALL)


def strip_think(text: str) -> str:
    """Remove reasoning blocks some models emit even when thinking is "disabled".

    Handles complete `<think>…</think>` blocks, an unterminated leading `<think>…` (the
    model ran out of tokens while thinking → nothing usable), and an orphan `</think>`
    whose opening tag was injected by the chat template rather than generated.
    """
    text = _THINK_BLOCK.sub("", text)
    text = _THINK_OPEN_UNTERMINATED.sub("", text)
    if "</think" in text.lower():
        text = _THINK_ORPHAN_CLOSE.sub("", text, count=1)
    return text.strip()


_FENCED_BLOCK = re.compile(r"```[\w-]*[ \t]*\n?(.*?)```", re.DOTALL)


def _balanced_object_at(text: str, start: int) -> int | None:
    """Return the index just past the `}` that closes the `{` at `start`, or None."""
    depth = 0
    in_string = escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def extract_json_object(text: str) -> str:
    """Pull the first balanced top-level `{…}` out of noisy model output.

    Small models wrap JSON in markdown fences or chat around it ("Sure! Here is…"); this
    recovers the object without an extra LLM call. Brace matching respects JSON strings
    and escapes, so `"a}b"` inside a value does not end the object early.
    """
    # Fenced blocks first: prose before a fence may contain stray braces.
    candidates = [m.group(1) for m in _FENCED_BLOCK.finditer(text)] + [text]
    for chunk in candidates:
        for match in re.finditer(r"\{", chunk):
            end = _balanced_object_at(chunk, match.start())
            if end is not None:
                return chunk[match.start() : end]
    raise ValueError("no JSON object found in model output")
