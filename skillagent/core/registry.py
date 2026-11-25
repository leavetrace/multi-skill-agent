"""Skill registry: the single source of truth for which skills exist (CONTRACTS §3).

Router cards, the routing enum and the graph's skill nodes are all generated from this,
so adding a skill means registering one `SkillSpec` and changing nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from skillagent.core.errors import DuplicateSkillError, UnknownSkillError
from skillagent.core.types import canonical_skill_name

if TYPE_CHECKING:
    from skillagent.skills.base import SkillSpec

__all__ = ["SkillRegistry"]


class SkillRegistry:
    """Name → `SkillSpec` map with canonicalizing lookup and deterministic ordering."""

    def __init__(self) -> None:
        self._specs: dict[str, SkillSpec] = {}

    def register(self, spec: SkillSpec) -> None:
        """Add a spec. Its name must already be canonical snake_case so lookups are stable."""
        if canonical_skill_name(spec.name) != spec.name:
            raise ValueError(
                f"skill name {spec.name!r} must be snake_case "
                f"(did you mean {canonical_skill_name(spec.name)!r}?)"
            )
        if spec.name in self._specs:
            raise DuplicateSkillError(f"skill {spec.name!r} is already registered")
        self._specs[spec.name] = spec

    def resolve(self, name: str) -> str | None:
        """Canonical registered name for `name`, or None if no such skill."""
        canonical = canonical_skill_name(name)
        return canonical if canonical in self._specs else None

    def get(self, name: str) -> SkillSpec:
        resolved = self.resolve(name)
        if resolved is None:
            raise UnknownSkillError(f"unknown skill {name!r}; registered skills: {self.names()}")
        return self._specs[resolved]

    def specs(self) -> list[SkillSpec]:
        """Specs sorted by (order, name): the order router cards are rendered in."""
        return sorted(self._specs.values(), key=lambda s: (s.order, s.name))

    def names(self) -> list[str]:
        return [spec.name for spec in self.specs()]

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.resolve(name) is not None

    def __len__(self) -> int:
        return len(self._specs)
