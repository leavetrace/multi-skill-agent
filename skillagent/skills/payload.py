"""Separate the content to process from the user's instruction (CONTRACTS §12).

The router never copies the payload (ADR-002), so summarizer and translator receive the
whole prompt ("Translate this into Persian: …") and must find the content themselves.
Doing it deterministically keeps the instruction out of the translation without spending
an LLM call. When no rule fires we return the whole text with `uncertain=True`, and the
skill prompt tells the model to ignore any request wording it finds inside.

Rule order (first match wins): chained → quoted → after_colon → after_newline → whole.
`after_newline` covers both a leading cue line ("Summarize:\\n<text>") and a trailing one
("<text>\\n\\nSummarize this in 3 bullets").
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from skillagent.core.language import normalize_persian
from skillagent.core.types import SkillInput

__all__ = ["MAX_INSTRUCTION_WORDS", "Payload", "extract_payload", "is_cue_only"]

MAX_INSTRUCTION_WORDS = 15

PayloadMethod = Literal["chained", "quoted", "after_colon", "after_newline", "whole"]


class Payload(BaseModel):
    text: str
    method: PayloadMethod
    uncertain: bool


# --- cues --------------------------------------------------------------------------------

_LANGS_EN = (
    "english|persian|farsi|french|german|spanish|arabic|turkish|russian|chinese|italian|"
    "japanese|korean|portuguese|dutch|hindi|urdu"
)
_LANGS_FA = (
    "فارسی|انگلیسی|فرانسوی|آلمانی|اسپانیایی|عربی|ترکی|روسی|چینی|ایتالیایی|ژاپنی|کره‌ای|پرتغالی"
)
# Anything that marks a phrase as a summarize/translate request. Matched against
# `normalize_persian(text).lower()`, so Arabic ي/ك typed by the user still match.
_CUE = re.compile(
    rf"\btranslat\w*|\bsummar\w*|\btl;?\s?dr\b|\bkey points\b|\bmain points\b"
    rf"|\b(?:in|into|to)\s+(?:{_LANGS_EN})\b"
    rf"|ترجمه|خلاصه|چکیده|برگردان|نکات\s+(?:اصلی|کلیدی)"
    rf"|به\s+(?:زبان\s+)?(?:{_LANGS_FA})",
    re.IGNORECASE,
)
# A cue line must also read as a *request*, not as content that happens to say "summary"
# ("In summary, revenue grew 20%." must stay part of the text).
_EN_REQUEST = re.compile(
    r"^(?:(?:please|pls|now|then|and|also|kindly|ok|okay)[,\s]+)*"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?"
    r"(?:translate|summari[sz]e|tl;?\s?dr|condense|shorten|give\s+me|write|make|provide|"
    r"list|what\s+are\s+the\s+(?:key|main)\s+points)\b",
    re.IGNORECASE,
)
_FA_REQUEST = re.compile(
    r"(?:کن|کنید|بکن|بکنید|بده|بدهید|بدید|برگردان|برگردانید|بنویس|بنویسید|بگو|بگویید)"
    r"[\s.!؟?…]*$"
    r"|^(?:لطفا|لطفاً|حالا|بعد|و)?\s*(?:ترجمه|خلاصه|چکیده)(?:\s|\u200c|$)"
)
_COLONS = ":："
# An apostrophe between letters (it's, don't) does not end a single-quoted span.
_SINGLE_QUOTE = re.compile(r"(?<!\w)'((?:[^'\n]|\b'\b)*?\w(?:[^'\n]|\b'\b)*?)'(?!\w)")
_QUOTE_PATTERNS = (
    re.compile(r"«([^«»]*?\w[^«»]*?)»", re.DOTALL),
    re.compile(r"“([^“”]*?\w[^“”]*?)”", re.DOTALL),
    re.compile(r'"([^"]*?\w[^"]*?)"', re.DOTALL),
    _SINGLE_QUOTE,
)


def _key(text: str) -> str:
    return normalize_persian(text).lower()


def _has_cue(text: str) -> bool:
    return _CUE.search(_key(text)) is not None


def _word_count(text: str) -> int:
    return len(text.split())


def _is_request_line(line: str) -> bool:
    """Short, cue-bearing, and phrased as a request (imperative or request opener)."""
    stripped = line.strip().strip("*#>-•").strip()
    if not stripped or _word_count(stripped) > MAX_INSTRUCTION_WORDS or not _has_cue(stripped):
        return False
    key = _key(stripped).rstrip(":：")
    return bool(_EN_REQUEST.search(key) or _FA_REQUEST.search(key))


# --- rules -------------------------------------------------------------------------------


def _quoted(text: str) -> str | None:
    """Exactly one top-level quoted span, and everything else is a short instruction."""
    spans: list[tuple[int, int, str]] = []
    for pattern in _QUOTE_PATTERNS:
        spans.extend((m.start(), m.end(), m.group(1)) for m in pattern.finditer(text))
    top = [
        s
        for s in spans
        if not any(o is not s and o[0] <= s[0] and s[1] <= o[1] for o in spans)  # drop nested
    ]
    if len(top) != 1:
        return None
    start, end, inner = top[0]
    rest = f"{text[:start]} {text[end:]}".strip()
    if rest and (_word_count(rest) > MAX_INSTRUCTION_WORDS or not _has_cue(rest)):
        return None
    content = inner.strip()
    return content or None


def _instruction_colon(text: str) -> int | None:
    """Index of the first colon that can end an instruction.

    Colons between digits (`10:30`) and URL schemes (`https://`) never do, so "Summarize
    the 10:30 meeting: …" still splits at the right place.
    """
    for i, ch in enumerate(text):
        if ch not in _COLONS:
            continue
        before = text[i - 1] if i > 0 else ""
        after = text[i + 1 : i + 3]
        if before.isdigit() and after[:1].isdigit():
            continue
        if after.startswith("//"):
            continue
        return i
    return None


def _after_colon(text: str) -> str | None:
    i = _instruction_colon(text)
    if i is None:
        return None
    prefix, content = text[:i], text[i + 1 :].strip()
    if _word_count(prefix) > MAX_INSTRUCTION_WORDS or not _has_cue(prefix) or not content:
        return None
    return content


def _after_newline(text: str) -> str | None:
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return None
    if _is_request_line(lines[0]) and (content := "\n".join(lines[1:]).strip()):
        return content
    if _is_request_line(lines[-1]) and (content := "\n".join(lines[:-1]).strip()):
        return content
    return None


def extract_payload(inp: SkillInput) -> Payload:
    """Find the content a summarize/translate request operates on. Never raises."""
    if inp.is_chained:
        return Payload(text=inp.text.strip(), method="chained", uncertain=False)
    text = inp.text.strip()
    if (content := _quoted(text)) is not None:
        return Payload(text=content, method="quoted", uncertain=False)
    if (content := _after_colon(text)) is not None:
        return Payload(text=content, method="after_colon", uncertain=False)
    if (content := _after_newline(text)) is not None:
        return Payload(text=content, method="after_newline", uncertain=False)
    return Payload(text=text, method="whole", uncertain=True)


def is_cue_only(text: str) -> bool:
    """True when the text is only a request with no content ("Translate this:", «خلاصه کن»).

    Skills reject these instead of translating the instruction itself. The router's G1
    guard normally asks for the text first; this is the skill-side safety net.
    """
    stripped = text.strip()
    if "\n" in stripped:
        return False
    i = _instruction_colon(stripped)
    if i is not None:
        if stripped[i + 1 :].strip():
            return False
        stripped = stripped[:i]
    words = re.findall(r"[\w;\u200c]+", _key(stripped))
    return all(_CUE.fullmatch(w) or w in _FILLER for w in words)


# Words that can surround a cue without being content: "translate this into Persian
# please", «لطفاً این متن را به انگلیسی ترجمه کن».
_FILLER = frozenset(
    [
        "please",
        "pls",
        "can",
        "could",
        "would",
        "you",
        "me",
        "for",
        "it",
        "this",
        "that",
        "the",
        "text",
        "above",
        "below",
        "following",
        "now",
        "and",
        "then",
        "a",
        "an",
        "to",
        "into",
        "in",
        "of",
        "give",
        "write",
        "make",
        "short",
        "summary",
        "translation",
        "tl;dr",
        "tldr",
        "لطفا",
        "لطفاً",
        "این",
        "اینو",
        "اینرو",
        "آن",
        "متن",
        "را",
        "رو",
        "به",
        "زبان",
        "برای",
        "من",
        "کن",
        "کنید",
        "بکن",
        "بده",
        "بدهید",
        "برگردان",
        "خلاصه\u200cاش",
        "ترجمه\u200cاش",
        "ترجمش",
        "خلاصش",
        "و",
        "بعد",
    ]
    + _LANGS_EN.split("|")
    + _LANGS_FA.split("|")
)
