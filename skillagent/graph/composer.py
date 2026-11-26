"""Deterministic EN/FA response assembly (ADR-003): no LLM call, no paraphrasing.

A synthesizing LLM could reword an exact translation or a calculator result; plain
assembly cannot. Every user-visible string the graph itself writes (limit message,
clarification footer, failure notes, dropped-task notice, apology) lives here, so the
Persian wording is reviewed in one place (ی/ک, ZWNJ, «،»).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from skillagent.core.language import to_persian_digits
from skillagent.core.types import PlanStep, RoutingDecision, SkillResult

__all__ = [
    "APOLOGY",
    "UiLang",
    "clarify_message",
    "compose",
    "limit_message",
    "skill_label",
    "ui_lang",
]

UiLang = Literal["en", "fa"]

APOLOGY = (
    "Sorry, I couldn't complete your request this time. Please try again in a moment.\n"
    "متأسفم، این بار نتوانستم درخواست شما را انجام دهم. لطفاً کمی بعد دوباره امتحان کنید."
)
"""Static and bilingual: used when even the response language may be unknown."""

# Keyed by skill name; unknown (e.g. synthetic) skills fall back to their name.
_LABELS: dict[str, dict[UiLang, str]] = {
    "summarizer": {"en": "Summary", "fa": "خلاصه"},
    "translator": {"en": "Translation", "fa": "ترجمه"},
    "calculator": {"en": "Calculation", "fa": "محاسبه"},
    "general_chat": {"en": "Answer", "fa": "پاسخ"},
}

_NOTES: dict[str, dict[UiLang, str]] = {
    "error": {
        "en": "The {label} step ran into an error, so it has no result.",
        "fa": "مرحلهٔ «{label}» با خطا روبه‌رو شد و نتیجه‌ای ندارد.",
    },
    "timeout": {
        "en": "The {label} step took too long and was stopped.",
        "fa": "مرحلهٔ «{label}» بیش از حد طول کشید و متوقف شد.",
    },
    "dependency": {
        "en": "The {label} step was skipped because the step it depends on did not succeed.",
        "fa": "مرحلهٔ «{label}» انجام نشد، چون مرحله‌ای که به آن وابسته بود موفق نبود.",
    },
    "limit": {
        "en": "The {label} step was skipped because the request reached its time or step limit.",
        "fa": "مرحلهٔ «{label}» به‌دلیل رسیدن درخواست به سقف زمان یا تعداد مراحل انجام نشد.",
    },
}

_DROPPED: dict[UiLang, str] = {
    "en": "Note: I handle up to {n} tasks per request, so I skipped: {items}.",
    "fa": "توجه: من در هر درخواست حداکثر {n} کار را انجام می‌دهم؛ این موارد انجام نشد: {items}.",
}
_ITEM_SEP: dict[UiLang, str] = {"en": "; ", "fa": "، "}

_CLARIFY_FOOTER: dict[UiLang, str] = {
    "en": "Please send your full request again with the missing detail "
    "(I don't remember earlier messages).",
    "fa": "لطفاً درخواست کامل خود را همراه با جزئیات لازم دوباره بفرستید "
    "(من پیام‌های قبلی را به خاطر نمی‌سپارم).",
}

_LIMIT: dict[UiLang, str] = {
    "en": "Your message is too long for me to process (about {tokens} tokens; the limit is "
    "{limit}). Please shorten it or send it in smaller parts.",
    "fa": "پیام شما برای پردازش بیش از حد طولانی است (حدود {tokens} توکن؛ سقف {limit} توکن "
    "است). لطفاً آن را کوتاه‌تر کنید یا در چند بخش بفرستید.",
}

_SHOWN = ("ok", "rejected")


def ui_lang(code: str | None) -> UiLang:
    """Persian when the response language is `fa`, English for everything else."""
    return "fa" if code == "fa" else "en"


def _num(value: int, lang: UiLang) -> str:
    return to_persian_digits(str(value)) if lang == "fa" else str(value)


def skill_label(skill: str, lang: UiLang) -> str:
    return _LABELS.get(skill, {}).get(lang, skill)


def limit_message(lang: UiLang, *, tokens: int, limit: int) -> str:
    return _LIMIT[lang].format(tokens=_num(tokens, lang), limit=_num(limit, lang))


def clarify_message(lang: UiLang, question: str) -> str:
    """The router's question plus a request to resend everything (A6: no memory)."""
    return f"{question.strip()}\n\n{_CLARIFY_FOOTER[lang]}"


