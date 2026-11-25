"""Core data types shared by router, scheduler and skills (CONTRACTS §1).

`RoutingDecision` carries the plan validation rules V1–V8 so that *every* producer of a
plan (LLM router, fast-path rule, fallback) goes through the same checks, and the router's
repair loop can feed the exact error text back to the model.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from skillagent.core.language import normalize_lang_code

if TYPE_CHECKING:
    from skillagent.core.registry import SkillRegistry

__all__ = [
    "SKILL_NAMES",
    "IOKind",
    "LangCode",
    "LangHint",
    "PlanStep",
    "RoutingDecision",
    "SkillInput",
    "SkillOutput",
    "SkillResult",
    "StepTask",
    "TraceEvent",
    "UserRequest",
    "canonical_skill_name",
]

LangHint = Literal["fa", "en", "mixed", "unknown"]
IOKind = Literal["text", "number"]

LangCode = Annotated[str, BeforeValidator(normalize_lang_code), Field(pattern=r"^[a-z]{2,3}$")]

SKILL_NAMES = ("summarizer", "translator", "calculator", "general_chat")


def canonical_skill_name(name: str) -> str:
    """`"General Chat"`, `"general-chat"`, `" GENERAL_CHAT "` → `"general_chat"`.

    LLMs paraphrase identifiers; canonicalizing is cheaper than a repair round-trip.
    """
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


class UserRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_text: str
    normalized_text: str
    lang_hint: LangHint
    approx_tokens: int


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^s[1-9][0-9]*$")
    skill: str
    instruction: str = Field(min_length=1, max_length=300)
    input_from: str = "user"
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("skill")
    @classmethod
    def _canonicalize_skill(cls, value: str) -> str:
        return canonical_skill_name(value)


class RoutingDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    response_language: LangCode
    steps: list[PlanStep] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    dropped_intents: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=300)
    route_source: Literal["llm", "rule", "fallback"] = "llm"

    @model_validator(mode="after")
    def _validate_plan(self, info: ValidationInfo) -> RoutingDecision:
        """Apply V1–V8 (CONTRACTS §1.1).

        Order: V1/V2 (shape), V8 (truncate to max_skills), then V3–V7 on the kept steps only,
        so a plan is never sent back for repair because of a step we would drop anyway.
        All problems are reported together so one repair can fix them all.
        """
        context = info.context or {}
        if self.needs_clarification:  # V1
            if not (self.clarification_question or "").strip():
                raise ValueError(
                    "needs_clarification=true requires a non-empty clarification_question"
                )
            self.steps = []
            return self
        if not self.steps:  # V2
            raise ValueError("steps must contain at least one step when needs_clarification=false")

        max_skills = context.get("max_skills")
        if max_skills is not None and len(self.steps) > max_skills:  # V8
            self.dropped_intents.extend(step.instruction for step in self.steps[max_skills:])
            self.steps = self.steps[:max_skills]

        errors = _structural_errors(self.steps)  # V3, V4
        registry = context.get("registry")
        if registry is not None and not errors:
            errors = _registry_errors(self.steps, registry)  # V5–V7
        if errors:
            raise ValueError("; ".join(errors))
        return self


def _structural_errors(steps: list[PlanStep]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for i, step in enumerate(steps):
        if step.id in seen:  # V3
            errors.append(f"steps[{i}].id={step.id!r} is duplicated; step ids must be unique")
        if step.input_from != "user" and step.input_from not in seen:  # V4
            errors.append(
                f"steps[{i}].input_from={step.input_from!r} must reference an earlier step id "
                "or 'user'"
            )
        seen.add(step.id)
    return errors


def _registry_errors(steps: list[PlanStep], registry: SkillRegistry) -> list[str]:
    errors: list[str] = []
    by_id: dict[str, PlanStep] = {}
    for i, step in enumerate(steps):
        by_id[step.id] = step
        resolved = registry.resolve(step.skill)
        if resolved is None:  # V5
            errors.append(
                f"steps[{i}].skill={step.skill!r} is not a known skill; "
                f"choose one of {registry.names()}"
            )
            continue
        step.skill = resolved
        spec = registry.get(resolved)
        source = by_id.get(step.input_from)
        if source is not None and registry.resolve(source.skill) is not None:  # V6
            source_kind = registry.get(source.skill).output_kind
            if source_kind not in spec.accepts:
                errors.append(
                    f"steps[{i}] ({resolved}) cannot take input from {source.id!r}: "
                    f"{source.skill} outputs {source_kind!r} but {resolved} accepts "
                    f"{sorted(spec.accepts)}"
                )
        if spec.params_model is not None:  # V7
            try:
                parsed = spec.params_model.model_validate(step.params)
            except ValidationError as exc:
                details = ", ".join(
                    f"{'.'.join(str(p) for p in e['loc']) or 'params'}: {e['msg']}"
                    for e in exc.errors()
                )
                errors.append(f"steps[{i}].params invalid for {resolved}: {details}")
                continue
            step.params = parsed.model_dump(exclude_none=True)
    return errors


class SkillInput(BaseModel):
    text: str
    instruction: str
    params: dict[str, Any] = Field(default_factory=dict)
    response_language: LangCode
    is_chained: bool = False


class SkillOutput(BaseModel):
    status: Literal["ok", "rejected"]
    output: str
    output_kind: IOKind = "text"
    meta: dict[str, Any] = Field(default_factory=dict)


class SkillResult(BaseModel):
    step_id: str
    skill: str
    status: Literal["ok", "rejected", "error", "timeout", "skipped"]
    output: str = ""
    output_kind: IOKind = "text"
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class StepTask(BaseModel):
    step: PlanStep
    skill_input: SkillInput
    deadline_monotonic: float


class TraceEvent(BaseModel):
    node: str
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    t_ms: float
