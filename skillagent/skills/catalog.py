"""The product catalog: exactly the four shipped skills (ADR-013).

Imports are explicit rather than auto-discovered: one obvious place to read what ships,
and tests can build registries with synthetic skills without any plugin magic.
"""

from __future__ import annotations

from skillagent.core.registry import SkillRegistry
from skillagent.skills import general_chat, summarizer, translator
from skillagent.skills.calculator import SPEC as CALCULATOR_SPEC

__all__ = ["build_default_registry"]


def build_default_registry() -> SkillRegistry:
    registry = SkillRegistry()
    for spec in (summarizer.SPEC, translator.SPEC, CALCULATOR_SPEC, general_chat.SPEC):
        registry.register(spec)
    return registry