def _note(step: PlanStep, result: SkillResult | None, lang: UiLang) -> str:
    label = skill_label(step.skill, lang)
    label = label if lang == "fa" else label.lower()
    if result is None or result.status == "skipped":
        reason = (result.meta.get("reason") if result else None) or "limit"
        key = "dependency" if reason == "dependency" else "limit"
    else:
        key = "timeout" if result.status == "timeout" else "error"
    return _NOTES[key][lang].format(label=label)


def _block(
    step: PlanStep,
    steps: Mapping[str, PlanStep],
    results: Mapping[str, SkillResult],
    lang: UiLang,
) -> tuple[str, bool]:
    """Text for one terminal step, and whether it carries a real (user-facing) output.

    A failed terminal step is explained by its root cause: walking up the chain, the first
    step that did not end `ok`. If that root was `rejected`, its message is already
    user-facing ("this text is too short to summarize") and is shown instead of notes.
    """
    result = results.get(step.id)
    if result is not None and result.status in _SHOWN:
        return result.output, True
    chain = [step]
    while chain[-1].input_from in steps:
        chain.append(steps[chain[-1].input_from])
    root = next(s for s in reversed(chain) if _status(results, s) != "ok")
    root_result = results.get(root.id)
    if root_result is not None and root_result.status == "rejected":
        return root_result.output, True
    notes = [_note(root, root_result, lang)]
    if root is not step:
        notes.append(_note(step, result, lang))
    return "\n".join(notes), False


def _status(results: Mapping[str, SkillResult], step: PlanStep) -> str:
    result = results.get(step.id)
    return result.status if result is not None else "skipped"


def _section_labels(terminal: list[PlanStep], lang: UiLang) -> list[str]:
    labels = [skill_label(s.skill, lang) for s in terminal]
    totals = {label: labels.count(label) for label in labels}
    seen: dict[str, int] = {}
    numbered = []
    for label in labels:
        if totals[label] == 1:
            numbered.append(label)
            continue
        seen[label] = seen.get(label, 0) + 1
        numbered.append(f"{label} ({_num(seen[label], lang)})")
    return numbered


def compose(
    decision: RoutingDecision, results: Mapping[str, SkillResult], *, max_skills: int
) -> str:
    """Final answer in `decision.response_language`.

    Terminal steps (no other step consumes them) are what the user asked to see: one
    terminal step (a single skill or a chain) is shown bare; several (parallel) get one
    labelled section each, in plan order. Intermediate chain outputs stay in the trace.
    """
    lang = ui_lang(decision.response_language)
    steps = {s.id: s for s in decision.steps}
    consumed = {s.input_from for s in decision.steps}
    terminal = [s for s in decision.steps if s.id not in consumed]
    blocks = [_block(s, steps, results, lang) for s in terminal]

    if not any(shown for _, shown in blocks):
        body = "\n\n".join([APOLOGY, *(text for text, _ in blocks)])
    elif len(blocks) == 1:
        body = blocks[0][0]
    else:
        labels = _section_labels(terminal, lang)
        body = "\n\n".join(
            f"**{label}**\n{text}" for label, (text, _) in zip(labels, blocks, strict=True)
        )

    if decision.dropped_intents:
        items = _ITEM_SEP[lang].join(i.strip() for i in decision.dropped_intents)
        body += "\n\n" + _DROPPED[lang].format(n=_num(max_skills, lang), items=items)
    return body
