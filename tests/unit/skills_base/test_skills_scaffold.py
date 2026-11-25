from __future__ import annotations

import dataclasses

import pytest
from pydantic import ValidationError

from skillagent.config import Settings
from skillagent.core.types import SkillInput
from skillagent.prompts import PromptLoader
from skillagent.skills.base import SkillBudget, SkillContext
from skillagent.skills.catalog import build_default_registry
from skillagent.skills.params import SummarizerParams, TranslatorParams
from skillagent.testing import FakeLLM

# Fixed by CONTRACTS §2 (owners may refine text, never these fields).
EXPECTED = {
    "summarizer": ({"text"}, "text", True, SummarizerParams, (4000, 700, 30, 0.3)),
    "translator": ({"text", "number"}, "text", True, TranslatorParams, (4000, 1500, 30, 0.2)),
    "calculator": ({"text", "number"}, "number", False, None, (800, 300, 20, 0.0)),
    "general_chat": ({"text", "number"}, "text", False, None, (1500, 600, 25, 0.7)),
}


@pytest.mark.parametrize("name", list(EXPECTED))
def test_contract_fields(name: str) -> None:
    spec = build_default_registry().get(name)
    accepts, output_kind, requires_payload, params_model, budget = EXPECTED[name]
    assert spec.accepts == frozenset(accepts)
    assert spec.output_kind == output_kind
    assert spec.requires_payload is requires_payload
    assert spec.params_model is params_model
    b = spec.budget
    assert (b.max_input_tokens, b.max_output_tokens, b.timeout_s, b.temperature) == budget


@pytest.mark.parametrize("name", list(EXPECTED))
def test_cards_are_bilingual(name: str) -> None:
    spec = build_default_registry().get(name)
    assert spec.description and len(spec.when_to_use) >= 2
    assert any(any("؀" <= ch <= "ۿ" for ch in cue) for cue in spec.when_to_use)
    assert any(cue.isascii() for cue in spec.when_to_use)
    for cue in spec.when_to_use:
        assert "ي" not in cue and "ك" not in cue  # Persian letters, not Arabic


@pytest.mark.parametrize("name", list(EXPECTED))
async def test_stub_runner(name: str) -> None:
    spec = build_default_registry().get(name)
    ctx = SkillContext(llm=FakeLLM([]), settings=Settings(), prompts=PromptLoader())
    out = await spec.run(SkillInput(text="x", instruction="do it", response_language="en"), ctx)
    assert out.status == "ok"
    assert out.output == f"[stub:{name}] do it"


def test_spec_is_frozen() -> None:
    spec = build_default_registry().get("calculator")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "other"  # type: ignore[misc]


def test_params_models() -> None:
    assert TranslatorParams.model_validate({"target_language": "انگلیسی", "junk": 1}).model_dump(
        exclude_none=True
    ) == {"target_language": "en"}
    assert SummarizerParams(format="bullets").output_language is None
    with pytest.raises(ValidationError):
        SummarizerParams.model_validate({"length": "tiny"})


def test_budget_model() -> None:
    assert (
        SkillBudget(max_input_tokens=1, max_output_tokens=1, timeout_s=1, temperature=0).timeout_s
        == 1
    )
