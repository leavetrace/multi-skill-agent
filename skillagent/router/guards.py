"""Deterministic post-checks on a validated LLM decision (WP4 §4.4).

Each guard fixes one failure mode small models show and code can detect exactly. They
are deliberately few; new guards need evidence from eval, not intuition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from skillagent.core.language import normalize_persian
from skillagent.core.registry import SkillRegistry
from skillagent.core.types import LangHint, RoutingDecision, UserRequest
from skillagent.router.preprocess import is_unambiguous_english, strip_quoted, word_count

__all__ = ["MISSING_PAYLOAD_QUESTION", "GuardFiring", "apply_guards"]

G1_MAX_WORDS = 4

MISSING_PAYLOAD_QUESTION = {
    "en": (
        "I couldn't find the text you want me to work on. Please send your request again "
        "together with the text."
    ),
    "fa": (
        "متنی که باید روی آن کار کنم را پیدا نکردم. لطفاً درخواستتان را همراه با متن دوباره بفرستید."
    ),
}

# Words that point at content instead of containing it. Skill-agnostic on purpose: the
# skill side of G1 comes from `SkillSpec.requires_payload`.
_DEICTIC = re.compile(
    r"\b(?:this|that|it|these|those|the\s+text|following|below|above)\b"
    r"|(?:^|\s)(?:این|اینو|اینا|اینها|اون|اونو|آن|آنرا|متن|زیر)(?=\s|$|[.,!?؟،])",
    re.IGNORECASE,
)


# "Please answer in Persian", «به انگلیسی جواب بده»: the user names the reply language, which
# the prompt says overrides the instruction language, so G2 must not undo it.
_REPLY_LANGUAGE_REQUEST = re.compile(
    r"\b(?:answer|reply|respond|response)\w*\s+(?:me\s+|to\s+me\s+)?in\s+[A-Za-z]+"
    r"|به\s+\S+\s+(?:جواب|پاسخ)",
    re.IGNORECASE,
)

# «ترجمه کن», «خلاصه کنید»: a noun plus a light verb and nothing else.
_BARE_PERSIAN_VERB = re.compile(r"\S+\s+(?:کن|کنید|بکن|بکنید|بده|بدید)")


@dataclass
class GuardFiring:
    guard: str  # "G1_missing_payload" | "G2_language"
    detail: dict[str, Any] = field(default_factory=dict)


def apply_guards(
    decision: RoutingDecision,
    request: UserRequest,
    registry: SkillRegistry,
    lead_hint: LangHint,
) -> tuple[RoutingDecision, list[GuardFiring]]:
    """Run G2 (language) then G1 (missing payload), so G1's question uses the fixed language."""
    firings: list[GuardFiring] = []
    decision = _g2_language(decision, request, lead_hint, firings)
    decision = _g1_missing_payload(decision, request, registry, firings)
    return decision, firings


def _g1_missing_payload(
    decision: RoutingDecision,
    request: UserRequest,
    registry: SkillRegistry,
    firings: list[GuardFiring],
) -> RoutingDecision:
    """ "translate this" with nothing to translate: the model sometimes runs the skill anyway."""
    if decision.needs_clarification or not _lacks_payload(request.normalized_text):
        return decision
    payload_steps = [
        s.skill
        for s in decision.steps
        if s.input_from == "user" and s.skill in registry and registry.get(s.skill).requires_payload
    ]
    if not payload_steps:
        return decision
    lang = "fa" if decision.response_language == "fa" else "en"
    firings.append(GuardFiring("G1_missing_payload", {"skills": payload_steps}))
    return RoutingDecision(
        response_language=decision.response_language,
        needs_clarification=True,
        clarification_question=MISSING_PAYLOAD_QUESTION[lang],
        confidence=decision.confidence,
        rationale=f"G1: {'/'.join(payload_steps)} requested without content",
        route_source=decision.route_source,
    )


def _lacks_payload(text: str) -> bool:
    """≤ 4 words that point at absent content ("translate this"), a bare verb
    ("Summarize", «ترجمه کن»), or an instruction ending at a colon with nothing after it."""
    text = normalize_persian(text).strip()
    if word_count(text) > G1_MAX_WORDS:
        return False
    stripped = text.rstrip(" .!?؟")
    if stripped.endswith((":", "：")):
        return True
    unquoted = strip_quoted(stripped)
    if unquoted.strip() != stripped:  # something quoted: that is the content
        return False
    return (
        bool(_DEICTIC.search(stripped))
        or word_count(stripped) == 1
        or bool(_BARE_PERSIAN_VERB.fullmatch(stripped))
    )


def _g2_language(
    decision: RoutingDecision,
    request: UserRequest,
    lead_hint: LangHint,
    firings: list[GuardFiring],
) -> RoutingDecision:
    """The model sometimes answers in the *content* language; the instruction language wins.

    fa → en is only forced when the instruction is clearly English, because Finglish
    ("salam chetori") is Latin-script Persian and must stay `fa`. Clarifications are left
    alone: their question text is already written in the model's chosen language. An
    explicit reply-language request ("answer in Persian") also wins over the instruction
    language (prompt rule 7), so the model's choice is kept then.
    """
    if decision.needs_clarification:
        return decision
    if _REPLY_LANGUAGE_REQUEST.search(normalize_persian(request.raw_text)):
        return decision
    current = decision.response_language
    target: str | None = None
    if lead_hint == "fa" and current == "en":
        target = "fa"
    elif lead_hint == "en" and current == "fa" and is_unambiguous_english(request.raw_text):
        target = "en"
    if target is None:
        return decision
    firings.append(GuardFiring("G2_language", {"from": current, "to": target}))
    return decision.model_copy(update={"response_language": target})
