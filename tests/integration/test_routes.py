"""Every route type through `run_agent` with the real registry and a scripted `FakeLLM`."""

from __future__ import annotations

import asyncio
import dataclasses

from skillagent.core.errors import LLMProviderError, LLMRateLimitError
from skillagent.core.types import SkillInput, SkillOutput
from skillagent.graph.composer import APOLOGY
from skillagent.skills.base import SkillContext
from skillagent.skills.catalog import build_default_registry

ARTICLE = (
    "The city council met on Monday to discuss the new public library. Members agreed that "
    "the building will open next spring, that it will stay open until ten at night, and that "
    "children's programs will be free. The budget was approved after a long debate about "
    "parking and the cost of the new reading rooms."
)


def purposes(llm) -> list[str]:
    return [c.purpose for c in llm.calls]


def user_message(llm, purpose: str) -> str:
    call = next(c for c in llm.calls if c.purpose == purpose)
    return next(m["content"] for m in call.messages if m["role"] == "user")


def events(run, node: str, event: str) -> list:
    return [e for e in run.trace if e.node == node and e.event == event]


async def test_single_step(run, fake_llm, plan, mk_step):
    llm = fake_llm(
        router=plan("en", mk_step("s1", "general_chat", "Answer the greeting")),
        general_chat="Hi! I'm doing well, thanks for asking.",
    )
    result = await run("Hello, how are you today?", llm)
    assert result.response == "Hi! I'm doing well, thanks for asking."
    assert result.results["s1"].status == "ok"
    assert result.llm_calls == 2
    assert purposes(llm) == ["router", "skill:general_chat"]
    assert result.decision is not None and result.decision.route_source == "llm"
    assert result.total_ms > 0


async def test_chain_feeds_only_the_dependency_output(run, fake_llm, plan, mk_step):
    summary = "The council approved a new library opening next spring with free kids' programs."
    llm = fake_llm(
        router=plan(
            "en",
            mk_step("s1", "summarizer", "Summarize the article"),
            mk_step("s2", "translator", "Translate the summary", "s1", target_language="fa"),
        ),
        summarizer=summary,
        translator="شورای شهر کتابخانهٔ تازه‌ای را تصویب کرد.",
    )
    result = await run(f"Summarize this and translate the summary to Persian: {ARTICLE}", llm)

    assert purposes(llm) == ["router", "skill:summarizer", "skill:translator"]
    sent = user_message(llm, "skill:translator")
    assert summary in sent
    assert "parking" not in sent  # the original article never reaches the second step
    start = events(result, "skill:translator", "start")[0]
    assert start.data["is_chained"] is True
    assert result.results["s2"].meta["payload_method"] == "chained"
    # chain → only the final output is shown; the intermediate one stays in results/trace
    assert result.response == "شورای شهر کتابخانهٔ تازه‌ای را تصویب کرد."
    assert summary not in result.response
    assert [e.data["steps"] for e in events(result, "scheduler", "wave")] == [["s1"], ["s2"]]


async def test_parallel_steps_run_concurrently_in_one_wave(
    run, fake_llm, barrier_llm, plan, mk_step
):
    rules = fake_llm(
        router=plan(
            "en",
            mk_step("s1", "translator", "Translate 'good morning' to German", target_language="de"),
            mk_step("s2", "general_chat", "Tell a fun fact about cats"),
        ),
        translator="Guten Morgen",
        general_chat="Cats sleep about 15 hours a day.",
    ).rules
    llm = barrier_llm(rules, parties=2)  # each skill call waits for the other one
    result = await run("Translate 'good morning' to German and tell me a fun fact about cats", llm)
    assert {r.status for r in result.results.values()} == {"ok"}
    assert [e.data["steps"] for e in events(result, "scheduler", "wave")] == [["s1", "s2"]]
    assert result.response == (
        "**Translation**\nGuten Morgen\n\n**Answer**\nCats sleep about 15 hours a day."
    )


async def test_clarification_calls_no_skill(run, fake_llm, plan):
    llm = fake_llm(
        router=plan(
            "en",
            needs_clarification=True,
            clarification_question="Which text would you like me to translate?",
        )
    )
    result = await run("translate this", llm)
    assert purposes(llm) == ["router"]
    assert result.results == {}
    assert result.response.startswith("Which text would you like me to translate?")
    assert "full request" in result.response
    assert events(result, "clarify", "end")


async def test_router_fallback_runs_degraded_general_chat(run, fake_llm):
    llm = fake_llm(router="this is not json at all", general_chat="Happy to help!")
    result = await run("Tell me something nice", llm)
    assert result.decision is not None and result.decision.route_source == "fallback"
    assert result.decision.steps[0].params == {"degraded": True}
    assert purposes(llm) == [
        "router",
        "router:repair",
        "skill:general_chat",
    ]  # 1 repair, then skill
    assert result.results["s1"].meta["degraded"] is True
    assert result.response == "Happy to help!"
    assert result.llm_calls == 3


