"""Text → expression normalization and direct-path classification."""

from __future__ import annotations

from fractions import Fraction

import pytest

from skillagent.skills.calculator.evaluator import evaluate
from skillagent.skills.calculator.normalize import looks_like_expression, strip_cues, to_expression


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("۱۲ × ۳٫۵", "12 * 3.5"),
        ("١٢ × ٣٫٥", "12 * 3.5"),  # Arabic-Indic digits
        ("۱٬۲۰۰ ÷ ۴", "1200 / 4"),
        ("8 − 3 – 1", "8 - 3 - 1"),
        ("2^3", "2**3"),
        ("2²", "2**2"),
        ("3 · 4", "3 * 4"),
        ("3 ✕ 4", "3 * 4"),
        ("3 x 4", "3*4"),
        ("√16+9", "sqrt(16)+9"),
        ("√(9)*2", "sqrt(9)*2"),
        ("∛27", "cbrt(27)"),
        ("17%", "(17/100)"),
        ("۱۷٪", "(17/100)"),
        ("50% * 200", "(50/100) * 200"),
        ("17 % 5", "17 % 5"),  # modulo stays modulo
        ("15% of 2,480", "(15/100)*2480"),
        ("۱۵ درصد از ۲۴۸۰", "(15/100)*2480"),
        ("2,340 + 1,000,000", "2340 + 1000000"),
        ("1,234.5 * 2", "1234.5 * 2"),
        ("gcd(12, 18)", "gcd(12, 18)"),
        ("max(1,234)", "max(1,234)"),  # commas inside a call are arguments
        ("(1,000 + 2,000) * 2", "(1000 + 2000) * 2"),
        ("2(3+4)", "2*(3+4)"),
        ("(1+2)(3+4)", "(1+2)*(3+4)"),
        ("(1+2)3", "(1+2)*3"),
        ("2pi", "2*pi"),
        ("2 sqrt(9)", "2*sqrt(9)"),
        ("sqrt(9)", "sqrt(9)"),  # no * between a function and its "("
        ("1e5*2", "1e5*2"),  # scientific literal stays intact
        ("  1   +    2  ", "1 + 2"),
    ],
)
def test_to_expression(text: str, expected: str) -> None:
    assert to_expression(text) == expected


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("۳٫۵ + ۱", Fraction(9, 2)),
        ("۱٬۲۰۰ × ۲", Fraction(2400)),
        ("15% of 2,480", Fraction(372)),
        ("2(3+4)", Fraction(14)),
        ("(1+2)(3+4)", Fraction(21)),
        ("200 * 17%", Fraction(34)),
        ("2,340 + 1,000,000", Fraction(1002340)),
    ],
)
def test_normalized_text_evaluates(text: str, value: Fraction) -> None:
    assert evaluate(to_expression(text)).exact == value


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("What is 2+2?", "2+2"),
        ("what's 3*4", "3*4"),
        ("Calculate: 10/4", "10/4"),
        ("compute 7*6 =", "7*6"),
        ("Please evaluate (3+4)*2", "(3+4)*2"),
        ("۲+۲ چند می‌شود؟", "۲+۲"),
        ("۲+۲ چند میشه؟", "۲+۲"),
        ("۲+۲ چقدر است؟", "۲+۲"),
        ("حاصل ۳*۴ را حساب کن", "۳*۴"),
        ("۵*۵ رو محاسبه کن", "۵*۵"),
        ("calculated 2+2", "calculated 2+2"),  # cue must be a whole word
        ("compute 15% of 240.", "15% of 240"),  # sentence-final period dropped
        ("2.5*4.", "2.5*4"),
    ],
)
def test_strip_cues(text: str, expected: str) -> None:
    assert strip_cues(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "2+2",
        "(3+4)*2^3 / 7",
        "۱۲ × ۳٫۵",
        "sqrt(16)",
        "17%",
        "15% of 2,480",
        "2pi",
        "1/0",
        "1+" * 400 + "1",  # too_complex is still an expression (limit message, no LLM)
    ],
)
def test_looks_like_expression_positive(text: str) -> None:
    assert looks_like_expression(text)


@pytest.mark.parametrize(
    "text",
    [
        "42",
        "-5",
        "pi",
        "",
        "2 apples and 3 oranges",
        "2+2 in Persian",
        "x**2 + 1",
        "hello",
        "سلام",
        "بیست و پنج ضرب در چهار",
        "2 3",
        "1990-2000 was a decade?!",
        "sqrt(1,2)",
    ],
)
def test_looks_like_expression_negative(text: str) -> None:
    assert not looks_like_expression(text)
