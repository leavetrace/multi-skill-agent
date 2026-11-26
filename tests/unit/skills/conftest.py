"""Fixtures for the text skills: FakeLLM-backed contexts, inputs and sent-message access.

Tests here run with `--import-mode=importlib` and no packages, so shared helpers are
fixtures rather than importable functions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from skillagent.config import Settings
from skillagent.core.types import SkillInput
from skillagent.llm.types import LLMResponse
from skillagent.prompts import PromptLoader
from skillagent.skills.base import SkillContext
from skillagent.testing import FakeLLM, FakeRule


class LengthLimitedLLM(FakeLLM):
    """FakeLLM whose replies report `finish_reason="length"` (FakeLLM always says "stop")."""

    async def complete(self, messages, **kwargs: Any) -> LLMResponse:  # type: ignore[override]
        response = await super().complete(messages, **kwargs)
        return response.model_copy(update={"finish_reason": "length"})


@pytest.fixture
def ctx_for() -> Callable[[FakeLLM], SkillContext]:
    def factory(llm: FakeLLM) -> SkillContext:
        settings = Settings(llm_provider="google", google_api_key="AIza-test-0000", llm_rpm=0)
        return SkillContext(llm=llm, settings=settings, prompts=PromptLoader())

    return factory


@pytest.fixture
def fake() -> Callable[..., FakeLLM]:
    """`fake("reply", truncated=False)` → a FakeLLM answering every call with that text."""

    def factory(reply: str = "ok", *, truncated: bool = False) -> FakeLLM:
        cls = LengthLimitedLLM if truncated else FakeLLM
        return cls([FakeRule(match=lambda m, p: True, reply=reply)])

    return factory


@pytest.fixture
def make_input() -> Callable[..., SkillInput]:
    def factory(
        text: str,
        *,
        instruction: str = "Process the provided text",
        params: dict[str, Any] | None = None,
        lang: str = "en",
        chained: bool = False,
    ) -> SkillInput:
        return SkillInput(
            text=text,
            instruction=instruction,
            params=params or {},
            response_language=lang,
            is_chained=chained,
        )

    return factory


@pytest.fixture
def sent() -> Callable[[FakeLLM], tuple[str, str]]:
    """`sent(llm)` → (system, user) contents of the last call."""

    def read(llm: FakeLLM) -> tuple[str, str]:
        messages = llm.calls[-1].messages
        by_role = {m.get("role"): m.get("content", "") for m in messages}
        return by_role["system"], by_role["user"]

    return read
