from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from skillagent.core.registry import SkillRegistry
from skillagent.core.types import (
    PlanStep,
    RoutingDecision,
    SkillInput,
    SkillOutput,
    SkillResult,
    StepTask,
    TraceEvent,
    UserRequest,
    canonical_skill_name,
)
from skillagent.skills.catalog import build_default_registry


def decision(steps: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"response_language": "en", "steps": steps, **extra}


def step(i: int, skill: str, input_from: str = "user", **extra: Any) -> dict[str, Any]:
    return {
        "id": f"s{i}",
        "skill": skill,
        "instruction": f"do {skill}",
        "input_from": input_from,
        **extra,
    }


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {"registry": build_default_registry(), "max_skills": 2}


class TestCanonicalName:
    @pytest.mark.parametrize(
        "raw", ["general_chat", "General Chat", "general-chat", " GENERAL_CHAT ", "General  Chat"]
    )
    def test_variants(self, raw: str) -> None:
        assert canonical_skill_name(raw) == "general_chat"

    def test_plan_step_canonicalizes_without_registry(self) -> None:
        assert PlanStep.model_validate(step(1, "General-Chat")).skill == "general_chat"


class TestLangCodeField:
    @pytest.mark.parametrize(("raw", "code"), [("Persian", "fa"), ("فارسی", "fa"), ("EN", "en")])
    def test_normalized(self, raw: str, code: str) -> None:
        assert (
            RoutingDecision.model_validate(
                decision([step(1, "translator")], response_language=raw)
            ).response_language
            == code
        )

    def test_unknown_language_is_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="unknown language"):
            RoutingDecision.model_validate(
                decision([step(1, "translator")], response_language="Elvish")
            )

    def test_skill_input_language(self) -> None:
        inp = SkillInput(text="t", instruction="i", response_language="Farsi")
        assert inp.response_language == "fa"


class TestPlanStepFields:
    @pytest.mark.parametrize("bad_id", ["s0", "1", "step1", "S1", "s01"])
    def test_id_pattern(self, bad_id: str) -> None:
        with pytest.raises(ValidationError):
            PlanStep(id=bad_id, skill="x", instruction="y")

    def test_instruction_length(self) -> None:
        with pytest.raises(ValidationError):
            PlanStep(id="s1", skill="x", instruction="")
        with pytest.raises(ValidationError):
            PlanStep(id="s1", skill="x", instruction="a" * 301)

    def test_extra_keys_ignored(self) -> None:
        assert not hasattr(PlanStep.model_validate({**step(1, "x"), "foo": 1}), "foo")


class TestV1Clarification:
    def test_question_required(self) -> None:
        with pytest.raises(ValidationError, match="clarification_question"):
            RoutingDecision.model_validate(decision([], needs_clarification=True))
        with pytest.raises(ValidationError, match="clarification_question"):
            RoutingDecision.model_validate(
                decision([], needs_clarification=True, clarification_question="  ")
            )

    def test_steps_cleared(self) -> None:
        d = RoutingDecision.model_validate(
            decision(
                [step(1, "translator")],
                needs_clarification=True,
                clarification_question="Which text?",
            )
        )
        assert d.steps == []
        assert d.clarification_question == "Which text?"


class TestV2NonEmpty:
    def test_steps_required_without_clarification(self) -> None:
        with pytest.raises(ValidationError, match="at least one step"):
            RoutingDecision.model_validate(decision([]))

    def test_single_step_ok(self) -> None:
        assert len(RoutingDecision.model_validate(decision([step(1, "calculator")])).steps) == 1


class TestV3UniqueIds:
    def test_duplicate_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"steps\[1\]\.id='s1' is duplicated"):
            RoutingDecision.model_validate(decision([step(1, "a"), step(1, "b")]))


class TestV4InputFrom:
    def test_earlier_reference_ok(self) -> None:
        d = RoutingDecision.model_validate(decision([step(1, "a"), step(2, "b", "s1")]))
        assert d.steps[1].input_from == "s1"

    def test_forward_reference_rejected(self) -> None:
        with pytest.raises(
            ValidationError,
            match=r"steps\[0\]\.input_from='s2' must reference an earlier step id or 'user'",
        ):
            RoutingDecision.model_validate(decision([step(1, "a", "s2"), step(2, "b")]))

    def test_self_reference_rejected(self) -> None:
        with pytest.raises(ValidationError, match="earlier step"):
            RoutingDecision.model_validate(decision([step(1, "a", "s1")]))

    def test_unknown_reference_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"steps\[1\]\.input_from='s3'"):
            RoutingDecision.model_validate(decision([step(1, "a"), step(2, "b", "s3")]))


class TestV5SkillResolution:
    def test_resolves_variants(self, ctx: dict[str, Any]) -> None:
        d = RoutingDecision.model_validate(decision([step(1, "General Chat")]), context=ctx)
        assert d.steps[0].skill == "general_chat"

    def test_unknown_skill(self, ctx: dict[str, Any]) -> None:
        with pytest.raises(
            ValidationError, match=r"steps\[0\]\.skill='weather' is not a known skill"
        ):
            RoutingDecision.model_validate(decision([step(1, "weather")]), context=ctx)

    def test_unknown_skill_allowed_without_registry(self) -> None:
        assert (
            RoutingDecision.model_validate(decision([step(1, "weather")])).steps[0].skill
            == "weather"
        )


