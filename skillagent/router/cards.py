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
from skillagent.router.examples import LEGEND, PlanExample
from skillagent.skills.base import SkillSpec

__all__ = [
    "MAX_DONT_CUES",
    "MAX_USE_CUES",
    "render_cards",
    "render_examples",
    "render_params",
    "select_cues",
]

MAX_USE_CUES = 3
MAX_DONT_CUES = 2
_LANG_DESCRIPTION = "ISO 639-1 code"
_SKILL_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def render_cards(specs: Iterable[SkillSpec]) -> str:
    """One compact block per skill: description, capped use / don't-use cues, params."""
    return "\n\n".join(_render_card(spec) for spec in specs)


def _render_card(spec: SkillSpec) -> str:
    header = f"### {spec.name}" + (" (needs text)" if spec.requires_payload else "")
    lines = [header, spec.description.strip()]
    if use := select_cues(spec.when_to_use, MAX_USE_CUES):
        lines.append("Use: " + " | ".join(use))
    if dont := select_cues(spec.when_not_to_use, MAX_DONT_CUES):
        lines.append("Don't use: " + " | ".join(dont))
    lines.append(f"Params: {render_params(spec.params_model)}")
    return "\n".join(lines)


def select_cues(cues: Sequence[str], cap: int) -> list[str]:
    """The first `cap` cues in SPEC order, keeping both scripts when the SPEC has both.

    SPEC authors list the most decisive cues first, so a prefix keeps them; if the prefix
    is all-Latin (or all-Persian), the last slot goes to the first cue of the other script
    so Persian and English requests both have a matching example on the card.
    """
    cleaned = [c.strip() for c in cues if c.strip()]
    picked = cleaned[:cap]
    for wants_persian in (True, False):
        if picked and not any(_is_persian(c) == wants_persian for c in picked):
            other = next((c for c in cleaned[cap:] if _is_persian(c) == wants_persian), None)
            if other is not None and len(picked) > 1:
                picked[-1] = other
    return picked


def _is_persian(cue: str) -> bool:
    """Mostly Arabic-script letters (a Latin cue quoting «…» Persian still counts as Latin)."""
    letters = [ch for ch in cue if ch.isalpha()]
    arabic = sum("\u0600" <= ch <= "\u06ff" for ch in letters)
    return bool(letters) and arabic * 2 > len(letters)


def render_params(model: type[BaseModel] | None) -> str:
    """Field names and allowed values, read from the params model's JSON schema."""
    if model is None:
        return "none"
    properties: dict[str, Any] = model.model_json_schema().get("properties", {})
    if not properties:
        return "none"
    lang_fields = {
        name for name, info in model.model_fields.items() if _is_lang_code(info.annotation)
    }
    parts = [
        f"{name} = {_LANG_DESCRIPTION if name in lang_fields else _describe(schema)}"
        for name, schema in properties.items()
    ]
    return "; ".join(parts)


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
    """Router-level examples whose skills are all available: the first as full JSON (so the
    schema stays concrete), the rest in compact plan notation. Then one SPEC example for
    each skill no router-level example shows, so a newly registered skill still gets one.

    Examples that mention a skill outside `specs` are left out, so the prompt never shows
    the model a skill it cannot choose (Top-K, synthetic registries).
    """
    available = {spec.name for spec in specs}
    usable = [ex for ex in extra if ex.skills <= available]
    blocks: list[str] = []
    if usable:
        first = json.dumps(usable[0].plan, ensure_ascii=False, separators=(", ", ": "))
        blocks.append(f"User: {usable[0].prompt}\nJSON: {first}")
    shown = set().union(*(ex.skills for ex in usable)) if usable else set()
    compact = [f"User: {ex.prompt}\n→ {ex.compact()}" for ex in usable[1:]]
    for spec in specs:
        if spec.name in shown:
            continue
        ex = next((e for e in spec.examples if _plan_skills(e.plan) <= available), None)
        if ex is not None:
            compact.append(f"User: {ex.prompt}\n→ {ex.plan}")
    if compact:
        blocks.append(f"Short form ({LEGEND}):\n\n" + "\n\n".join(compact))
    return "\n\n".join(blocks) if blocks else "(no examples)"


def _plan_skills(plan: str) -> set[str]:
    """Skill names in compact notation: `summarizer(user) -> translator(s1, x=y)`."""
    return set(_SKILL_CALL.findall(plan))
