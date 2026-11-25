"""Evaluator correctness: precedence, exactness, every whitelisted function, limits."""

from __future__ import annotations

import math
import random
from fractions import Fraction

import pytest

from skillagent.skills.calculator import evaluator
from skillagent.skills.calculator.evaluator import (
    FUNCTION_NAMES,
    CalculatorError,
    check_expression,
    evaluate,
)


def exact(expr: str) -> Fraction:
    value = evaluate(expr)
    assert value.is_exact, f"{expr} should be exact, got {value}"
    assert value.exact is not None
    return value.exact


def approx(expr: str) -> float:
    value = evaluate(expr)
    assert not value.is_exact and value.exact is None
    return value.approx


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("2 ** 3 ** 2", 512),  # right-associative
        ("-2**2", -4),  # unary minus binds looser than **
        ("(-2)**2", 4),
        ("--3", 3),
        ("+-+5", -5),
        ("10 - 4 - 3", 3),
        ("100 / 10 / 5", 2),
        ("7 // 2", 3),
        ("-7 // 2", -4),
        ("7 % 3", 1),
        ("-7 % 3", 2),
        ("2 * -3", -6),
        ("0**0", 1),
        ("1_000 + 1", 1001),
    ],
)
def test_precedence_and_integers(expr: str, expected: int) -> None:
    assert exact(expr) == expected


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("0.1 + 0.2", Fraction(3, 10)),
        ("1/3*3", Fraction(1)),
        ("1/3 + 1/6", Fraction(1, 2)),
        ("0.1 * 3", Fraction(3, 10)),
        ("1.1 * 1.1", Fraction(121, 100)),
        ("2.5 % 1", Fraction(1, 2)),
        ("1e3 / 8", Fraction(125)),
        ("1.5e-3 * 1000", Fraction(3, 2)),
        (".5 + 5.", Fraction(11, 2)),
        ("1e400 / 1e399", Fraction(10)),
        ("2 ** -2", Fraction(1, 4)),
        ("(2/3) ** 3", Fraction(8, 27)),
    ],
)
def test_exact_rational_arithmetic(expr: str, expected: Fraction) -> None:
    assert exact(expr) == expected


def test_literal_is_parsed_from_source_text() -> None:
    # A float literal would be 0.1000000000000000055511151231257827...
    assert exact("0.1") == Fraction(1, 10)
    assert exact("0.1000000000000000000001") == Fraction(10**21 + 1, 10**22)


