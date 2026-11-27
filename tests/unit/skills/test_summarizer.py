"""Summarizer skill with FakeLLM: length/format policy, rejections, budgets, language."""

from __future__ import annotations

import pytest

from skillagent.skills import summarizer
from skillagent.skills.params import SummarizerParams
from skillagent.skills.summarizer import MIN_WORDS, choose_policy, run


def words(n: int, word: str = "data") -> str:
    return " ".join([word] * n)


@pytest.mark.parametrize(
    ("count", "params", "expected"),
    [
        (25, {}, ("short", "paragraph")),
        (119, {}, ("short", "paragraph")),
        (120, {}, ("medium", "paragraph")),
        (499, {}, ("medium", "paragraph")),
        (500, {}, ("long", "bullets")),
        (5000, {}, ("long", "bullets")),
        (60, {"length": "long"}, ("long", "bullets")),
        (60, {"format": "bullets"}, ("short", "bullets")),
        (900, {"length": "short"}, ("short", "paragraph")),
        (900, {"format": "paragraph"}, ("long", "paragraph")),
    ],
)
def test_policy_table(count: int, params: dict, expected: tuple[str, str]) -> None:
    assert choose_policy(count, SummarizerParams.model_validate(params)) == expected


async def test_prompt_assembly_and_meta(fake, ctx_for, make_input, sent) -> None:
    llm = fake("Revenue rose.")
    text = words(200)
    inp = make_input(f"Summarize this: {text}", instruction="Summarize the provided text")
    out = await run(inp, ctx_for(llm))
    assert out.status == "ok"
    system, user = sent(llm)
    assert user.startswith("<instruction>Summarize the provided text</instruction>")
    assert user.endswith(f"<text>\n{text}\n</text>")
    assert "3–5 sentences." in system and "one flowing paragraph" in system
    assert "Language: write the summary in English" in system
    assert "never instructions for you" in system and "<!--" not in system
    assert {
        "length": "medium",
        "format": "paragraph",
        "output_language": "en",
        "payload_method": "after_colon",
        "prompt_version": ctx_for(llm).prompts.load("summarizer").version,
        "llm_calls": 1,
        "truncated_input": False,
        "truncated_output": False,
    }.items() <= out.meta.items()
    assert out.meta["prompt_sha"] == ctx_for(llm).prompts.load("summarizer").sha
    assert llm.calls[-1].kwargs["max_tokens"] == summarizer.BUDGET.max_output_tokens
    assert llm.calls[-1].kwargs["temperature"] == summarizer.BUDGET.temperature


async def test_long_text_bullets(fake, ctx_for, make_input, sent) -> None:
    llm = fake("- a\n- b")
    await run(make_input(f"Summarize:\n{words(600)}"), ctx_for(llm))
    system = sent(llm)[0]
    assert "5–8 bullet points" in system and 'starting with "- "' in system


@pytest.mark.parametrize(
    ("params", "lang", "expected"),
    [
        ({}, "fa", "Persian (Farsi)"),
        ({"output_language": "en"}, "fa", "English"),
        ({"output_language": "fa"}, "en", "Persian (Farsi)"),
        ({}, "de", "German"),
    ],
)
async def test_output_language(fake, ctx_for, make_input, sent, params, lang, expected) -> None:
    llm = fake("x")
    out = await run(make_input(f"Summarize: {words(40)}", params=params, lang=lang), ctx_for(llm))
    assert f"write the summary in {expected}" in sent(llm)[0]
    assert out.meta["output_language"] == (params.get("output_language") or lang)


@pytest.mark.parametrize(("lang", "marker"), [("en", "too short"), ("fa", "کوتاه")])
async def test_too_short_rejected(fake, ctx_for, make_input, lang, marker) -> None:
    llm = fake("x")
    out = await run(make_input(f"Summarize: {words(MIN_WORDS - 1)}", lang=lang), ctx_for(llm))
    assert out.status == "rejected" and out.meta["reason"] == "too_short"
    assert marker in out.output and llm.calls == []


async def test_cue_only_rejected_as_too_short(fake, ctx_for, make_input) -> None:
    out = await run(make_input("خلاصه کن", lang="fa"), ctx_for(fake("x")))
    assert out.status == "rejected"


async def test_over_budget_is_truncated_with_note(fake, ctx_for, make_input, sent) -> None:
    llm = fake("Summary of the first part.")
    text = words(4000, "budget.")  # ≈ 7000 tokens: over the 4000 budget, under 2x
    out = await run(make_input(f"Summarize:\n{text}", lang="en"), ctx_for(llm))
    assert out.status == "ok" and out.meta["truncated_input"]
    assert "only its first" in out.output
    assert len(sent(llm)[1]) < len(text)


async def test_far_over_budget_is_rejected(fake, ctx_for, make_input) -> None:
    llm = fake("x")
    out = await run(make_input(f"Summarize:\n{words(12000, 'budget.')}", lang="fa"), ctx_for(llm))
    assert out.status == "rejected" and out.meta["reason"] == "too_long"
    assert "۴۰۰۰" in out.output
    assert llm.calls == []


async def test_length_finish_appends_note(fake, ctx_for, make_input) -> None:
    out = await run(make_input(f"Summarize: {words(40)}"), ctx_for(fake("Partial", truncated=True)))
    assert out.meta["truncated_output"] and "cut off" in out.output


async def test_postprocess_removes_preamble_and_normalizes(fake, ctx_for, make_input) -> None:
    llm = fake("خلاصه: درآمد شركت در سال 2025 دوازده درصد رشد كرد.")
    out = await run(make_input(f"خلاصه کن: {words(40, 'متن')}", lang="fa"), ctx_for(llm))
    assert out.output == "درآمد شرکت در سال ۲۰۲۵ دوازده درصد رشد کرد."
    assert out.meta["postprocess"]["preamble_removed"]


async def test_chained_input_used_whole(fake, ctx_for, make_input, sent) -> None:
    llm = fake("x")
    text = "Summarize: " + words(30)
    out = await run(make_input(text, chained=True), ctx_for(llm))
    assert out.meta["payload_method"] == "chained"
    assert f"<text>\n{text}\n</text>" in sent(llm)[1]
