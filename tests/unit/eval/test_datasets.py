"""The eval datasets load, validate, match the WP6a slot table and keep a clean split."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from eval.schema import (
    DatasetError,
    EvalCase,
    load_cases,
    normalize_for_overlap,
    overlap_errors,
    render_prompt,
    text_refs,
)

EVAL_DIR = Path(__file__).resolve().parents[3] / "eval"
TEXTS = EVAL_DIR / "texts"

# (lang, category) per slot, exactly as agent_prompts/WP6a_eval_datasets.md §3 fixes them.
TEST_SLOTS = {
    "T01": ("en", "single"),
    "T02": ("fa", "single"),
    "T03": ("en", "single"),
    "T04": ("fa", "single"),
    "T05": ("en", "single"),
    "T06": ("fa", "single"),
    "T07": ("en", "single"),
    "T08": ("fa", "single"),
    "T09": ("en", "chain"),
    "T10": ("en", "parallel"),
    "T11": ("mixed", "single"),
    "T12": ("fa", "clarify"),
    "T13": ("en", "no_match"),
    "T14": ("en", "over_limit"),
    "T15": ("fa", "injection"),
}


@pytest.fixture(scope="module")
def test_set() -> list[EvalCase]:
    return load_cases(EVAL_DIR / "test_set.yaml")


@pytest.fixture(scope="module")
def dev_set() -> list[EvalCase]:
    return load_cases(EVAL_DIR / "dev_set.yaml")


# --- the shipped datasets ---------------------------------------------------------------------


def test_test_set_matches_slot_table(test_set: list[EvalCase]) -> None:
    assert {c.id: (c.lang, c.category) for c in test_set} == TEST_SLOTS
    assert [c.id for c in test_set] == sorted(TEST_SLOTS)


def test_test_set_slot_specifics(test_set: list[EvalCase]) -> None:
    by_id = {c.id: c for c in test_set}
    assert by_id["T05"].expected.calc_values and by_id["T06"].expected.calc_values
    assert by_id["T09"].expected.skills == ["summarizer", "translator"]
    assert set(by_id["T10"].expected.skills or []) == {"translator", "calculator"}
    assert by_id["T11"].expected.response_language == "fa"
    assert by_id["T12"].expected.skills == []
    assert any(alt.outcome == "clarify" for alt in by_id["T13"].also_ok)
    assert by_id["T14"].expected.dropped == 1
    assert by_id["T15"].expected.skills == ["translator"]
    assert "not_answering_injection" in by_id["T15"].output_checks


def test_dev_set_size_and_ids(dev_set: list[EvalCase]) -> None:
    assert len(dev_set) >= 33
    assert [c.id for c in dev_set] == [f"D{i:02d}" for i in range(1, len(dev_set) + 1)]


def test_dev_set_contains_all_wp0_probes_once(dev_set: list[EvalCase]) -> None:
    probes = [
        int(m.group(1)) for c in dev_set if (m := re.match(r"WP0 probe #(\d+):", c.rationale))
    ]
    assert sorted(probes) == list(range(1, 21))


def test_dev_set_has_two_extra_finglish_cases(dev_set: list[EvalCase]) -> None:
    finglish = [c for c in dev_set if c.lang == "finglish" and "WP0 probe" not in c.rationale]
    assert len(finglish) >= 2


def test_sets_do_not_overlap(test_set: list[EvalCase], dev_set: list[EvalCase]) -> None:
    assert overlap_errors(test_set, dev_set, TEXTS) == []


def test_every_text_file_is_used(test_set: list[EvalCase], dev_set: list[EvalCase]) -> None:
    used = {name for c in test_set + dev_set for name in text_refs(c.prompt)}
    assert {p.stem for p in TEXTS.glob("*.md")} == used


def test_long_text_is_long_enough_for_windowing() -> None:
    words = (TEXTS / "dev_en_long_timekeeping.md").read_text(encoding="utf-8").split()
    assert len(words) >= 1300


def test_prompts_render_without_placeholders(
    test_set: list[EvalCase], dev_set: list[EvalCase]
) -> None:
    for case in test_set + dev_set:
        assert "{{" not in render_prompt(case, TEXTS), case.id


def test_every_case_has_a_rationale(test_set: list[EvalCase], dev_set: list[EvalCase]) -> None:
    for case in test_set + dev_set:
        assert "\n" not in case.rationale.strip(), case.id


def _persian_sources(cases: list[EvalCase]) -> list[tuple[str, str]]:
    found = [(c.id, re.sub(r"\{\{.*?\}\}", "", c.prompt)) for c in cases if c.lang == "fa"]
    found += [(p.name, p.read_text(encoding="utf-8")) for p in TEXTS.glob("*_fa_*.md")]
    return found


def test_persian_text_hygiene(test_set: list[EvalCase], dev_set: list[EvalCase]) -> None:
    """Persian prompts and texts use Persian letters and punctuation (CLAUDE.md §5)."""
    for source, text in _persian_sources(test_set + dev_set):
        assert not set(text) & set("يكى"), f"{source}: Arabic letter variant"
        assert not set(text) & set(",;?"), f"{source}: ASCII punctuation in Persian"
        assert not re.search(r"(?:^|\s)ن?می ", text), f"{source}: 'می' without ZWNJ"


# --- the validator rejects broken data --------------------------------------------------------


def _case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": "D01",
        "prompt": "What is 2+2?",
        "lang": "en",
        "category": "single",
        "expected": {
            "outcome": "plan",
            "skills": ["calculator"],
            "structure": "single",
            "response_language": "en",
            "calc_values": ["4"],
        },
        "rationale": "simple arithmetic baseline",
    }
    case.update(overrides)
    return case


def _write(tmp_path: Path, cases: list[dict[str, Any]], name: str = "dev_set") -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(cases, allow_unicode=True), encoding="utf-8")
    (tmp_path / "texts").mkdir(exist_ok=True)
    return path


def test_valid_minimal_case_loads(tmp_path: Path) -> None:
    assert load_cases(_write(tmp_path, [_case()]))[0].id == "D01"


@pytest.mark.parametrize(
    ("expected_patch", "message"),
    [
        ({"skills": ["calculator", "weather"]}, "unknown skill"),
        ({"outcome": "clarify", "structure": None, "calc_values": []}, "requires skills"),
        ({"structure": "chain"}, "contradicts"),
        ({"calc_values": ["about 4"]}, "not a number"),
        ({"skills": ["general_chat"]}, "calc_values require"),
        ({"skills": ["calculator"] * 3, "structure": "parallel"}, "at most 2"),
        ({"response_language": None}, "expected needs"),
        ({"response_language": "klingon"}, "unknown language"),
    ],
)
def test_invalid_expectations_are_rejected(
    tmp_path: Path, expected_patch: dict[str, Any], message: str
) -> None:
    case = _case()
    case["expected"] = {**case["expected"], **expected_patch}
    with pytest.raises(DatasetError, match=message):
        load_cases(_write(tmp_path, [case]))


def test_unknown_param_key_is_rejected(tmp_path: Path) -> None:
    case = _case(
        prompt="Translate hi to German",
        expected={
            "outcome": "plan",
            "skills": ["translator"],
            "structure": "single",
            "response_language": "en",
            "params": {"translator": {"target_lang": "de"}},
        },
    )
    with pytest.raises(DatasetError, match="target_lang"):
        load_cases(_write(tmp_path, [case]))


def test_category_must_agree_with_expected(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="category 'chain'"):
        load_cases(_write(tmp_path, [_case(category="chain")]))


def test_injection_requires_markers(tmp_path: Path) -> None:
    case = _case(output_checks=["not_answering_injection"])
    with pytest.raises(DatasetError, match="must_contain_any"):
        load_cases(_write(tmp_path, [case]))


def test_duplicate_ids_and_wrong_prefix(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="duplicate id"):
        load_cases(_write(tmp_path, [_case(), _case(prompt="What is 3+3?")]))
    with pytest.raises(DatasetError, match="must start with 'T'"):
        load_cases(_write(tmp_path, [_case()], name="test_set"))


def test_missing_text_and_malformed_placeholder(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="missing text file nope.md"):
        load_cases(_write(tmp_path, [_case(prompt="Sum: {{text:nope}}")]))
    with pytest.raises(DatasetError, match="malformed placeholder"):
        load_cases(_write(tmp_path, [_case(prompt="Sum: {{txt:nope}}")]))


def test_overlap_detection(tmp_path: Path) -> None:
    (tmp_path / "shared.md").write_text("Some paragraph.", encoding="utf-8")
    base = _case(expected={**_case()["expected"]})
    test = [EvalCase.model_validate({**base, "id": "T01", "prompt": "What is ۲+۲ ?"})]
    dev = [EvalCase.model_validate(base)]
    assert any("same prompt" in e for e in overlap_errors(test, dev, tmp_path))

    summ = {
        "outcome": "plan",
        "skills": ["summarizer"],
        "structure": "single",
        "response_language": "en",
    }
    t = EvalCase.model_validate(_case(id="T02", prompt="Sum up: {{text:shared}}", expected=summ))
    d = EvalCase.model_validate(_case(prompt="Briefly: {{text:shared}}", expected=summ))
    assert overlap_errors([t], [d], tmp_path) == ["shared text file: T02 and D01"]


def test_normalization_ignores_cosmetic_differences() -> None:
    assert normalize_for_overlap("سلام، خوبي؟") == normalize_for_overlap("سلام خوبی")
    assert normalize_for_overlap("What is 17% of 2,340?") == normalize_for_overlap(
        "what is 17 of 2 340"
    )
