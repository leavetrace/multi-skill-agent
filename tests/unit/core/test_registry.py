from __future__ import annotations

import pytest

from skillagent.core.errors import DuplicateSkillError, UnknownSkillError
from skillagent.core.registry import SkillRegistry
from skillagent.skills.catalog import build_default_registry
from skillagent.testing import make_skill_spec


def test_register_and_get() -> None:
    registry = SkillRegistry()
    spec = make_skill_spec("alpha")
    registry.register(spec)
    assert registry.get("alpha") is spec
    assert registry.get("ALPHA") is spec
    assert len(registry) == 1


def test_duplicate_rejected() -> None:
    registry = SkillRegistry()
    registry.register(make_skill_spec("alpha"))
    with pytest.raises(DuplicateSkillError, match="already registered"):
        registry.register(make_skill_spec("alpha"))


def test_non_canonical_name_rejected() -> None:
    with pytest.raises(ValueError, match="snake_case"):
        SkillRegistry().register(make_skill_spec("General Chat"))


def test_unknown_lists_available() -> None:
    registry = build_default_registry()
    with pytest.raises(UnknownSkillError, match=r"unknown skill 'weather'.*summarizer"):
        registry.get("weather")


def test_resolve_and_contains() -> None:
    registry = build_default_registry()
    assert registry.resolve("General-Chat") == "general_chat"
    assert registry.resolve("weather") is None
    assert "general chat" in registry
    assert "weather" not in registry
    assert 42 not in registry


def test_ordering_by_order_then_name() -> None:
    registry = SkillRegistry()
    for name, order in [("zeta", 1), ("beta", 5), ("alpha", 5), ("omega", 100)]:
        registry.register(make_skill_spec(name, order=order))
    assert registry.names() == ["zeta", "alpha", "beta", "omega"]
    assert [s.name for s in registry.specs()] == registry.names()


def test_default_registry_has_exactly_the_four_product_skills() -> None:
    registry = build_default_registry()
    assert registry.names() == ["summarizer", "translator", "calculator", "general_chat"]
    assert len(registry) == 4


def test_twenty_synthetic_skills_scale_without_code_changes() -> None:
    registry = build_default_registry()
    for i in range(20):
        registry.register(make_skill_spec(f"synthetic_{i:02d}", order=200 + i))
    assert len(registry) == 24
    assert registry.names()[-1] == "synthetic_19"