async def test_more_than_two_intents_runs_two_and_notifies(run, fake_llm, plan, mk_step):
    llm = fake_llm(
        router=plan(
            "en",
            mk_step("s1", "general_chat", "Say hello"),
            mk_step("s2", "translator", "Translate 'cat' to French", target_language="fr"),
            mk_step("s3", "general_chat", "Write a haiku about rain"),
        ),
        general_chat="Hello!",
        translator="chat",
    )
    result = await run("Say hello, translate 'cat' to French, and write a haiku about rain", llm)
    assert set(result.results) == {"s1", "s2"}
    assert result.decision is not None
    assert result.decision.dropped_intents == ["Write a haiku about rain"]
    assert result.response.endswith(
        "Note: I handle up to 2 tasks per request, so I skipped: Write a haiku about rain."
    )


async def test_timeout_keeps_the_other_parallel_result(run, fake_llm, plan, mk_step):
    async def sleepy(inp: SkillInput, ctx: SkillContext) -> SkillOutput:
        await asyncio.sleep(5)
        return SkillOutput(status="ok", output="never")

    registry = build_default_registry()
    slow = dataclasses.replace(
        registry.get("general_chat"),
        run=sleepy,
        budget=registry.get("general_chat").budget.model_copy(update={"timeout_s": 0.05}),
    )
    registry._specs["general_chat"] = slow  # swap one runner, keep the real catalog otherwise
    llm = fake_llm(
        router=plan(
            "en",
            mk_step("s1", "translator", "Translate 'thank you' to German", target_language="de"),
            mk_step("s2", "general_chat", "Tell me a joke"),
        ),
        translator="Danke",
    )
    result = await run("Translate 'thank you' to German and tell me a joke", llm, registry=registry)
    assert result.results["s2"].status == "timeout"
    assert result.results["s1"].status == "ok"
    assert "**Translation**\nDanke" in result.response
    assert "The answer step took too long and was stopped." in result.response
    assert APOLOGY not in result.response


async def test_partial_failure_when_one_skill_raises(run, fake_llm, plan, mk_step):
    llm = fake_llm(
        router=plan(
            "en",
            mk_step("s1", "translator", "Translate 'thank you' to German", target_language="de"),
            mk_step("s2", "general_chat", "Tell me a joke"),
        ),
        translator="Danke",
        general_chat=LLMProviderError("upstream 500"),
    )
    result = await run("Translate 'thank you' to German and tell me a joke", llm)
    failed = result.results["s2"]
    assert failed.status == "error"
    assert failed.error == "LLMProviderError: upstream 500"
    assert failed.meta["llm_calls"] == 1  # counted by the wrapper: the skill never returned meta
    assert "**Translation**\nDanke" in result.response
    assert "The answer step ran into an error" in result.response


async def test_failed_dependency_skips_the_dependent(run, fake_llm, plan, mk_step):
    llm = fake_llm(
        router=plan(
            "en",
            mk_step("s1", "summarizer", "Summarize the article"),
            mk_step("s2", "translator", "Translate the summary", "s1", target_language="fa"),
        ),
        summarizer=LLMProviderError("boom"),
    )
    result = await run(f"Summarize this and translate it to Persian: {ARTICLE}", llm)
    assert result.results["s1"].status == "error"
    assert result.results["s2"].status == "skipped"
    assert result.results["s2"].meta["reason"] == "dependency"
    assert "skill:translator" not in purposes(llm)
    assert result.response.startswith(APOLOGY)
    assert "The summary step ran into an error" in result.response
    assert "The translation step was skipped" in result.response


async def test_rejected_dependency_shows_its_message(run, fake_llm, plan, mk_step):
    llm = fake_llm(
        router=plan(
            "en",
            mk_step("s1", "summarizer", "Summarize the text"),
            mk_step("s2", "translator", "Translate the summary", "s1", target_language="fa"),
        )
    )
    result = await run("Summarize this and translate it: The cat sat.", llm)
    assert result.results["s1"].status == "rejected"
    assert result.results["s2"].status == "skipped"
    assert result.response == result.results["s1"].output  # user-facing, no apology
    assert result.llm_calls == 1


async def test_pure_arithmetic_fast_path_makes_no_llm_call(run, fake_llm):
    llm = fake_llm(router=AssertionError("router must not be called"))
    result = await run("۲۵ درصد از ۸۴۰", llm)
    assert llm.calls == []
    assert result.llm_calls == 0
    assert result.decision is not None and result.decision.route_source == "rule"
    assert result.results["s1"].meta["path"] == "direct"
    assert result.response.strip() != ""
    assert "۲۱۰" in result.response


