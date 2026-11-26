"""Deterministic preprocessing for the router (CONTRACTS §11): no LLM calls here.

The whole-text language hint describes the *content*; a prompt like
«این متن رو summarize کن: <English paragraph>» reads as `en` even though the user writes
in Persian (ADR-021). `leading_segment_hint` looks only at the instruction part, which is
what decides the reply language.
"""

from __future__ import annotations

import re

from skillagent.core.language import (
    ZWNJ,
    detect_lang_hint,
    estimate_tokens,
    normalize_persian,
)
from skillagent.core.types import LangHint, UserRequest

__all__ = [
    "build_user_request",
    "instruction_segment",
    "is_unambiguous_english",
    "leading_segment_hint",
    "strip_quoted",
    "word_count",
]

_PREFIX_MAX_WORDS = 15
_HEAD_WORDS = 12
_TRAILING_CUE_MAX_WORDS = 15

_SEGMENT_END = re.compile(r"[:：\n]")
# Quoted spans are content even inside the instruction: "Translate «سلام» to English".
_QUOTED = re.compile(r"«[^»]*»|“[^”]*”|\"[^\"]*\"|'[^'\n]*'|`[^`]*`")
_WORD = re.compile(rf"[^\s{ZWNJ}]+")

# Words that are common in English instructions but not in Finglish. Finglish shares many
# short Latin tokens with English ("in" = this, "to" = you/in, "man" = I, "be" = to), so
# those are deliberately absent: a Finglish prompt must never look "clearly English".
_ENGLISH_MARKER_TEXT = (
    "the a an is are was this that these those please what what's how can could would "
    "you your me my it its and of for with from into translate summarize summarise "
    "calculate compute explain tell give write text following below above which who why "
    "when where should i"
)
_ENGLISH_MARKERS = frozenset(_ENGLISH_MARKER_TEXT.split())


def build_user_request(raw_text: str) -> UserRequest:
    """Strip, normalize Persian letters, and attach the script hint and token estimate."""
    text = raw_text.strip()
    normalized = normalize_persian(text)
    return UserRequest(
        raw_text=text,
        normalized_text=normalized,
        lang_hint=detect_lang_hint(normalized),
        approx_tokens=estimate_tokens(text),
    )


def strip_quoted(text: str) -> str:
    """Replace quoted spans with a space: quoted words are content, not instruction."""
    return _QUOTED.sub(" ", text)


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


def instruction_segment(raw_text: str) -> str:
    """Best guess at the instruction part of a prompt (deterministic, may be imperfect).

    1. The text before the first `:`/newline, if that prefix is short (≤ 15 words).
    2. Otherwise a short last line ("trailing cue": `<paragraph>\\n\\nخلاصه‌اش کن`).
    3. Otherwise the first 12 words.
    """
    text = normalize_persian(raw_text).strip()
    if not text:
        return ""
    match = _SEGMENT_END.search(text)
    if match:
        prefix = text[: match.start()].strip()
        if prefix and word_count(prefix) <= _PREFIX_MAX_WORDS and _has_letters(prefix):
            return prefix
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        last = lines[-1]
        if word_count(last) <= _TRAILING_CUE_MAX_WORDS and _has_letters(last):
            return last
    return " ".join(_WORD.findall(text)[:_HEAD_WORDS])


def leading_segment_hint(raw_text: str) -> LangHint:
    """Language of the instruction part, ignoring quoted spans.

    When the segment is script-mixed («این متن رو summarize کن»), the majority of *words*
    decides: Persian speakers routinely code-switch English verbs into Persian sentences,
    so a letter ratio would under-count the Persian frame.
    """
    segment = instruction_segment(raw_text)
    unquoted = strip_quoted(segment)
    if _has_letters(unquoted):
        segment = unquoted
    hint = detect_lang_hint(segment)
    if hint != "mixed":
        return hint
    persian = latin = 0
    for word in _WORD.findall(segment):
        word_hint = detect_lang_hint(word)
        persian += word_hint == "fa"
        latin += word_hint == "en"
    if persian > latin:
        return "fa"
    if latin > persian:
        return "en"
    return "mixed"


def is_unambiguous_english(raw_text: str) -> bool:
    """True when the instruction is clearly English, not Finglish ("salam chetori").

    Script alone cannot tell the two apart, so we require at least two English marker words
    making up ≥ 30% of the instruction. Used only to decide whether a code override of the
    model's `response_language` (fa → en) is safe.
    """
    segment = strip_quoted(instruction_segment(raw_text))
    if detect_lang_hint(segment) != "en":
        return False
    words = [w.strip(".,!?;:()[]").lower() for w in _WORD.findall(segment)]
    words = [w for w in words if w]
    if not words:
        return False
    hits = sum(w in _ENGLISH_MARKERS for w in words)
    return hits >= 2 and hits / len(words) >= 0.3


def _has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)
