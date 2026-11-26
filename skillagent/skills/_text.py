"""Shared plumbing for the three LLM text skills (summarizer, translator, general_chat).

Everything here is deterministic: prompt-header stripping, delimiter escaping, the output
clean-up that small models need (preambles, wrapping quotes, Arabic letters, digits), and
the localized notes. Keeping it in one place means the three skills clean output the same
way, and each clean-up rule reports whether it fired so eval can count them.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from skillagent.core.errors import LLMProviderError
from skillagent.core.language import normalize_persian, strip_think, to_persian_digits
from skillagent.llm.types import ChatMessage, LLMResponse
from skillagent.prompts import PromptTemplate

__all__ = [
    "UiLang",
    "build_messages",
    "escape_delimiters",
    "language_name",
    "localized",
    "localized_language_name",
    "payload_message",
    "persianize_digits",
    "postprocess",
    "prompt_meta",
    "require_text",
    "system_prompt",
    "truncation_note",
    "ui_lang",
    "was_truncated",
]

UiLang = Literal["fa", "en"]

_NAMES_EN = {
    "en": "English", "fa": "Persian (Farsi)", "ar": "Arabic", "de": "German",
    "fr": "French", "es": "Spanish", "it": "Italian", "tr": "Turkish", "ru": "Russian",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "pt": "Portuguese", "nl": "Dutch",
    "hi": "Hindi", "ur": "Urdu", "he": "Hebrew", "el": "Greek", "pl": "Polish",
    "sv": "Swedish", "uk": "Ukrainian", "az": "Azerbaijani", "ku": "Kurdish", "ps": "Pashto",
}  # fmt: skip
_NAMES_FA = {
    "en": "انگلیسی", "fa": "فارسی", "ar": "عربی", "de": "آلمانی", "fr": "فرانسوی",
    "es": "اسپانیایی", "it": "ایتالیایی", "tr": "ترکی", "ru": "روسی", "zh": "چینی",
    "ja": "ژاپنی", "ko": "کره‌ای", "pt": "پرتغالی", "nl": "هلندی", "hi": "هندی",
    "ur": "اردو", "he": "عبری", "el": "یونانی", "pl": "لهستانی", "sv": "سوئدی",
    "uk": "اوکراینی", "az": "ترکی آذربایجانی", "ku": "کردی", "ps": "پشتو",
}  # fmt: skip


def ui_lang(code: str) -> UiLang:
    """Language for our own fixed messages: Persian for `fa`, English for everything else."""
    return "fa" if code == "fa" else "en"


def language_name(code: str) -> str:
    """English name for prompts; models follow "Persian (Farsi)" better than "fa"."""
    return _NAMES_EN.get(code, f"the language with ISO 639-1 code '{code}'")


def localized_language_name(code: str, lang: UiLang) -> str:
    if lang == "fa":
        return _NAMES_FA.get(code, code)
    return _NAMES_EN.get(code, code).removesuffix(" (Farsi)")


# --- prompt assembly ---------------------------------------------------------------------

_HEADER_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)


def system_prompt(template: PromptTemplate, **variables: str) -> str:
    """Render and drop the leading `<!-- … -->` design note.

    The note documents the prompt for reviewers (and the README); sending it would only
    cost tokens and could leak design wording into answers.
    """
    return _HEADER_COMMENT.sub("", template.render(**variables), count=1)


_OUR_TAGS = re.compile(r"<(/?)\s*(text|task|message)\s*>", re.IGNORECASE)


def escape_delimiters(text: str) -> tuple[str, bool]:
    """Neutralize our own tags inside user data so it cannot close `<text>` early.

    `</text>` becomes `‹/text›`: visually the same for the model, but no longer a tag.
    """
    escaped = _OUR_TAGS.sub(lambda m: f"‹{m.group(1)}{m.group(2)}›", text)
    return escaped, escaped != text


def build_messages(system: str, user: str) -> list[ChatMessage]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def payload_message(instruction: str, content: str, note: str | None) -> tuple[str, bool]:
    """User message for the payload skills: restated instruction, optional note, `<text>`.

    The content always sits last and inside `<text>`, so the system prompt can point at
    one unambiguous block and call it data.
    """
    instruction, esc_a = escape_delimiters(instruction)
    content, esc_b = escape_delimiters(content)
    parts = [f"<instruction>{instruction}</instruction>"]
    if note:
        parts.append(note)
    parts.append(f"<text>\n{content}\n</text>")
    return "\n".join(parts), esc_a or esc_b


def require_text(response: LLMResponse, skill: str) -> str:
    """An empty reply is a provider-side failure, not a valid translation or summary."""
    if not response.text.strip():
        raise LLMProviderError(f"{skill}: the model returned an empty reply")
    return response.text


def prompt_meta(template: PromptTemplate) -> dict[str, Any]:
    return {"prompt_version": template.version, "prompt_sha": template.sha}


# --- output clean-up ---------------------------------------------------------------------

_LANG_WORDS = r"(?:english|persian|farsi|french|german|spanish|arabic|turkish|russian)"
_EN_PREAMBLE = re.compile(
    r"\A\s*(?:(?:sure|okay|ok|certainly|of course|absolutely)[,!.]?\s+)?"
    r"(?:here(?:'s|’s| is| are)\s+)?(?:the\s+|your\s+|a\s+|an\s+)?"
    r"(?:(?:brief|short|concise|full|faithful)\s+)?(?:" + _LANG_WORDS + r"\s+)?"
    r"(?:translation|translated\s+text|summary|summarized\s+(?:text|version))"
    # Only label-like tails ("of the text", "in Persian", "(Persian)"), so content such as
    # "The summary of the meeting was short: …" is never cut.
    r"(?:\s+(?:of|for)\s+(?:the|this|your)(?:\s+(?:above|given|provided))?"
    r"(?:\s+(?:text|article|passage|paragraph|message|sentence|report))?)?"
    r"(?:\s+(?:in|into|to)\s+" + _LANG_WORDS + r")?(?:\s*\([^)\n]{1,20}\))?\s*[:：]\s*",
    re.IGNORECASE,
)
_FA_PREAMBLE = re.compile(
    r"\A\s*(?:(?:حتماً|حتما|بله|البته|بفرمایید)[،,!.]?\s+)?(?:این\s+)?(?:هم\s+)?(?:متن\s+)?"
    r"(?:ترجمه(?:‌شده|ٔ|‌ی|ی)?|خلاصه(?:‌شده|ٔ|‌ی|ی)?)"
    r"(?:\s+(?:متن|مطلب|جمله|به|زبان|فارسی|انگلیسی|شده))*\s*[:：]\s*"
)
_SOURCE_LABEL = re.compile(
    r"\A\s*(?:translation|translated|summary|tl;?\s?dr|ترجمه|خلاصه)", re.IGNORECASE
)
_WRAPPERS = (("«", "»"), ("“", "”"), ('"', '"'), ("'", "'"))
_FENCE = re.compile(r"\A```[\w-]*[ \t]*\n(.*?)\n?```\Z", re.DOTALL)


def _strip_preamble(text: str, source: str) -> str:
    if _SOURCE_LABEL.match(source):  # the content itself starts with "Summary:" etc.
        return text
    for pattern in (_EN_PREAMBLE, _FA_PREAMBLE):
        stripped = pattern.sub("", text, count=1)
        if stripped != text and stripped.strip():
            return stripped
    return text


def _strip_wrapper(text: str, source: str) -> str:
    src = source.strip()
    if (m := _FENCE.match(text)) and "```" not in src:
        return m.group(1).strip()
    for left, right in _WRAPPERS:
        inner = text[len(left) : -len(right)]
        if (
            len(text) > 2
            and text.startswith(left)
            and text.endswith(right)
            and left not in inner
            and right not in inner
            and not (src.startswith(left) and src.endswith(right))
        ):
            return inner.strip()
    return text


_PROTECTED = re.compile(
    r"```.*?```"  # fenced code
    r"|`[^`\n]*`"  # inline code
    r"|(?:https?://|www\.)\S+"  # URLs
    r"|\S+@\S+\.\S+"  # e-mail addresses
    r"|^[ \t]*\d+[.)](?=\s)"  # markdown list numbers must stay ASCII to render as a list
    r"|\S*[A-Za-z]\S*",  # identifiers and Latin tokens: v2, COVID-19, A4, H2O
    re.DOTALL | re.MULTILINE,
)
_COMMA_BETWEEN_DIGITS = re.compile(r"(?<=\d),(?=\d{3}\b)")


def persianize_digits(text: str) -> str:
    """ASCII digits in Persian prose → Persian digits; code, URLs and identifiers keep ASCII.

    Done in code rather than trusted to the prompt: small models mix digit systems.
    """
    out: list[str] = []
    pos = 0
    for m in _PROTECTED.finditer(text):
        out.append(_persian_prose_digits(text[pos : m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_persian_prose_digits(text[pos:]))
    return "".join(out)


def _persian_prose_digits(segment: str) -> str:
    return to_persian_digits(_COMMA_BETWEEN_DIGITS.sub("٬", segment))


def postprocess(
    text: str, lang: str, *, source: str = "", strip_labels: bool = True
) -> tuple[str, dict[str, bool]]:
    """Deterministic clean-up of a model reply. Returns the text and which rules fired.

    `source` is the content the model worked on: a rule never removes something the
    source itself had (a text that starts with "Summary:" keeps it in translation).
    """
    flags: dict[str, bool] = {}
    cleaned = strip_think(text)
    flags["think_stripped"] = cleaned != text.strip()
    if strip_labels:
        before = cleaned
        cleaned = _strip_preamble(cleaned, source).strip()
        flags["preamble_removed"] = cleaned != before
        before = cleaned
        cleaned = _strip_wrapper(cleaned, source)
        flags["wrapper_removed"] = cleaned != before
    if lang == "fa":
        before = cleaned
        cleaned = normalize_persian(cleaned)
        flags["persian_normalized"] = cleaned != before
        before = cleaned
        cleaned = persianize_digits(cleaned)
        flags["persian_digits"] = cleaned != before
    return cleaned, flags


_TRUNCATED = {
    "en": "[Note: the output was cut off at the length limit and may be incomplete.]",
    "fa": "[توجه: خروجی به سقف طول رسید و قطع شد؛ ممکن است کامل نباشد.]",
}


def localized(template: str, lang: UiLang, **values: object) -> str:
    """Fill one of our fixed messages; Persian messages show Persian digits."""
    text = template.format(**values)
    return persianize_digits(text) if lang == "fa" else text


def truncation_note(lang: UiLang) -> str:
    return _TRUNCATED[lang]


def was_truncated(response: LLMResponse) -> bool:
    return response.finish_reason == "length"
