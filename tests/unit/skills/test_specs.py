"""Router cards of the three text skills: enough bilingual cues and well-formed examples."""

from __future__ import annotations

import re

import pytest

from skillagent.skills.catalog import build_default_registry

TEXT_SKILLS = ("summarizer", "translator", "general_chat")
_STEP = re.compile(r"^([a-z_]+)\((user|s[1-9])(?:, [a-z_]+=[a-z]+)*\)$")


def _has_persian(s: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in s)


@pytest.mark.parametrize("name", TEXT_SKILLS)
def test_card_richness(name: str) -> None:
    spec = build_default_registry().get(name)
    assert len(spec.when_to_use) >= 4
    assert sum(_has_persian(c) for c in spec.when_to_use) >= 2
    assert sum(not _has_persian(c) for c in spec.when_to_use) >= 2
    assert len(spec.when_not_to_use) >= 3
    assert len(spec.examples) >= 4
    for text in (spec.description, *spec.when_to_use, *spec.when_not_to_use):
        assert "ي" not in text and "ك" not in text


@pytest.mark.parametrize("name", TEXT_SKILLS)
def test_examples_use_plan_notation(name: str) -> None:
    registry = build_default_registry()
    spec = registry.get(name)
    plans = [e.plan for e in spec.examples]
    assert any("->" in p for p in plans), "needs a chained example"
    assert any(" + " in p for p in plans), "needs a parallel example"
    for plan in plans:
        for step in re.split(r" -> | \+ ", plan):
            m = _STEP.match(step)
            assert m, step
            assert m.group(1) in registry
        assert name in plan
