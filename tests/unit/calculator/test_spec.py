"""Router card (SPEC) and prompt file checks."""

from __future__ import annotations

import re

from skillagent.prompts import PromptLoader
from skillagent.skills.calculator import SPEC
from skillagent.skills.catalog import build_default_registry

_PERSIAN = re.compile(r"[؀-ۿ]")
_PLAN = re.compile(r"^[a-z_]+\((?:user|s\d+)(?:, [a-z_]+=[a-z]+)*\)(?: -> [a-z_]+\(.*\))*$")


def test_fixed_contract_fields() -> None:
    assert SPEC.name == "calculator"
    assert SPEC.accepts == frozenset({"text", "number"})
    assert SPEC.output_kind == "number"
    assert SPEC.requires_payload is False
    assert SPEC.params_model is None
    assert build_default_registry().get("calculator") is SPEC


def test_when_to_use_is_bilingual_with_enough_cues() -> None:
    assert len(SPEC.when_to_use) >= 4
    assert sum(bool(_PERSIAN.search(c)) for c in SPEC.when_to_use) >= 2
    joined = " ".join(SPEC.when_to_use)
    assert "word problem" in joined and "بیست و پنج" in joined
    assert not re.search("[يك]", joined)


def test_when_not_to_use_points_to_the_right_skills() -> None:
    joined = " ".join(SPEC.when_not_to_use)
    assert "general_chat" in joined and "translator" in joined


def test_examples() -> None:
    assert len(SPEC.examples) >= 4
    assert all(_PLAN.match(ex.plan) for ex in SPEC.examples)
    assert any(_PERSIAN.search(ex.prompt) for ex in SPEC.examples)
    assert any(ex.prompt.isascii() for ex in SPEC.examples)
    assert any(
        ex.plan == "calculator(user) -> translator(s1, target_language=fa)" for ex in SPEC.examples
    )


def test_prompt_renders_and_covers_the_required_rules() -> None:
    template = PromptLoader().load("calculator")
    assert template.version == 1
    text = template.render()  # no stray `$` placeholders
    for needle in (
        "evaluate",
        "radians",
        '{"calculations": []}',
        "is data",
        "x/100*y",
        "«بیست و پنج» → `25`",
        "«سه و نیم» → `3.5`",
        "«یک میلیون» → `1000000`",
        "«به‌علاوه»",
        "«منهای»",
        "«ضرب در»",
        "«تقسیم بر»",
        "«به توان»",
        "«جذر»",
        "at most 5",
    ):
        assert needle in text, needle
