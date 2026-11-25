from __future__ import annotations

import pytest

from skillagent.core.errors import LLMTimeoutError
from skillagent.llm.types import LLMClient, ToolCall
from skillagent.testing import FakeLLM, FakeRule

USER = [{"role": "user", "content": "translate this please"}]


def test_implements_protocol() -> None:
    assert isinstance(FakeLLM([]), LLMClient)


async def test_regex_matches_purpose_or_last_user_message() -> None:
    llm = FakeLLM([FakeRule("skill:translator", "by purpose"), FakeRule("translate", "by text")])
    assert (await llm.complete(USER, purpose="skill:translator")).text == "by purpose"
    assert (await llm.complete(USER, purpose="other")).text == "by text"


async def test_callable_matcher_and_reply() -> None:
    llm = FakeLLM(
        [FakeRule(lambda msgs, purpose: len(msgs) == 1, lambda msgs: msgs[-1]["content"].upper())]
    )
    assert (await llm.complete(USER)).text == "TRANSLATE THIS PLEASE"


async def test_times_limits_rule_then_falls_through() -> None:
    llm = FakeLLM([FakeRule(".*", "first", times=1)], default="later")
    assert [(await llm.complete(USER)).text for _ in range(3)] == ["first", "later", "later"]


async def test_tool_call_reply() -> None:
    call = ToolCall(
        id="t1",
        name="evaluate",
        arguments={"expression": "2+2"},
        raw_arguments='{"expression": "2+2"}',
    )
    llm = FakeLLM([FakeRule("calc", [call])])
    response = await llm.complete(USER, purpose="calc", tool_choice="evaluate")
    assert response.tool_calls == [call] and response.text == ""
    assert llm.calls[0].kwargs["tool_choice"] == "evaluate"


async def test_exception_reply() -> None:
    llm = FakeLLM([FakeRule(".*", LLMTimeoutError("slow"))])
    with pytest.raises(LLMTimeoutError):
        await llm.complete(USER)


async def test_no_match_names_purpose() -> None:
    with pytest.raises(AssertionError, match="purpose='router'"):
        await FakeLLM([FakeRule("nothing-matches-this", "x")]).complete(USER, purpose="router")


async def test_records_snapshot_and_strips_think() -> None:
    messages = [{"role": "user", "content": "a"}]
    llm = FakeLLM([], default="<think>hmm</think> done")
    response = await llm.complete(messages, purpose="p", max_tokens=5)
    messages[0]["content"] = "mutated"
    assert response.text == "done"
    assert llm.calls[0].messages == [{"role": "user", "content": "a"}]
    assert llm.calls[0].kwargs["max_tokens"] == 5
    assert response.attempts == 1 and response.usage.prompt_tokens == 1
