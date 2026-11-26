"""Candidate selection: which skill cards the router prompt shows (ADR-008).

Below the threshold every skill is shown (`AllSkills`): at small N, Top-K could only lose
recall. Above it, `BM25TopK` keeps the prompt bounded. BM25 is pure Python over curated
bilingual cues, so it needs no embedding provider and costs no quota.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Protocol, runtime_checkable

from skillagent.core.language import ZWNJ, normalize_persian
from skillagent.core.registry import SkillRegistry
from skillagent.core.types import UserRequest
from skillagent.skills.base import SkillSpec

__all__ = ["FALLBACK_SKILL", "AllSkills", "BM25TopK", "CandidateSelector", "tokenize"]

FALLBACK_SKILL = "general_chat"  # CONTRACTS §11: always a candidate

_SPLIT = re.compile(r"[^\w]+|_")


@runtime_checkable
class CandidateSelector(Protocol):
    def select(self, request: UserRequest, registry: SkillRegistry) -> list[str]: ...


class AllSkills:
    """Every registered skill, in registry (card) order."""

    def select(self, request: UserRequest, registry: SkillRegistry) -> list[str]:
        return registry.names()


def tokenize(text: str) -> list[str]:
    """normalize_persian → lowercase → drop ZWNJ → split on non-letters/digits → len ≥ 2.

    ZWNJ is removed (not split on) so «می‌شود» and «میشود» become the same token.
    """
    text = normalize_persian(text).lower().replace(ZWNJ, "")
    return [tok for tok in _SPLIT.split(text) if len(tok) > 1]


def _document(spec: SkillSpec) -> list[str]:
    parts = [spec.name, spec.description, *spec.when_to_use, *(ex.prompt for ex in spec.examples)]
    return tokenize(" ".join(parts))


class BM25TopK:
    """Okapi BM25 over each skill's name, description, cues and example prompts.

    The top `k` by score, plus `general_chat` and any skill named literally in the prompt
    ("use the weather_lookup skill"). Results keep registry order so the prompt is stable.
    """

    def __init__(self, k: int, *, k1: float = 1.5, b: float = 0.75) -> None:
        if k < 1:
            raise ValueError("k must be >= 1")
        self.k, self.k1, self.b = k, k1, b
        self._index_key: tuple[str, ...] | None = None
        self._docs: dict[str, Counter[str]] = {}
        self._lengths: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._avg_len = 1.0

    def scores(self, query: str, registry: SkillRegistry) -> dict[str, float]:
        self._ensure_index(registry)
        terms = tokenize(query)
        result: dict[str, float] = {}
        for name, tf in self._docs.items():
            norm = self.k1 * (1 - self.b + self.b * self._lengths[name] / self._avg_len)
            result[name] = sum(
                self._idf.get(t, 0.0) * tf[t] * (self.k1 + 1) / (tf[t] + norm)
                for t in terms
                if t in tf
            )
        return result

    def select(self, request: UserRequest, registry: SkillRegistry) -> list[str]:
        scores = self.scores(request.normalized_text, registry)
        order = {name: i for i, name in enumerate(registry.names())}
        ranked = sorted(scores, key=lambda n: (-scores[n], order[n]))
        chosen = set(ranked[: self.k])
        if FALLBACK_SKILL in registry:
            chosen.add(FALLBACK_SKILL)
        lowered = request.normalized_text.lower()
        chosen |= {n for n in registry.names() if n in lowered or n.replace("_", " ") in lowered}
        return [n for n in registry.names() if n in chosen]

    def _ensure_index(self, registry: SkillRegistry) -> None:
        key = tuple(registry.names())
        if key == self._index_key:
            return
        docs = {spec.name: _document(spec) for spec in registry.specs()}
        self._docs = {name: Counter(tokens) for name, tokens in docs.items()}
        self._lengths = {name: len(tokens) for name, tokens in docs.items()}
        self._avg_len = max(1.0, sum(self._lengths.values()) / max(1, len(docs)))
        n = len(docs)
        df = Counter(t for tf in self._docs.values() for t in tf)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self._index_key = key
