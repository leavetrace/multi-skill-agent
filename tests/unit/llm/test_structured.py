"""Structured-output loop, exercised through FakeLLM (the same helper the gateway uses)."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from skillagent.core.errors import StructuredOutputError
from skillagent.core.types import RoutingDecision
from skillagent.skills.catalog import build_default_registry
from skillagent.testing import FakeLLM, FakeRule

MESSAGES = [{"role": "system", "content": "route"}, {"role": "user", "content": "سلام"}]


class Ping(BaseModel):
    ok: bool


def plan(skill: str, **step: object) -> str:
    return json.dumps(
        {
            "response_language": "fa",
            "steps": [{"id": "s1", "skill": skill, "instruction": "reply", **step}],
        },
        ensure_ascii=False,
    )


async def test_success_first_try() -> None:
    llm = FakeLLM([FakeRule("router", 'Sure:\n```json\n{"ok": true}\n```')])
    result = await llm.complete_structured(MESSAGES, Ping, purpose="router")
    assert result.value == Ping(ok=True)
    assert result.repairs == 0
    assert result.response.text.startswith("Sure")
    assert llm.calls[0].kwargs["json_mode"] is True


async def test_repair_then_success() -> None:
    llm = FakeLLM(
        [FakeRule(r"^router:repair", '{"ok": true}'), FakeRule("router", '{"ok": "maybe"}')]
    )
    result = await llm.complete_structured(MESSAGES, Ping, purpose="router")
    assert result.repairs == 1
    assert [c.purpose for c in llm.calls] == ["router", "router:repair"]
    repair_messages = llm.calls[1].messages
    assert repair_messages[:2] == MESSAGES
    assert repair_messages[2] == {"role": "assistant", "content": '{"ok": "maybe"}'}
    assert repair_messages[3]["role"] == "user"
    assert repair_messages[3]["content"].startswith("Your previous output was invalid: ok:")
    assert repair_messages[3]["content"].endswith(
        "Return ONLY a corrected JSON object that fixes this."
    )


async def test_repairs_exhausted_raise_with_raw_text() -> None:
    llm = FakeLLM([], default="I cannot do JSON")
    with pytest.raises(StructuredOutputError) as info:
        await llm.complete_structured(MESSAGES, Ping, max_repairs=2, purpose="router")
    assert info.value.raw_text == "I cannot do JSON"
    assert "no JSON object" in info.value.errors
    assert len(llm.calls) == 3


async def test_zero_repairs() -> None:
    llm = FakeLLM([], default="{}")
    with pytest.raises(StructuredOutputError, match="ok: Field required"):
        await llm.complete_structured(MESSAGES, Ping, max_repairs=0)
    assert len(llm.calls) == 1


async def test_invalid_json_message() -> None:
    llm = FakeLLM([], default='{"ok": tru}')
    with pytest.raises(StructuredOutputError, match="not valid JSON"):
        await llm.complete_structured(MESSAGES, Ping, max_repairs=0)


async def test_validation_context_passed_through() -> None:
    """Router scenario: an unknown skill only fails *with* the registry in context, and the
    repair message carries the V5 error so the model can fix it."""
    registry = build_default_registry()
    llm = FakeLLM(
        [FakeRule("router:repair", plan("General Chat")), FakeRule("router", plan("weather"))]
    )
    result = await llm.complete_structured(
        MESSAGES,
        RoutingDecision,
        purpose="router",
        validation_context={"registry": registry, "max_skills": 2},
    )
    assert result.value.steps[0].skill == "general_chat"
    assert result.repairs == 1
    assert "'weather' is not a known skill" in llm.calls[1].messages[-1]["content"]

    no_context = FakeLLM([], default=plan("weather"))
    assert (await no_context.complete_structured(MESSAGES, RoutingDecision)).repairs == 0


async def test_kwargs_forwarded() -> None:
    llm = FakeLLM([], default='{"ok": false}')
    await llm.complete_structured(MESSAGES, Ping, temperature=0.3, max_tokens=99, timeout_s=7)
    assert llm.calls[0].kwargs == {
        "temperature": 0.3,
        "max_tokens": 99,
        "json_mode": True,
        "tools": None,
        "tool_choice": None,
        "timeout_s": 7,
    }


async def test_repair_purpose_without_base_purpose() -> None:
    llm = FakeLLM([FakeRule("^repair", '{"ok": true}')], default="nope")
    await llm.complete_structured(MESSAGES, Ping)
    assert [c.purpose for c in llm.calls] == ["", "repair"]


async def test_truncated_reply_repair_message_mentions_token_limit() -> None:
    from skillagent.llm.types import LLMResponse

    class CutOffFirst(FakeLLM):
        async def complete(self, messages, **kwargs):  # type: ignore[override]
            response = await super().complete(messages, **kwargs)
            if len(self.calls) == 1:
                return response.model_copy(update={"finish_reason": "length"})
            return response

    llm = CutOffFirst([FakeRule("router:repair", '{"ok": true}'), FakeRule("router", '{"ok": ')])
    result = await llm.complete_structured(MESSAGES, Ping, purpose="router")
    assert result.repairs == 1
    assert "cut off at the token limit" in llm.calls[1].messages[-1]["content"]
    assert isinstance(result.response, LLMResponse)


def test_fake_llm_reports_finish_reason() -> None:
    import asyncio

    from skillagent.llm.types import ToolCall

    call = ToolCall(id="t1", name="evaluate", arguments={}, raw_arguments="{}")
    llm = FakeLLM([FakeRule("tool", [call]), FakeRule("text", "hi")])
    tool = asyncio.run(llm.complete([{"role": "user", "content": "x"}], purpose="tool"))
    text = asyncio.run(llm.complete([{"role": "user", "content": "x"}], purpose="text"))
    assert (tool.finish_reason, text.finish_reason) == ("tool_calls", "stop")
