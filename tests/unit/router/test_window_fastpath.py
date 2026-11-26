from __future__ import annotations

from collections.abc import Callable

import pytest

from skillagent.core.language import estimate_tokens
from skillagent.core.registry import SkillRegistry
from skillagent.router import Router, build_user_request
from skillagent.router.fast_path import try_route
from skillagent.router.router import ROUTER_VIEW_TOKENS, router_view
from skillagent.testing import FakeLLM, make_skill_spec

# --- long-prompt windowing -----------------------------------------------------------------


def test_short_text_is_untouched() -> None:
    assert router_view("Summarize this: short text.") == ("Summarize this: short text.", 0)


def test_long_text_keeps_head_and_tail() -> None:
    words = [f"w{i}" for i in range(3000)]
    text = "Summarize this: " + " ".join(words) + " Then translate it to German."
    view, omitted = router_view(text)
    assert omitted > 0
    assert view.startswith("Summarize this: w0 w1")
    assert view.endswith("Then translate it to German.")
    assert f"[… {omitted} words omitted …]" in view
    head, tail = view.split(f"\n[… {omitted} words omitted …]\n")
    assert estimate_tokens(head) <= 500 and estimate_tokens(tail) <= 150
    assert len(head.split()) + len(tail.split()) + omitted == len(text.split())


def test_long_persian_text_is_windowed() -> None:
    text = "این متن را خلاصه کن:\n" + "رایانش ابری " * 2000
    view, omitted = router_view(text)
    assert omitted > 0 and view.startswith("این متن را خلاصه کن:")
    assert estimate_tokens(view) < ROUTER_VIEW_TOKENS + 50


async def test_router_sends_windowed_view(make_router: Callable[..., Router], plan) -> None:
    llm = FakeLLM([], default=plan())
    text = "Summarize this: " + "lorem ipsum " * 2000 + "END-MARKER"
    result = await make_router().route(build_user_request(text), llm)
    user = llm.calls[0].messages[1]["content"]
    assert "words omitted" in user and "END-MARKER" in user
    prompt_event = next(e for e in result.events if e.event == "prompt")
    assert prompt_event.data["omitted_words"] > 0


# --- fast path -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("2+2", "en"),
        ("(3+4)*2^3", "en"),
        ("what is 15% of 2,480?", "en"),
        ("calculate 12 * 3.5", "en"),
        ("۱۲ × ۳٫۵", "fa"),
        ("۲۵ ضرب در ۴", None),  # number words → not a pure expression
        ("۲+۲ چند می‌شود؟", "fa"),
        ("sqrt(144) + 3**3", "en"),
    ],
)
def test_fast_path_positives(registry: SkillRegistry, text: str, lang: str | None) -> None:
    result = try_route(build_user_request(text), registry)
    if lang is None:
        assert result is None
        return
    assert result is not None and result.rule == "pure_expression"
    decision = result.decision
    assert decision.route_source == "rule"
    assert [s.skill for s in decision.steps] == ["calculator"]
    assert decision.response_language == lang


@pytest.mark.parametrize(
    "text",
    [
        "2 apples and 3 oranges",
        "what is 2+2 in Persian?",
        "Translate 2+2=4 into Persian",
        "hello",
        "42",
        "Summarize this: revenue grew 5% to 120 million.",
        "If a train travels 180 km in 2.5 hours, what is its average speed?",
    ],
)
def test_fast_path_negatives(registry: SkillRegistry, text: str) -> None:
    assert try_route(build_user_request(text), registry) is None


def test_fast_path_empty_input_clarifies_in_english(registry: SkillRegistry) -> None:
    result = try_route(build_user_request("   "), registry)
    assert result is not None and result.rule == "empty"
    assert result.decision.needs_clarification
    assert result.decision.response_language == "en"
    assert result.decision.clarification_question


def test_fast_path_needs_calculator_in_registry() -> None:
    reg = SkillRegistry()
    reg.register(make_skill_spec("general_chat"))
    assert try_route(build_user_request("2+2"), reg) is None


async def test_fast_path_makes_no_llm_call(make_router: Callable[..., Router]) -> None:
    llm = FakeLLM([])  # any call would raise AssertionError
    result = await make_router().route(build_user_request("۱۲ × ۳٫۵"), llm)
    assert result.llm_calls == 0 and llm.calls == []
    assert result.decision.route_source == "rule"
    assert any(e.event == "fast_path" for e in result.events)