def test_big_integers_within_limits() -> None:
    assert exact("2 ** 1000") == 2**1000
    assert exact("factorial(1000)") == math.factorial(1000)
    assert exact("10 ** 4999") == 10**4999
    assert exact("comb(1000, 500)") == math.comb(1000, 500)


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("sqrt(144)", Fraction(12)),
        ("sqrt(16/9)", Fraction(4, 3)),
        ("sqrt(0.25)", Fraction(1, 2)),
        ("cbrt(27)", Fraction(3)),
        ("cbrt(-8)", Fraction(-2)),
        ("abs(-3.5)", Fraction(7, 2)),
        ("round(2.5)", Fraction(3)),  # half away from zero, not banker's rounding
        ("round(-2.5)", Fraction(-3)),
        ("round(3.14159, 2)", Fraction(314, 100)),
        ("round(1234, -2)", Fraction(1200)),
        ("floor(-2.5)", Fraction(-3)),
        ("ceil(2.1)", Fraction(3)),
        ("factorial(5)", Fraction(120)),
        ("comb(5, 2)", Fraction(10)),
        ("perm(5, 2)", Fraction(20)),
        ("perm(4)", Fraction(24)),
        ("gcd(12, 18)", Fraction(6)),
        ("gcd(12, 18, 8)", Fraction(2)),
        ("lcm(4, 6)", Fraction(12)),
        ("min(3, 1.5, 2)", Fraction(3, 2)),
        ("max(3, 1.5, 2)", Fraction(3)),
        ("hypot(3, 4)", Fraction(5)),
        ("log(8, 2)", Fraction(3)),
        ("log(1/8, 2)", Fraction(-3)),
        ("log10(1000)", Fraction(3)),
        ("log2(1024)", Fraction(10)),
        ("ln(1)", Fraction(0)),
        ("8 ** (2/3)", Fraction(4)),
        ("4 ** 0.5", Fraction(2)),
    ],
)
def test_functions_with_exact_results(expr: str, expected: Fraction) -> None:
    assert exact(expr) == expected


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("sqrt(2)", math.sqrt(2)),
        ("cbrt(2)", math.cbrt(2)),
        ("exp(1)", math.e),
        ("ln(e)", 1.0),
        ("log(10)", math.log(10)),
        ("log(10, 3)", math.log(10, 3)),
        ("log10(2)", math.log10(2)),
        ("log2(3)", math.log2(3)),
        ("sin(pi/6)", math.sin(math.pi / 6)),
        ("cos(0.5)", math.cos(0.5)),
        ("tan(pi/4)", math.tan(math.pi / 4)),
        ("asin(1)", math.pi / 2),
        ("acos(0)", math.pi / 2),
        ("atan(1)", math.pi / 4),
        ("sinh(1)", math.sinh(1)),
        ("cosh(1)", math.cosh(1)),
        ("tanh(1)", math.tanh(1)),
        ("degrees(pi)", 180.0),
        ("radians(180)", math.pi),
        ("sin(radians(30))", 0.5),
        ("hypot(1, 1)", math.sqrt(2)),
        ("2 ** 0.5", math.sqrt(2)),
        ("pi * 2", math.tau),
        ("tau / 2", math.pi),
        ("ceil(pi)", 4.0),
        ("round(pi, 2)", 3.14),
    ],
)
def test_functions_with_float_results(expr: str, expected: float) -> None:
    assert approx(expr) == pytest.approx(expected, rel=1e-12)


def test_every_whitelisted_function_is_tested() -> None:
    names = {expr.split("(")[0] for expr in _ALL_FUNCTION_CASES}
    assert names >= FUNCTION_NAMES


_ALL_FUNCTION_CASES = [
    "sqrt(1)", "cbrt(1)", "abs(1)", "round(1)", "floor(1)", "ceil(1)", "exp(1)", "ln(1)",
    "log(1)", "log10(1)", "log2(1)", "sin(1)", "cos(1)", "tan(1)", "asin(1)", "acos(1)",
    "atan(1)", "sinh(1)", "cosh(1)", "tanh(1)", "degrees(1)", "radians(1)", "factorial(1)",
    "comb(1, 1)", "perm(1)", "gcd(1)", "lcm(1)", "min(1)", "max(1)", "hypot(1)",
]  # fmt: skip


@pytest.mark.parametrize("expr", _ALL_FUNCTION_CASES)
def test_every_function_evaluates(expr: str) -> None:
    value = evaluate(expr)
    assert math.isfinite(value.approx)


def test_trig_noise_is_snapped_to_zero() -> None:
    assert approx("sin(pi)") == 0.0
    assert approx("cos(pi/2)") == 0.0


