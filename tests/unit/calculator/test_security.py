"""Hostile input: code execution attempts and resource exhaustion.

Every case runs under `within_timeout` (2 s, daemon thread, works on Windows), so a
regression that makes the evaluator hang fails the test instead of hanging the suite.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from skillagent.skills.calculator.evaluator import CalculatorError, evaluate
from skillagent.skills.calculator.normalize import (
    looks_like_expression,
    strip_cues,
    to_expression,
)

INJECTION = [
    "__import__('os')",
    "__import__('os').system('echo pwned')",
    "().__class__",
    "().__class__.__bases__[0].__subclasses__()",
    "(1).__class__",
    "[1][0]",
    "[x for x in (1, 2)]",
    "{1: 2}",
    "{1, 2}",
    "(1, 2)",
    "lambda: 1",
    "(lambda x: x)(1)",
    "open('secrets.txt')",
    "eval('1+1')",
    "exec('import os')",
    "compile('1', 'f', 'eval')",
    "globals()",
    "getattr(1, 'real')",
    "breakpoint()",
    "input()",
    "x + 1",
    "sqrt.__globals__",
    "math.sqrt(4)",
    "'a' * 3",
    "b'abc'",
    "f'{1+1}'",
    "f'{__import__(\"os\")}'",
    "1 if 1 else 2",
    "(y := 5)",
    "1 < 2",
    "1 and 2",
    "not 1",
    "~1",
    "1 << 2",
    "1 | 2",
    "2 ^ 3",
    "2 @ 3",
    "True + 1",
    "None",
    "...",
    "1j * 2",
    "sqrt(x=4)",
    "max(*[1, 2])",
    "round(2.5, ndigits=1)",
    "await 1",
]

RESOURCE = [
    ("9**9**9", "too_large"),
    ("9**9**9**9", "too_large"),
    ("10**100000", "too_large"),
    ("2**10001", "too_large"),
    ("999**5000", "too_large"),
    ("(10**2500) * (10**2500) * 10", "too_large"),
    ("factorial(100000)", "too_large"),
    ("factorial(10**10)", "too_large"),
    ("comb(10**9, 10**4)", "too_large"),
    ("perm(10**9, 10**4)", "too_large"),
    ("1e100000", "too_large"),
    ("1e-100000", "too_large"),
    ("lcm(10**2600, 10**2600 + 1)", "too_large"),
    ("2.0 ** 100000", "too_large"),
    ("exp(10**6)", "too_large"),
    ("(" * 41 + "1" + ")" * 41, "too_complex"),
    ("(" * 5000 + "1" + ")" * 5000, "too_complex"),
    ("-" * 450 + "1", "too_complex"),
    ("1+" * 200 + "1", "too_complex"),
    ("1" * 10_000, "too_complex"),
    ("1+" * 5000 + "1", "too_complex"),
    ("sqrt(" * 30 + "2" + ")" * 30, None),  # deep but legal
    ("(" * 40 + "1" + ")" * 40, None),
]


@pytest.mark.parametrize("expr", INJECTION)
def test_code_execution_is_rejected(expr: str, within_timeout: Callable[..., Any]) -> None:
    def attempt() -> str:
        with pytest.raises(CalculatorError) as info:
            evaluate(expr)
        return info.value.code

    code = within_timeout(attempt, name=expr)
    assert code in ("unsupported", "syntax")


@pytest.mark.parametrize("expr", [e for e in INJECTION if e != "2 ^ 3"])
def test_injection_never_qualifies_for_the_direct_path(
    expr: str, within_timeout: Callable[..., Any]
) -> None:
    assert within_timeout(lambda: looks_like_expression(expr), name=f"looks:{expr}") is False


@pytest.mark.parametrize(("expr", "code"), RESOURCE, ids=lambda v: str(v)[:30])
def test_resource_exhaustion_is_bounded(
    expr: str, code: str | None, within_timeout: Callable[..., Any]
) -> None:
    def attempt() -> str | None:
        try:
            evaluate(expr)
        except CalculatorError as exc:
            return exc.code
        return None

    assert within_timeout(attempt, name=expr[:40]) == code


def test_caret_is_rejected_raw_but_normalized_to_power() -> None:
    with pytest.raises(CalculatorError, match="use \\*\\* for powers"):
        evaluate("2 ^ 3")
    assert to_expression("2 ^ 3") == "2 ** 3"


def test_huge_input_never_takes_the_direct_path(within_timeout: Callable[..., Any]) -> None:
    text = "۱۲۳٬۴۵۶ × (" * 2000 + "1"
    assert within_timeout(lambda: looks_like_expression(text), name="looks:huge") is False
    assert to_expression("2(" * 3000).count("*") == 3000


# Regression: `\s*(?:را|رو)?\s*…$` in the Persian trailing-cue pattern was ~cubic and took
# 21 s on 2 000 spaces. Each normalizer step must stay roughly linear on long input.
REDOS = {
    "spaces": "1" + " " * 50_000 + "x",
    "spaces_then_question": "1" + " " * 50_000 + "?x",
    "mixed_whitespace_then_cue": "2+2" + " \t\n" * 20_000 + "چند",
    "zwnj_runs": "۲+۲ چند" + "\u200c " * 20_000 + "x",
    "repeated_cue_word": "را " * 20_000 + "x",
    "question_marks": "1+1" + "?" * 50_000 + "x",
    "parens": "2(" * 20_000,
    "commas": "1" + ",000" * 10_000 + "x",
}


@pytest.mark.parametrize("name", list(REDOS))
def test_normalizer_is_linear_on_adversarial_text(
    name: str, within_timeout: Callable[..., Any]
) -> None:
    text = REDOS[name]
    within_timeout(lambda: strip_cues(text), name=f"strip_cues:{name}", seconds=1.0)
    within_timeout(lambda: to_expression(text), name=f"to_expression:{name}", seconds=1.0)
    within_timeout(lambda: looks_like_expression(text), name=f"looks:{name}", seconds=1.0)


def test_unicode_identifier_tricks_are_rejected() -> None:
    # NFKC folds these to "exec"/"eval": still just unknown names, never executed.
    for expr in ("ｅｘｅｃ('1')", "𝐞𝐯𝐚𝐥('1')"):
        with pytest.raises(CalculatorError):
            evaluate(expr)


def test_no_eval_exec_or_sympify_in_the_package() -> None:
    """Acceptance check from WP2 §10, as a test: only `evaluate(` names may match."""
    root = Path(__file__).resolve().parents[3] / "skillagent"
    pattern = re.compile(r"eval\(|exec\(|sympify")
    offenders = [
        f"{path.relative_to(root)}:{n}: {line.strip()}"
        for path in root.rglob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line.replace("evaluate(", "").replace("_eval(", ""))
    ]
    assert offenders == []
