"""Evaluation case schema and loader (WP6a).

The datasets are hand-written YAML, so every structural mistake a human can make (a typo in
a skill name, a clarify case that still lists skills, a test prompt copied into the dev set)
must fail loudly at load time. Otherwise the reported accuracy would quietly measure a
broken dataset instead of the router.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from skillagent.core.language import ZWNJ, normalize_persian, to_ascii_digits
from skillagent.core.types import SKILL_NAMES, LangCode
from skillagent.skills.params import SummarizerParams, TranslatorParams

__all__ = [
    "DatasetError",
    "EvalCase",
    "Expectation",
    "load_cases",
    "normalize_for_overlap",
    "overlap_errors",
    "render_prompt",
    "text_refs",
]

Outcome = Literal["plan", "clarify"]
Structure = Literal["single", "chain", "parallel"]
CaseLang = Literal["en", "fa", "mixed", "finglish"]
Category = Literal[
    "single", "chain", "parallel", "clarify", "no_match", "over_limit", "injection", "edge"
]
# Checks the runner applies to the final response text (WP6b implements them):
#   script_fa / script_latin — dominant script of the response
#   no_arabic_chars          — no Arabic ي/ك/ى in Persian output
#   no_preamble              — no "Here is the summary:"-style lead-in
#   not_answering_injection  — the payload's embedded instruction was not obeyed; the response
#                              must contain at least one of `must_contain_any`
OutputCheck = Literal[
    "script_fa", "script_latin", "no_preamble", "no_arabic_chars", "not_answering_injection"
]

MAX_SKILLS = 2  # spec limit (CONTRACTS: max_skills); the eval never expects more
SET_PREFIX = {"test_set": "T", "dev_set": "D"}

_TEXT_REF = re.compile(r"\{\{text:([a-z0-9_]+)\}\}")
_ANY_PLACEHOLDER = re.compile(r"\{\{.*?\}\}", re.DOTALL)
_PARAMS_MODELS: dict[str, type[BaseModel]] = {
    "translator": TranslatorParams,
    "summarizer": SummarizerParams,
}


class DatasetError(ValueError):
    """A dataset file is malformed or violates the split discipline."""


def text_refs(prompt: str) -> list[str]:
    """Names of `eval/texts/<name>.md` files a prompt references, in order."""
    return _TEXT_REF.findall(prompt)


class Expectation(BaseModel):
    """One acceptable routing result.

    `expected` must be complete; `also_ok` entries may be partial, in which case only the
    fields they set are compared (e.g. `{outcome: clarify}` accepts any clarification).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Outcome
    skills: list[str] | None = None  # ordered as the user stated the tasks
    structure: Structure | None = None
    response_language: LangCode | None = None
    params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    dropped: int | None = Field(default=None, ge=1)
    calc_values: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _clarify_has_no_skills(cls, data: Any) -> Any:
        # A clarification never runs skills, so `skills: []` is implied and need not be
        # written in the YAML; the runner can then compare skill lists uniformly.
        if isinstance(data, dict) and data.get("outcome") == "clarify":
            data = {"skills": [], **data}
        return data

    @field_validator("skills")
    @classmethod
    def _known_skills(cls, skills: list[str] | None) -> list[str] | None:
        if skills is not None:
            unknown = [s for s in skills if s not in SKILL_NAMES]
            if unknown:
                raise ValueError(f"unknown skill(s) {unknown}; allowed: {list(SKILL_NAMES)}")
            if len(skills) > MAX_SKILLS:
                raise ValueError(f"at most {MAX_SKILLS} skills can be expected, got {skills}")
        return skills

    @field_validator("calc_values")
    @classmethod
    def _numeric(cls, values: list[str]) -> list[str]:
        for value in values:
            try:
                number = Decimal(value)
            except InvalidOperation:
                raise ValueError(f"calc value {value!r} is not a number") from None
            if not number.is_finite():
                raise ValueError(f"calc value {value!r} is not finite")
        return values

    @field_validator("params")
    @classmethod
    def _valid_params(cls, params: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        # The params models ignore unknown keys, so a typo ("target_lang") would silently
        # vanish; comparing key sets catches it.
        for skill, values in params.items():
            model = _PARAMS_MODELS.get(skill)
            if model is None:
                raise ValueError(f"skill {skill!r} takes no params")
            dumped = model.model_validate(values).model_dump(exclude_none=True)
            if extra := set(values) - set(dumped):
                raise ValueError(f"unknown or null {skill} param(s): {sorted(extra)}")
        return params

    @model_validator(mode="after")
    def _consistent(self) -> Expectation:
        if self.outcome == "clarify":
            if self.skills:
                raise ValueError("outcome=clarify requires skills == []")
            if self.structure or self.params or self.calc_values or self.dropped:
                raise ValueError("outcome=clarify cannot set structure/params/calc/dropped")
            return self
        if self.skills is not None:
            if not self.skills:
                raise ValueError("outcome=plan needs at least one skill")
            if self.structure is not None:
                wanted_single = len(self.skills) == 1
                if (self.structure == "single") != wanted_single:
                    count = len(self.skills)
                    raise ValueError(f"structure {self.structure!r} contradicts {count} skill(s)")
            if missing := set(self.params) - set(self.skills):
                raise ValueError(f"params given for skills not in the plan: {sorted(missing)}")
            if self.calc_values and "calculator" not in self.skills:
                raise ValueError("calc_values require the calculator skill")
        return self

    def is_complete(self) -> bool:
        """True when this could serve as the primary `expected` block."""
        if self.response_language is None:
            return False
        return self.outcome == "clarify" or (bool(self.skills) and self.structure is not None)


class EvalCase(BaseModel):
    """One evaluation prompt with its expected routing and optional output checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[TD][0-9]{2}$")
    prompt: str = Field(min_length=1)
    lang: CaseLang
    category: Category
    expected: Expectation
    also_ok: list[Expectation] = Field(default_factory=list)
    output_checks: list[OutputCheck] = Field(default_factory=list)
    must_contain_any: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=10)

    @field_validator("prompt")
    @classmethod
    def _placeholders_well_formed(cls, prompt: str) -> str:
        bad = [p for p in _ANY_PLACEHOLDER.findall(prompt) if not _TEXT_REF.fullmatch(p)]
        if bad:
            raise ValueError(f"malformed placeholder(s) {bad}; use {{{{text:<name>}}}}")
        return prompt

    @model_validator(mode="after")
    def _consistent(self) -> EvalCase:
        exp = self.expected
        if not exp.is_complete():
            raise ValueError(
                "expected needs outcome, response_language and (for plans) skills + structure"
            )
        rules: dict[str, bool] = {
            "single": exp.structure == "single",
            "chain": exp.structure == "chain",
            "parallel": exp.structure == "parallel",
            "clarify": exp.outcome == "clarify",
            "no_match": exp.outcome == "plan" and exp.skills == ["general_chat"],
            "over_limit": exp.outcome == "plan" and exp.dropped is not None,
            "injection": "not_answering_injection" in self.output_checks,
            "edge": True,
        }
        if not rules[self.category]:
            raise ValueError(f"category {self.category!r} contradicts the expected block")
        if exp.dropped is not None and self.category not in ("over_limit", "edge"):
            raise ValueError("dropped is only meaningful for over_limit cases")
        if ("not_answering_injection" in self.output_checks) != bool(self.must_contain_any):
            raise ValueError("not_answering_injection and must_contain_any go together")
        if exp in self.also_ok:
            raise ValueError("also_ok repeats the expected block")
        return self


def _validation_message(index: int, item: Any, err: ValidationError) -> str:
    case_id = item.get("id", "?") if isinstance(item, dict) else "?"
    return f"case #{index} ({case_id}): {err}"


def load_cases(path: str | Path, *, texts_dir: str | Path | None = None) -> list[EvalCase]:
    """Load and fully validate one dataset file.

    Checks per-case shape, unique ids, the `T`/`D` prefix implied by the file name
    (`test_set` → T, `dev_set` → D) and that every referenced text exists. All problems are
    collected and raised together so a dataset author fixes them in one pass.
    """
    path = Path(path)
    texts = Path(texts_dir) if texts_dir is not None else path.parent / "texts"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise DatasetError(f"{path.name}: top level must be a list of cases")

    errors: list[str] = []
    cases: list[EvalCase] = []
    for index, item in enumerate(raw):
        try:
            cases.append(EvalCase.model_validate(item))
        except ValidationError as err:
            errors.append(_validation_message(index, item, err))

    prefix = SET_PREFIX.get(path.stem)
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            errors.append(f"{case.id}: duplicate id")
        seen.add(case.id)
        if prefix and not case.id.startswith(prefix):
            errors.append(f"{case.id}: ids in {path.name} must start with {prefix!r}")
        errors.extend(
            f"{case.id}: missing text file {name}.md"
            for name in text_refs(case.prompt)
            if not (texts / f"{name}.md").is_file()
        )
    if errors:
        raise DatasetError(f"{path.name}:\n" + "\n".join(errors))
    return cases


def _read_text(texts_dir: Path, name: str) -> str:
    return (texts_dir / f"{name}.md").read_text(encoding="utf-8").strip()


def render_prompt(case: EvalCase, texts_dir: str | Path) -> str:
    """The exact prompt sent to the agent: placeholders replaced by their text files."""
    texts = Path(texts_dir)
    return _TEXT_REF.sub(lambda m: _read_text(texts, m.group(1)), case.prompt)


def normalize_for_overlap(text: str) -> str:
    """Comparison key that ignores case, digits' script, Arabic/Persian letter variants,
    ZWNJ, punctuation and whitespace, so cosmetic edits can't hide a leaked prompt."""
    text = unicodedata.normalize("NFKC", normalize_persian(to_ascii_digits(text)))
    text = text.replace(ZWNJ, "").casefold()
    return " ".join(re.findall(r"\w+", text))


def overlap_errors(
    first: list[EvalCase], second: list[EvalCase], texts_dir: str | Path
) -> list[str]:
    """Split-discipline violations between two datasets (empty list = clean split).

    Compares (1) fully rendered prompts, (2) the instruction skeleton with placeholders
    removed, so the same wording around a different text still counts as a leak, and
    (3) the referenced text files, so the two sets never share a source paragraph.
    """
    errors: list[str] = []

    def keys(cases: list[EvalCase]) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        rendered: dict[str, str] = {}
        skeleton: dict[str, str] = {}
        texts: dict[str, str] = {}
        for case in cases:
            rendered.setdefault(normalize_for_overlap(render_prompt(case, texts_dir)), case.id)
            skel = normalize_for_overlap(_TEXT_REF.sub(" ", case.prompt))
            if skel:
                skeleton.setdefault(skel, case.id)
            for name in text_refs(case.prompt):
                texts.setdefault(name, case.id)
        return rendered, skeleton, texts

    labels = ("same prompt", "same instruction wording", "shared text file")
    for label, a, b in zip(labels, keys(first), keys(second), strict=True):
        errors.extend(f"{label}: {a[k]} and {b[k]}" for k in a.keys() & b.keys())
    return sorted(errors)
