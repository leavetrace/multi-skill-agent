"""Skill specification types (CONTRACTS §2).

A `SkillSpec` is pure data plus one async runner. Keeping specs declarative is what lets
the router cards, plan validation (accepts/output_kind, params_model) and graph nodes be
generated from the registry instead of hand-wired per skill.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from skillagent.core.types import IOKind, SkillInput, SkillOutput

if TYPE_CHECKING:
    from skillagent.config import Settings
    from skillagent.llm.types import LLMClient
    from skillagent.prompts import PromptLoader

__all__ = ["RouterExample", "SkillBudget", "SkillContext", "SkillRunner", "SkillSpec"]


class SkillBudget(BaseModel):
    max_input_tokens: int
    max_output_tokens: int
    timeout_s: float
    temperature: float


class RouterExample(BaseModel):
    prompt: str
    plan: str  # compact notation, e.g. 'summarizer(user) -> translator(s1, target_language=fa)'


@dataclass(frozen=True)
class SkillContext:
    """Shared services handed to a runner; deliberately no graph state (context isolation)."""

    llm: LLMClient
    settings: Settings
    prompts: PromptLoader


SkillRunner = Callable[[SkillInput, SkillContext], Awaitable[SkillOutput]]
"""Runners raise on failure (the graph wrapper maps exceptions to error/timeout)."""


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    when_to_use: tuple[str, ...]
    when_not_to_use: tuple[str, ...]
    examples: tuple[RouterExample, ...]
    params_model: type[BaseModel] | None
    accepts: frozenset[IOKind]
    output_kind: IOKind
    requires_payload: bool
    budget: SkillBudget
    run: SkillRunner
    order: int = 100
