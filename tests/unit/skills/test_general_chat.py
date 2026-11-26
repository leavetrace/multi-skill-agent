"""General chat with FakeLLM: message shape, language, degraded mode, budgets."""

from __future__ import annotations

import pytest

from skillagent.skills import general_chat
from skillagent.skills.general_chat import run


async def test_message_shape(fake, ctx_for, make_input, sent) -> None:
    llm = fake("Hi! I'm well.")
    inp = make_input("Hi, how are you?", instruction="Greet the user")
    out = await run(inp, ctx_for(llm))
    system, user = sent(llm)
    assert user == "<task>Greet the user</task>\n<message>\nHi, how are you?\n</message>"
    assert "Answer in English" in system
    assert "cannot browse the web" in system and "no memory" in system
    assert "<!--" not in system and "could not be classified" not in system
    assert out.status == "ok" and out.output == "Hi! I'm well."
    assert out.meta["prompt_version"] == 1 and not out.meta["degraded"]
    call = llm.calls[-1]
    assert call.purpose == "skill:general_chat"
    assert call.kwargs["temperature"] == general_chat.BUDGET.temperature
    assert call.kwargs["max_tokens"] == general_chat.BUDGET.max_output_tokens


@pytest.mark.parametrize(("lang", "name"), [("fa", "Persian (Farsi)"), ("de", "German")])
async def test_response_language(fake, ctx_for, make_input, sent, lang, name) -> None:
    llm = fake("x")
    await run(make_input("salam chetori?", lang=lang), ctx_for(llm))
    assert f"Answer in {name}" in sent(llm)[0]


async def test_finglish_rule_in_prompt(fake, ctx_for, make_input, sent) -> None:
    llm = fake("x")
    await run(make_input("salam chetori?", lang="fa"), ctx_for(llm))
    assert "Finglish" in sent(llm)[0]


async def test_degraded_flag(fake, ctx_for, make_input, sent) -> None:
    llm = fake("x")
    out = await run(make_input("help me", params={"degraded": True}), ctx_for(llm))
    assert "could not be classified" in sent(llm)[0]
    assert "Never mention routing" in sent(llm)[0]
    assert out.meta["degraded"] is True


async def test_chained_input_is_data(fake, ctx_for, make_input, sent) -> None:
    llm = fake("x")
    inp = make_input("1380", instruction="Explain what this increase is called", chained=True)
    await run(inp, ctx_for(llm))
    user = sent(llm)[1]
    assert user == "<task>Explain what this increase is called</task>\n<text>\n1380\n</text>"


async def test_persian_reply_normalized_but_not_relabelled(fake, ctx_for, make_input) -> None:
    llm = fake("خلاصه: سلام! من يك دستيار هستم و 4 كار بلدم.")
    out = await run(make_input("سلام", lang="fa"), ctx_for(llm))
    assert out.output == "خلاصه: سلام! من یک دستیار هستم و ۴ کار بلدم."
    assert "preamble_removed" not in out.meta["postprocess"]


async def test_too_long_rejected(fake, ctx_for, make_input) -> None:
    llm = fake("x")
    out = await run(make_input("word " * 7000, lang="fa"), ctx_for(llm))
    assert out.status == "rejected" and out.meta["reason"] == "too_long"
    assert "خلاصه" in out.output and llm.calls == []


async def test_length_finish_appends_note(fake, ctx_for, make_input) -> None:
    out = await run(make_input("Tell me about Rome"), ctx_for(fake("Rome is", truncated=True)))
    assert out.meta["truncated_output"] and "cut off" in out.output
