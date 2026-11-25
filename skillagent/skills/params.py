"""Typed parameters the router may attach to a step (CONTRACTS §1.3).

Validated by rule V7, which also strips `None` values, so skills only see keys the model
actually set.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from skillagent.core.types import LangCode

__all__ = ["SummarizerParams", "TranslatorParams"]


class TranslatorParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target_language: LangCode | None = None  # None ⇒ default rule: source fa → en, else → fa
    source_language: LangCode | None = None


class SummarizerParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    length: Literal["short", "medium", "long"] | None = None
    format: Literal["paragraph", "bullets"] | None = None
    output_language: LangCode | None = None  # None ⇒ SkillInput.response_language