class TestV6IOKinds:
    def test_calculator_output_into_summarizer_rejected(self, ctx: dict[str, Any]) -> None:
        with pytest.raises(ValidationError, match="calculator outputs 'number'"):
            RoutingDecision.model_validate(
                decision([step(1, "calculator"), step(2, "summarizer", "s1")]), context=ctx
            )

    def test_calculator_output_into_translator_ok(self, ctx: dict[str, Any]) -> None:
        d = RoutingDecision.model_validate(
            decision([step(1, "calculator"), step(2, "translator", "s1")]), context=ctx
        )
        assert [s.skill for s in d.steps] == ["calculator", "translator"]

    def test_summarize_then_translate_ok(self, ctx: dict[str, Any]) -> None:
        d = RoutingDecision.model_validate(
            decision([step(1, "summarizer"), step(2, "translator", "s1")]), context=ctx
        )
        assert d.steps[1].input_from == "s1"


class TestV7Params:
    def test_params_normalized_and_none_dropped(self, ctx: dict[str, Any]) -> None:
        d = RoutingDecision.model_validate(
            decision([step(1, "translator", params={"target_language": "Persian", "x": 1})]),
            context=ctx,
        )
        assert d.steps[0].params == {"target_language": "fa"}

    def test_invalid_params(self, ctx: dict[str, Any]) -> None:
        with pytest.raises(
            ValidationError, match=r"steps\[0\]\.params invalid for summarizer: length"
        ):
            RoutingDecision.model_validate(
                decision([step(1, "summarizer", params={"length": "huge"})]), context=ctx
            )

    def test_skill_without_params_model_keeps_params(self, ctx: dict[str, Any]) -> None:
        d = RoutingDecision.model_validate(
            decision([step(1, "calculator", params={"k": 1})]), context=ctx
        )
        assert d.steps[0].params == {"k": 1}


class TestV8MaxSkills:
    def test_extra_steps_dropped_into_dropped_intents(self, ctx: dict[str, Any]) -> None:
        steps = [step(1, "translator"), step(2, "calculator"), step(3, "general_chat")]
        d = RoutingDecision.model_validate(
            decision(steps, dropped_intents=["earlier"]), context=ctx
        )
        assert [s.id for s in d.steps] == ["s1", "s2"]
        assert d.dropped_intents == ["earlier", "do general_chat"]

    def test_dropped_steps_are_not_validated(self, ctx: dict[str, Any]) -> None:
        steps = [step(1, "translator"), step(2, "calculator"), step(3, "no_such_skill", "s9")]
        d = RoutingDecision.model_validate(decision(steps), context=ctx)
        assert len(d.steps) == 2

    def test_not_applied_without_context(self) -> None:
        steps = [step(i, "general_chat") for i in range(1, 4)]
        assert len(RoutingDecision.model_validate(decision(steps)).steps) == 3


class TestErrorsAggregated:
    def test_all_problems_reported_at_once(self, ctx: dict[str, Any]) -> None:
        steps = [step(1, "weather"), step(2, "summarizer", params={"format": "table"})]
        with pytest.raises(ValidationError) as info:
            RoutingDecision.model_validate(decision(steps), context=ctx)
        message = str(info.value)
        assert "weather" in message and "format" in message


class TestOtherModels:
    def test_defaults(self) -> None:
        d = RoutingDecision.model_validate(decision([step(1, "calculator")]))
        assert (d.confidence, d.rationale, d.route_source, d.dropped_intents) == (
            0.5,
            "",
            "llm",
            [],
        )

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            RoutingDecision.model_validate(decision([step(1, "a")], confidence=1.5))

    def test_user_request_frozen(self) -> None:
        req = UserRequest(raw_text="x", normalized_text="x", lang_hint="en", approx_tokens=1)
        with pytest.raises(ValidationError):
            req.raw_text = "y"  # type: ignore[misc]

    def test_round_trip_models(self) -> None:
        task = StepTask(
            step=PlanStep(id="s1", skill="translator", instruction="translate"),
            skill_input=SkillInput(text="hi", instruction="translate", response_language="fa"),
            deadline_monotonic=123.0,
        )
        assert StepTask.model_validate_json(task.model_dump_json()) == task
        assert SkillOutput(status="ok", output="x").output_kind == "text"
        assert SkillResult(step_id="s1", skill="calculator", status="skipped").output == ""
        assert TraceEvent(node="router", event="start", t_ms=0.0).data == {}


class TestCustomRegistry:
    def test_validator_uses_given_registry(self) -> None:
        from skillagent.testing import make_skill_spec

        class P(BaseModel):
            n: int

        registry = SkillRegistry()
        registry.register(make_skill_spec("numbers", output_kind="number"))
        registry.register(make_skill_spec("texty", accepts=frozenset({"text"}), params_model=P))
        ok = RoutingDecision.model_validate(
            decision([step(1, "texty", params={"n": "3"})]), context={"registry": registry}
        )
        assert ok.steps[0].params == {"n": 3}
        with pytest.raises(ValidationError, match="texty accepts \\['text'\\]"):
            RoutingDecision.model_validate(
                decision([step(1, "numbers"), step(2, "texty", "s1", params={"n": 1})]),
                context={"registry": registry},
            )


def test_long_rationale_is_truncated_not_rejected() -> None:
    from skillagent.core.types import RATIONALE_MAX_CHARS

    decision = RoutingDecision.model_validate(
        {
            "response_language": "en",
            "steps": [{"id": "s1", "skill": "general_chat", "instruction": "chat"}],
            "rationale": "x" * 1000,
        }
    )
    assert len(decision.rationale) == RATIONALE_MAX_CHARS
    assert decision.rationale.endswith("…")
