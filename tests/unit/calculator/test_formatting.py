"""Deterministic EN/FA formatting: grouping, rounding, exact fractions, errors."""

from __future__ import annotations

import math

import pytest

from skillagent.skills.calculator.evaluator import evaluate
from skillagent.skills.calculator.formatting import (
    error_text,
    format_error_line,
    format_result_line,
    fraction_text,
    localize_number,
    render_number,
)


@pytest.mark.parametrize(
    ("expr", "text", "approximate", "exact"),
    [
        ("180/2.5", "72", False, "72"),
        ("0.1+0.2", "0.3", False, "3/10"),
        ("1/3", "0.333333333333", True, "1/3"),
        ("2/3", "0.666666666667", True, "2/3"),
        ("1/8", "0.125", False, "1/8"),
        ("-7/2", "-3.5", False, "-7/2"),
        ("1234567", "1234567", False, "1234567"),
        ("10**20", "100000000000000000000", False, "100000000000000000000"),
        ("2**-20", "9.53674316406e-7", True, "1/1048576"),
        ("sqrt(2)", "1.41421356237", True, None),
        ("0.1 * pi / pi", "0.1", True, None),
        ("sin(pi)", "0", False, None),
        ("tan(pi/4)", "1", True, None),
        ("1e-9 * pi", "3.14159265359e-9", True, None),
        ("factorial(200)", "7.88657867365e+374", True, None),
    ],
)
def test_render_number(expr: str, text: str, approximate: bool, exact: str | None) -> None:
    rendered = render_number(evaluate(expr))
    assert rendered.text == text
    assert rendered.approximate is approximate
    if exact is not None:
        assert rendered.exact == exact


def test_float_noise_never_appears() -> None:
    for expr in ("0.1 + 0.2 + pi - pi", "0.1 * 3 + e - e", "1.1 * 1.1 * pi / pi"):
        text = render_number(evaluate(expr)).text
        assert "0000000" not in text and "9999999" not in text, text
    assert "30000000000000004" not in format_result_line("x", "", evaluate("0.1+0.2"), "en")


def test_huge_exact_integer_keeps_full_digits_in_exact() -> None:
    rendered = render_number(evaluate("factorial(1000)"))
    assert rendered.exact == str(math.factorial(1000))  # 2568 digits, under str() limit
    big = render_number(evaluate("10**4999"))
    assert big.exact is not None and len(big.exact) == 5000  # past Python's 4300 limit
    assert big.text == "1e+4999"


def test_fraction_text_handles_huge_values() -> None:
    from fractions import Fraction

    assert fraction_text(Fraction(10**4500, 3)) == "1" + "0" * 4500 + "/3"
    assert fraction_text(Fraction(-5, 1)) == "-5"


@pytest.mark.parametrize(
    ("text", "lang", "shown"),
    [
        ("1234567", "en", "1,234,567"),
        ("1234567", "fa", "۱٬۲۳۴٬۵۶۷"),
        ("-1234.5", "en", "-1,234.5"),
        ("-1234.5", "fa", "-۱٬۲۳۴٫۵"),
        ("999", "en", "999"),
        ("0.333333333333", "fa", "۰٫۳۳۳۳۳۳۳۳۳۳۳۳"),
        ("1e+4999", "en", "1 × 10^4999"),
        ("9.53674316406e-7", "fa", "۹٫۵۳۶۷۴۳۱۶۴۰۶ × ۱۰^-۷"),
    ],
)
def test_localize_number(text: str, lang: str, shown: str) -> None:
    assert localize_number(text, lang) == shown


@pytest.mark.parametrize(
    ("expr", "label", "lang", "line"),
    [
        ("180 / 2.5", "average speed (km/h)", "en", "Average speed (km/h): 180 / 2.5 = 72"),
        (
            "180 / 2.5",
            "میانگین سرعت (کیلومتر بر ساعت)",
            "fa",
            "میانگین سرعت (کیلومتر بر ساعت): 180 / 2.5 = ۷۲",
        ),
        ("1/3", "", "en", "1/3 ≈ 0.333333333333 (exact: 1/3)"),
        ("1/3", "", "fa", "1/3 ≈ ۰٫۳۳۳۳۳۳۳۳۳۳۳۳ (مقدار دقیق: ۱/۳)"),
        ("1234567 * 1", "", "en", "1234567 * 1 = 1,234,567"),
        ("sqrt(2)", "", "en", "sqrt(2) ≈ 1.41421356237"),
        ("2**-20", "", "en", "2**-20 ≈ 9.53674316406 × 10^-7 (exact: 1/1048576)"),
    ],
)
def test_format_result_line(expr: str, label: str, lang: str, line: str) -> None:
    assert format_result_line(expr, label, evaluate(expr), lang) == line


def test_long_exact_fraction_is_not_shown() -> None:
    line = format_result_line("x", "", evaluate("1/3**80"), "en")
    assert "exact" not in line and line.startswith("x ≈ ")


@pytest.mark.parametrize(
    ("code", "fa_text"),
    [
        ("div_zero", "تقسیم بر صفر تعریف‌نشده است"),
        ("domain", "مقدار خارج از دامنهٔ تعریف تابع است"),
        ("too_large", "نتیجه برای محاسبهٔ ایمن بیش از حد بزرگ است"),
        ("too_complex", "عبارت بیش از حد طولانی یا تودرتو است"),
        ("syntax", "عبارت معتبر نیست"),
        ("unsupported", "عبارت شامل چیزی است که ماشین‌حساب پشتیبانی نمی‌کند"),
    ],
)
def test_error_text_bilingual(code: str, fa_text: str) -> None:
    assert error_text(code, "detail", "fa") == fa_text
    assert error_text(code, "", "en")  # generic English sentence when no detail
    assert error_text(code, "specific detail", "en") == "specific detail"
    for ch in fa_text:
        assert ch not in "يك"  # Persian letters, not Arabic


def test_format_error_line() -> None:
    assert (
        format_error_line("1/0", "share", "div_zero", "division by zero", "en")
        == "Share: 1/0 → error: division by zero"
    )
    assert (
        format_error_line("1/0", "سهم", "div_zero", "division by zero", "fa")
        == "سهم: 1/0 → خطا: تقسیم بر صفر تعریف‌نشده است"
    )
