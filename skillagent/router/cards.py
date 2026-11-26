"""Router skill cards and few-shot blocks, rendered from `SkillSpec` data only.

Nothing here knows any particular skill: adding a skill to the registry adds its card,
its parameter summary and its examples to the router prompt with no code change.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from typing import Any, get_args

from pydantic import BaseModel, BeforeValidator

from skillagent.core.language import normalize_lang_code
from skillagent.router.examples import PlanExample
from skillagent.skills.base import SkillSpec

__all__ = ["render_cards", "render_examples", "render_params"]

_LANG_DESCRIPTION = 'ISO 639-1 code, e.g. "en", "fa", "de"'
_SKILL_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def render_cards(specs: Iterable[SkillSpec]) -> str:
    """One compact block per skill: description, use / don't-use cues, params, I/O kinds."""
    return "\n\n".join(_render_card(spec) for spec in specs)


def _render_card(spec: SkillSpec) -> str:
    lines = [f"### {spec.name}", spec.description.strip()]
    if spec.when_to_use:
        lines.append("Use when:")
        lines += [f"- {cue.strip()}" for cue in spec.when_to_use]
    if spec.when_not_to_use:
        lines.append("Don't use when:")
        lines += [f"- {cue.strip()}" for cue in spec.when_not_to_use]
    lines.append(f"params: {render_params(spec.params_model)}")
    needs = "yes (a text to work on)" if spec.requires_payload else "no"
    lines.append(
        f"input: {'/'.join(sorted(spec.accepts))} · output: {spec.output_kind} · "
        f"needs content: {needs}"
    )
    return "\n".join(lines)


def render_params(model: type[BaseModel] | None) -> str:
    """Field names and allowed values, read from the params model's JSON schema."""
    if model is None:
        return "none (always {})"
    properties: dict[str, Any] = model.model_json_schema().get("properties", {})
    if not properties:
        return "none (always {})"
    lang_fields = {
        name for name, info in model.model_fields.items() if _is_lang_code(info.annotation)
    }
    parts = [
        f"{name} = {_LANG_DESCRIPTION if name in lang_fields else _describe(schema)}"
        for name, schema in properties.items()
    ]
    return "; ".join(parts) + " (all optional)"


def _is_lang_code(annotation: object) -> bool:
    """Does the annotation contain `LangCode` (recognized by its normalizing validator)?

    The JSON schema loses LangCode's pattern, so we look at the type itself.
    """
    for meta in getattr(annotation, "__metadata__", ()):
        if isinstance(meta, BeforeValidator) and meta.func is normalize_lang_code:
            return True
    return any(_is_lang_code(arg) for arg in get_args(annotation))


def _describe(schema: dict[str, Any]) -> str:
    options = schema.get("anyOf", [schema])
    kinds: list[str] = []
    for option in options:
        if option.get("type") == "null":
            continue
        if "enum" in option:
            kinds.append(" | ".join(json.dumps(v, ensure_ascii=False) for v in option["enum"]))
        elif "const" in option:
            kinds.append(json.dumps(option["const"], ensure_ascii=False))
        else:
            kinds.append(str(option.get("type", "any")))
    return " or ".join(kinds) or "any"


def render_examples(specs: Sequence[SkillSpec], extra: Sequence[PlanExample]) -> str:
    """Router-level JSON examples whose skills are all available, then each card's examples.

    Examples that mention a skill outside `specs` are left out, so the prompt never shows
    the model a skill it cannot choose (Top-K, synthetic registries).
    """
    available = {spec.name for spec in specs}
    blocks: list[str] = []
    for example in extra:
        if example.skills <= available:
            plan = json.dumps(example.plan, ensure_ascii=False, separators=(", ", ": "))
            blocks.append(f"User: {example.prompt}\nJSON: {plan}")
    compact = [
        f"User: {ex.prompt}\nPlan: {ex.plan}"
        for spec in specs
        for ex in spec.examples
        if _plan_skills(ex.plan) <= available
    ]
    if compact:
        blocks.append(
            "Short-form plans from the skill cards (`skill(input_from, params)`; `->` means "
            "the next step takes the previous step's output):\n\n" + "\n\n".join(compact)
        )
    return "\n\n".join(blocks) if blocks else "(no examples)"


def _plan_skills(plan: str) -> set[str]:
    """Skill names in compact notation: `summarizer(user) -> translator(s1, x=y)`."""
    return set(_SKILL_CALL.findall(plan))