@pytest.mark.parametrize(
    ("expr", "code"),
    [
        ("1/0", "div_zero"),
        ("1//0", "div_zero"),
        ("1%0", "div_zero"),
        ("1/(2-2)", "div_zero"),
        ("1.5/0.0", "div_zero"),
        ("0 ** -1", "div_zero"),
        ("pi/0", "div_zero"),
        ("sqrt(-1)", "domain"),
        ("log(0)", "domain"),
        ("ln(-1)", "domain"),
        ("log(8, 1)", "domain"),
        ("log(8, -2)", "domain"),
        ("asin(2)", "domain"),
        ("acos(-1.5)", "domain"),
        ("factorial(-1)", "domain"),
        ("factorial(2.5)", "domain"),
        ("comb(-1, 2)", "domain"),
        ("gcd(1.5, 2)", "domain"),
        ("(-8) ** (1/3)", "domain"),
        ("(-2) ** 0.5", "domain"),
        ("exp(1000)", "too_large"),
        ("cosh(1000)", "too_large"),
        ("1e308 * pi * 10", "too_large"),
        ("2.0 ** 5000 * pi", "too_large"),
        ("factorial(1001)", "too_large"),
        ("comb(1001, 2)", "too_large"),
        ("perm(5000, 2)", "too_large"),
        ("round(1, 1000)", "too_large"),
        ("sqrt(1, 2)", "syntax"),
        ("comb(5)", "syntax"),
        ("max()", "syntax"),
        ("sqrt", "syntax"),
        ("1 +", "syntax"),
        ("(1 + 2", "syntax"),
        ("", "syntax"),
        ("   ", "syntax"),
    ],
)
def test_error_codes(expr: str, code: str) -> None:
    with pytest.raises(CalculatorError) as info:
        evaluate(expr)
    assert info.value.code == code
    assert info.value.message


def test_non_integer_exponent_falls_back_to_float() -> None:
    assert approx("2 ** 1.5") == pytest.approx(2**1.5)
    assert approx("pi ** 2") == pytest.approx(math.pi**2)


def test_large_exact_values_keep_an_infinite_approximation() -> None:
    value = evaluate("10 ** 400")
    assert value.is_exact and value.exact == 10**400
    assert value.approx == math.inf


def test_trivial_bases_are_exempt_from_the_exponent_limit() -> None:
    assert exact("1 ** 1000000") == 1
    assert exact("(-1) ** 1000001") == -1
    assert exact("0 ** 1000000") == 0


def test_check_expression_does_not_evaluate() -> None:
    check_expression("1/0")  # parses fine; only evaluation fails
    check_expression("factorial(1000) ** 1000")


def test_limits_are_patchable_module_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evaluator, "MAX_EXPRESSION_LENGTH", 5)
    with pytest.raises(CalculatorError, match="too_complex"):
        evaluate("1+2+33")
    monkeypatch.setattr(evaluator, "MAX_EXPRESSION_LENGTH", 500)
    monkeypatch.setattr(evaluator, "MAX_FACTORIAL_N", 10)
    with pytest.raises(CalculatorError, match="too_large"):
        evaluate("factorial(11)")


# --- property-style: random integer expressions vs independently built Fractions -------


def _random_expression(rng: random.Random, depth: int) -> tuple[str, Fraction]:
    """Build an expression string and its exact value side by side (no eval anywhere)."""
    if depth == 0 or rng.random() < 0.3:
        n = rng.randint(-20, 20)
        return (f"({n})" if n < 0 else str(n)), Fraction(n)
    kind = rng.choice(["+", "-", "*", "/", "**", "neg"])
    if kind == "neg":
        text, value = _random_expression(rng, depth - 1)
        return f"-({text})", -value
    left_text, left = _random_expression(rng, depth - 1)
    if kind == "**":
        exponent = rng.randint(0, 3)
        if left == 0:
            exponent = max(exponent, 1)
        return f"({left_text}) ** {exponent}", left**exponent
    right_text, right = _random_expression(rng, depth - 1)
    if kind == "/" and right == 0:
        right_text, right = "7", Fraction(7)
    result = {
        "+": lambda: left + right,
        "-": lambda: left - right,
        "*": lambda: left * right,
        "/": lambda: left / right,
    }[kind]()
    return f"({left_text}) {kind} ({right_text})", result


@pytest.mark.parametrize("seed", range(150))
def test_random_expressions_match_fraction_arithmetic(seed: int) -> None:
    text, expected = _random_expression(random.Random(seed), depth=4)
    assert exact(text) == expected, text
