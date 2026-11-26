"""Router.route flow: success, repair, V8 over-limit, fallback, and never raising."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from skillagent.core.errors import (
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from skillagent.router import Router, build_user_request
from skillagent.router.router import PURPOSE
from skillagent.testing import FakeLLM, FakeRule


def _step(sid: str, skill: str, input_from: str = "user", **params: str) -> dict[str, object]:
    return {
        "id": sid,
        "skill": skill,
        "instruction": f"do {skill}",
        "input_from": input_from,
        "params": params,
    }


async def test_successful_route_uses_router_call_settings(
    make_router: Callable[..., Router], plan
) -> None:
    llm = FakeLLM([], default=plan(steps=[_step("s1", "summarizer")]))
    result = await make_router().route(build_user_request("Summarize this: a b c d e"), llm)
    assert result.llm_calls == 1
    assert result.decision.route_source == "llm"
    assert [s.skill for s in result.decision.steps] == ["summarizer"]
    call = llm.calls[0]
    assert call.purpose == PURPOSE
    assert call.kwargs["temperature"] == 0 and call.kwargs["max_tokens"] == 600
    assert call.kwargs["json_mode"] is True
    names = [e.event for e in result.events]
    assert names[0] == "start" and names[-1] == "end"
    assert {"candidates", "prompt", "llm"} <= set(names)
    end = result.events[-1].data
    assert end["route_source"] == "llm" and "latency_ms" in end


async def test_model_cannot_set_route_source(make_router: Callable[..., Router], plan) -> None:
    llm = FakeLLM([], default=plan(route_source="rule"))
    result = await make_router().route(build_user_request("hello there"), llm)
    assert result.decision.route_source == "llm"


async def test_elapsed_ms_is_used_for_event_times(make_router: Callable[..., Router], plan) -> None:
    ticks = iter(range(100))
    llm = FakeLLM([], default=plan())
    result = await make_router().route(
        build_user_request("hello"), llm, elapsed_ms=lambda: float(next(ticks))
    )
    times = [e.t_ms for e in result.events]
    assert times == sorted(times) and times[0] == 0.0


@pytest.mark.parametrize(
    "invalid",
    [
        {"steps": [_step("s1", "weather_bot")]},  # unknown skill (V5)
        {"steps": [_step("s1", "summarizer", "s2"), _step("s2", "translator")]},  # V4
        {"steps": [_step("s1", "calculator"), _step("s2", "summarizer", "s1")]},  # V6 IO kind
        {"steps": [_step("s1", "translator", target_language="Klingonese")]},  # V7
    ],
)
async def test_repair_after_invalid_reply(
    make_router: Callable[..., Router], plan, invalid: dict[str, object]
) -> None:
    llm = FakeLLM(
        [
            FakeRule(f"^{PURPOSE}\n", plan(**invalid), times=1),
            FakeRule(f"^{PURPOSE}:repair", plan(steps=[_step("s1", "translator")])),
        ]
    )
    result = await make_router().route(build_user_request("Translate: hola amigo"), llm)
    assert result.llm_calls == 2
    assert result.decision.route_source == "llm"
    assert [s.skill for s in result.decision.steps] == ["translator"]
    llm_event = next(e for e in result.events if e.event == "llm")
    assert llm_event.data["repairs"] == 1
    assert "invalid" in llm.calls[1].messages[-1]["content"]


async def test_v8_over_limit_keeps_two_and_records_dropped(
    make_router: Callable[..., Router], plan
) -> None:
    steps = [_step("s1", "translator", target_language="de"), _step("s2", "summarizer"),
             _step("s3", "general_chat")]  # fmt: skip
    llm = FakeLLM([], default=plan(steps=steps))
    result = await make_router().route(
        build_user_request("Translate to German, summarize, and tell a joke: some text here"),
        llm,
    )
    assert [s.id for s in result.decision.steps] == ["s1", "s2"]
    assert result.decision.dropped_intents == ["do general_chat"]
    assert result.decision.steps[0].params == {"target_language": "de"}


async def test_chain_and_params_are_canonicalized(make_router: Callable[..., Router], plan) -> None:
    steps = [_step("s1", "Summarizer"), _step("s2", "translator", "s1", target_language="Persian")]
    llm = FakeLLM([], default=plan(steps=steps))
    result = await make_router().route(build_user_request("Summarize and translate: x y"), llm)
    s1, s2 = result.decision.steps
    assert (s1.skill, s2.skill, s2.input_from) == ("summarizer", "translator", "s1")
    assert s2.params == {"target_language": "fa"}


# --- fallback --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "lang"),
    [("Summarize this: some text", "en"), ("این متن رو summarize کن: some English text", "fa")],
)
async def test_fallback_after_repair_exhausted(
    make_router: Callable[..., Router], text: str, lang: str
) -> None:
    llm = FakeLLM([], default='{"steps": "not a list"}')
    result = await make_router().route(build_user_request(text), llm)
    decision = result.decision
    assert decision.route_source == "fallback"
    assert [s.skill for s in decision.steps] == ["general_chat"]
    assert decision.response_language == lang
    assert decision.confidence == 0.0
    assert "StructuredOutputError" in decision.rationale
    assert result.llm_calls == 2
    assert any(e.event == "fallback" for e in result.events)


@pytest.mark.parametrize(
    "error",
    [
        LLMTimeoutError("timed out"),
        LLMRateLimitError("429 daily quota"),
        LLMProviderError("500 upstream", status_code=500),
        TimeoutError(),
    ],
)
async def test_fallback_on_provider_errors(
    make_router: Callable[..., Router], error: Exception
) -> None:
    llm = FakeLLM([], default=None)
    llm.rules.append(FakeRule(".*", error))
    result = await make_router().route(build_user_request("hello"), llm)
    assert result.decision.route_source == "fallback"
    assert type(error).__name__ in result.decision.rationale
    fallback = next(e for e in result.events if e.event == "fallback")
    assert fallback.data["error"] == type(error).__name__


@pytest.mark.parametrize(
    "reply",
    ["", "   ", "Sure! I think the user wants a summary.", "{not json", "[]", "null",
     '{"response_language": "klingon", "steps": []}', "<think>hmm</think>"],
)  # fmt: skip
async def test_never_raises_on_garbage(make_router: Callable[..., Router], reply: str) -> None:
    result = await make_router().route(build_user_request("hello"), FakeLLM([], default=reply))
    assert result.decision.route_source == "fallback"
    assert result.decision.steps[0].skill == "general_chat"


async def test_clarification_from_model_passes_through(
    make_router: Callable[..., Router], plan
) -> None:
    reply = plan(steps=[], needs_clarification=True, clarification_question="Which text?")
    result = await make_router().route(
        build_user_request("Can you help me with this?"), FakeLLM([], default=reply)
    )
    assert result.decision.needs_clarification
    assert result.decision.clarification_question == "Which text?"


async def test_payload_is_only_in_user_message(make_router: Callable[..., Router], plan) -> None:
    secret = "UNIQUE-PAYLOAD-TOKEN"
    llm = FakeLLM([], default=plan())
    await make_router().route(build_user_request(f"Summarize: {secret} " + "x " * 20), llm)
    system, user = (m["content"] for m in llm.calls[0].messages)
    assert secret not in system and secret in user
    json.loads(plan())  # sanity: fixture produces JSON
