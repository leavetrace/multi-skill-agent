"""Deterministic routes that need no LLM call (ARCHITECTURE §4.2).

A cost optimization, not a second router: only inputs whose route is certain are handled.
"Pure expression" is WP2's definition (ADR-022), so the router and the calculator's own
direct path can never disagree about what counts as arithmetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from skillagent.core.registry import SkillRegistry
from skillagent.core.types import RoutingDecision, UserRequest
from skillagent.skills.calculator.normalize import looks_like_expression, strip_cues

__all__ = ["CALCULATOR_SKILL", "EMPTY_QUESTION", "FastPathResult", "try_route"]

CALCULATOR_SKILL = "calculator"

EMPTY_QUESTION = (
    "Your message is empty. What would you like me to do? "
    "/ پیام شما خالی است. چه کاری برایتان انجام دهم؟"
)

# Persian letters or Persian/Arabic-Indic digits mean the user writes Persian.
_PERSIAN_SIGNAL = re.compile(r"[؀-ۿ]")


@dataclass(frozen=True)
class FastPathResult:
    decision: RoutingDecision
    rule: str  # "empty" | "pure_expression"


def try_route(request: UserRequest, registry: SkillRegistry) -> FastPathResult | None:
    """A rule-based decision, or None to let the LLM decide."""
    text = request.normalized_text
    if not text.strip():
        decision = RoutingDecision(
            response_language="en",
            needs_clarification=True,
            clarification_question=EMPTY_QUESTION,
            confidence=1.0,
            rationale="fast path: empty input",
            route_source="rule",
        )
        return FastPathResult(decision, "empty")
    if CALCULATOR_SKILL in registry:
        stripped = strip_cues(text)
        if stripped and looks_like_expression(stripped):
            lang = "fa" if _PERSIAN_SIGNAL.search(text) else "en"
            decision = RoutingDecision.model_validate(
                {
                    "response_language": lang,
                    "steps": [
                        {
                            "id": "s1",
                            "skill": CALCULATOR_SKILL,
                            "instruction": "Evaluate the arithmetic expression.",
                            "input_from": "user",
                        }
                    ],
                    "confidence": 1.0,
                    "rationale": "fast path: pure arithmetic expression",
                    "route_source": "rule",
                },
                context={"registry": registry},
            )
            return FastPathResult(decision, "pure_expression")
    return None
