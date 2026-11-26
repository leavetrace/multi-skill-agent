from __future__ import annotations

from collections.abc import Callable

import pytest

from skillagent.core.registry import SkillRegistry
from skillagent.core.types import RoutingDecision
from skillagent.router import Router, build_user_request, leading_segment_hint
from skillagent.router.guards import MISSING_PAYLOAD_QUESTION, apply_guards
from skillagent.testing import FakeLLM


def _decision(registry: SkillRegistry, lang: str, *skills: str) -> RoutingDecision:
    return RoutingDecision.model_validate(
        {
            "response_language": lang,
            "steps": [
                {"id": f"s{i}", "skill": s, "instruction": "do it", "input_from": "user"}
                for i, s in enumerate(skills, 1)
            ],
        },
        context={"registry": registry},
    )


def _guard(registry: SkillRegistry, text: str, decision: RoutingDecision):
    request = build_user_request(text)
    return apply_guards(decision, request, registry, leading_segment_hint(text))


# --- G1 missing payload ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "lang", "skill"),
    [
        ("Translate this", "en", "translator"),
        ("summarize it", "en", "summarizer"),
        ("Summarize", "en", "summarizer"),
        ("Translate to French:", "en", "translator"),
        ("اینو ترجمه کن", "fa", "translator"),
        ("ترجمه کن", "fa", "translator"),
        ("اینا رو خلاصه کن", "fa", "summarizer"),
    ],
)
def test_g1_converts_payload_skill_without_content(
    registry: SkillRegistry, text: str, lang: str, skill: str
) -> None:
    decision, firings = _guard(registry, text, _decision(registry, lang, skill))
    assert [f.guard for f in firings] == ["G1_missing_payload"]
    assert decision.needs_clarification and decision.steps == []
    assert decision.clarification_question == MISSING_PAYLOAD_QUESTION[lang]


@pytest.mark.parametrize(
    ("text", "skill"),
    [
        ("Translate hello to French", "translator"),  # the payload is "hello"
        ("Translate «it» to French", "translator"),  # deictic word is quoted content
        ("Hi there", "general_chat"),  # not a payload skill
        ("Summarize this: The meeting moved to Monday and the budget was approved.", "summarizer"),
    ],
)
def test_g1_leaves_valid_requests_alone(registry: SkillRegistry, text: str, skill: str) -> None:
    original = _decision(registry, "en", skill)
    decision, firings = _guard(registry, text, original)
    assert firings == [] and decision == original


def test_g1_ignores_chained_payload_steps(registry: SkillRegistry) -> None:
    chained = RoutingDecision.model_validate(
        {
            "response_language": "en",
            "steps": [
                {"id": "s1", "skill": "calculator", "instruction": "x", "input_from": "user"},
                {"id": "s2", "skill": "translator", "instruction": "y", "input_from": "s1"},
            ],
        },
        context={"registry": registry},
    )
    _, firings = _guard(registry, "calculate this, translate it", chained)
    assert firings == []


# --- G2 language ---------------------------------------------------------------------------


def test_g2_forces_persian_instruction_language(registry: SkillRegistry) -> None:
    text = "این متن رو summarize کن: Cloud computing lets companies rent servers on demand."
    decision, firings = _guard(registry, text, _decision(registry, "en", "summarizer"))
    assert decision.response_language == "fa"
    assert firings[0].guard == "G2_language"
    assert firings[0].detail == {"from": "en", "to": "fa"}


def test_g2_forces_english_only_when_unambiguous(registry: SkillRegistry) -> None:
    text = "Translate this to English: امروز هوا خیلی خوب است."
    decision, firings = _guard(registry, text, _decision(registry, "fa", "translator"))
    assert decision.response_language == "en" and firings[0].guard == "G2_language"


def test_g2_keeps_finglish_persian(registry: SkillRegistry) -> None:
    decision, firings = _guard(registry, "salam chetori", _decision(registry, "fa", "general_chat"))
    assert decision.response_language == "fa" and firings == []


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("What causes the seasons on Earth? Please answer in Persian.", "fa"),
        ("Explain inflation and reply to me in Persian", "fa"),
        ("به انگلیسی جواب بده: هوش مصنوعی چیست؟", "en"),
        ("هوش مصنوعی چیست؟ به انگلیسی پاسخ بده", "en"),
    ],
)
def test_g2_respects_an_explicit_reply_language(
    registry: SkillRegistry, text: str, lang: str
) -> None:
    """Dev D25: "answer in Persian" under an English instruction stays `fa`."""
    decision, firings = _guard(registry, text, _decision(registry, lang, "general_chat"))
    assert decision.response_language == lang and firings == []


def test_g2_leaves_other_languages_alone(registry: SkillRegistry) -> None:
    decision, firings = _guard(registry, "سلام خوبی؟", _decision(registry, "de", "general_chat"))
    assert decision.response_language == "de" and firings == []


async def test_guards_run_inside_route_and_are_logged(
    make_router: Callable[..., Router], plan
) -> None:
    reply = plan(
        steps=[{"id": "s1", "skill": "translator", "instruction": "Tr.", "input_from": "user"}]
    )
    llm = FakeLLM([], default=reply)
    result = await make_router().route(build_user_request("اینو ترجمه کن"), llm)
    guards = [e.data["guard"] for e in result.events if e.event == "guard"]
    assert guards == ["G2_language", "G1_missing_payload"]
    assert result.decision.needs_clarification
    assert result.decision.response_language == "fa"
    assert result.decision.clarification_question == MISSING_PAYLOAD_QUESTION["fa"]
    assert result.decision.route_source == "llm"