async def test_request_over_token_limit_makes_no_llm_call(make_settings, fake_llm):
    from skillagent.api import run_agent

    llm = fake_llm(router=AssertionError("router must not be called"))
    settings = make_settings(max_request_tokens=50)
    result = await run_agent("word " * 400, settings=settings, llm=llm)
    assert llm.calls == []
    assert result.llm_calls == 0
    assert result.decision is None
    assert result.response.startswith("Your message is too long")
    assert events(result, "preprocess", "over_limit")


async def test_persian_end_to_end(run, fake_llm, plan, mk_step, calc_call):
    llm = fake_llm(
        router=plan(
            "fa",
            mk_step("s1", "translator", "ترجمهٔ «سلام دنیا» به انگلیسی", target_language="en"),
            mk_step("s2", "calculator", "محاسبهٔ بیست و پنج درصد هشتصد و چهل"),
            mk_step("s3", "general_chat", "یک شعر کوتاه بگو"),
        ),
        translator="Hello world",
        calculator=calc_call("25/100*840", "بیست و پنج درصد هشتصد و چهل"),
    )
    result = await run(
        "«سلام دنیا» را به انگلیسی ترجمه کن، بیست و پنج درصد هشتصد و چهل را حساب کن و یک شعر بگو",
        llm,
    )
    response = result.response
    assert "**ترجمه**\nHello world" in response
    assert "**محاسبه**" in response
    assert "۲۱۰" in response
    assert "توجه: من در هر درخواست حداکثر ۲ کار را انجام می‌دهم" in response
    assert "یک شعر کوتاه بگو" in response
    assert "ي" not in response and "ك" not in response


async def test_persian_failure_notes(run, fake_llm, plan, mk_step):
    llm = fake_llm(
        router=plan("fa", mk_step("s1", "general_chat", "پاسخ به احوال‌پرسی")),
        general_chat=LLMProviderError("down"),
    )
    result = await run("سلام، حالت چطور است؟", llm)
    assert result.response.startswith(APOLOGY)
    assert "مرحلهٔ «پاسخ» با خطا روبه‌رو شد" in result.response
    assert "ي" not in result.response and "ك" not in result.response


async def test_provider_failures_never_raise(run, fake_llm):
    for exc in (LLMProviderError("503 high demand"), LLMRateLimitError("daily quota")):
        llm = fake_llm(router=exc, general_chat=exc)
        result = await run("Hello there", llm)
        assert result.decision is not None and result.decision.route_source == "fallback"
        assert result.results["s1"].status == "error"
        assert result.response.startswith(APOLOGY)


async def test_unexpected_exception_escaping_the_graph_is_degraded(run, fake_llm):
    llm = fake_llm(router=RuntimeError("programming error in a dependency"))
    result = await run("Hello there", llm)
    assert result.response == APOLOGY
    error = events(result, "agent", "error")[0]
    assert "RuntimeError: programming error" in error.data["error"]
    assert events(result, "preprocess", "end")  # trace up to the failure is kept


async def test_config_error_is_raised(make_settings):
    import pytest

    from skillagent.api import run_agent
    from skillagent.core.errors import ConfigError

    settings = make_settings(llm_provider="groq")  # no GROQ_API_KEY in the isolated env
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        await run_agent("Hello", settings=settings)


async def test_context_isolation(run, fake_llm, plan, mk_step):
    seen: list[tuple[SkillInput, SkillContext]] = []

    async def spy(inp: SkillInput, ctx: SkillContext) -> SkillOutput:
        seen.append((inp, ctx))
        return SkillOutput(status="ok", output="spied")

    registry = build_default_registry()
    registry._specs["general_chat"] = dataclasses.replace(registry.get("general_chat"), run=spy)
    rationale = "SECRET-RATIONALE the user wants two things"
    llm = fake_llm(
        router=plan(
            "en",
            mk_step("s1", "translator", "Translate 'owl' to Spanish", target_language="es"),
            mk_step("s2", "general_chat", "Tell me about owls"),
            rationale=rationale,
        ),
        translator="búho",
    )
    prompt = "Translate 'owl' to Spanish and tell me about owls"
    await run(prompt, llm, registry=registry)

    ((inp, ctx),) = seen
    assert type(inp) is SkillInput
    assert inp.model_dump() == {
        "text": prompt,
        "instruction": "Tell me about owls",
        "params": {},
        "response_language": "en",
        "is_chained": False,
    }
    assert set(vars(ctx)) == {"llm", "settings", "prompts"}  # services only, no graph state
    dumped = str(inp.model_dump())
    assert "SECRET-RATIONALE" not in dumped
    assert "Spanish" not in inp.instruction and "búho" not in dumped
