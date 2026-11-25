"""Deterministic EN/FA rendering of calculator results.

Every digit the user sees is produced here from the evaluator's value; the model only
ever contributes labels. Numbers are rounded to 12 significant digits with `decimal`
(never `repr(float)`), so float noise such as `0.30000000000000004` cannot appear, and
huge exact integers are rendered without Python's 4300-digit `int → str` limit.

Persian choices (documented for reviewers): Persian digits, `٫` as the decimal mark and
`٬` (U+066C) as the thousands separator, applied to the *result*; the expression stays in
ASCII so operators and precedence are unambiguous in both directions of text.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction

from skillagent.core.language import to_persian_digits
from skillagent.skills.calculator.evaluator import CalcValue

__all__ = [
    "SIGNIFICANT_DIGITS",
    "RenderedNumber",
    "error_text",
    "format_error_line",
    "format_result_line",
    "fraction_text",
    "localize_number",
    "render_number",
]

SIGNIFICANT_DIGITS = 12
MAX_FULL_INTEGER_DIGITS = 100  # longer exact integers are shown in scientific form
MAX_EXACT_FRACTION_CHARS = 40  # "(exact: p/q)" is shown only when it stays readable
_FIXED_RANGE = (Decimal("1e-6"), Decimal("1e15"))  # outside → scientific notation

_ERROR_TEXT: dict[str, dict[str, str]] = {
    "div_zero": {"en": "division by zero is undefined", "fa": "تقسیم بر صفر تعریف‌نشده است"},
    "domain": {
        "en": "the value is outside the function's domain",
        "fa": "مقدار خارج از دامنهٔ تعریف تابع است",
    },
    "too_large": {
        "en": "the result is too large to compute safely",
        "fa": "نتیجه برای محاسبهٔ ایمن بیش از حد بزرگ است",
    },
    "too_complex": {
        "en": "the expression is too long or too deeply nested",
        "fa": "عبارت بیش از حد طولانی یا تودرتو است",
    },
    "syntax": {"en": "the expression is not valid", "fa": "عبارت معتبر نیست"},
    "unsupported": {
        "en": "the expression uses something the calculator does not support",
        "fa": "عبارت شامل چیزی است که ماشین‌حساب پشتیبانی نمی‌کند",
    },
}


@dataclass(frozen=True)
class RenderedNumber:
    """`text`: canonical ASCII, ungrouped (machine-friendly, e.g. for eval `calc_values`).
    `approximate`: the shown digits are rounded. `exact`: exact form (`"1/3"`, full
    integer digits) or None when the value itself is only approximate."""

    text: str
    approximate: bool
    exact: str | None


def render_number(value: CalcValue) -> RenderedNumber:
    if value.exact is not None:
        return _render_exact(value.exact)
    exact_binary = Decimal(value.approx)  # exact value of the float, no repr noise
    rounded = _round_sig(exact_binary)
    return RenderedNumber(_decimal_text(rounded), approximate=rounded != exact_binary, exact=None)


def _render_exact(frac: Fraction) -> RenderedNumber:
    exact = fraction_text(frac)
    if frac.denominator == 1:
        digits = len(exact.lstrip("-"))
        if digits <= MAX_FULL_INTEGER_DIGITS:
            return RenderedNumber(exact, approximate=False, exact=exact)
        rounded = _round_sig(Decimal(frac.numerator))
        return RenderedNumber(_decimal_text(rounded), approximate=True, exact=exact)
    with localcontext() as ctx:
        ctx.prec = SIGNIFICANT_DIGITS + 30  # enough to tell "terminates within 12" apart
        quotient = Decimal(frac.numerator) / Decimal(frac.denominator)
    rounded = _round_sig(quotient)
    approximate = Fraction(rounded) != frac
    return RenderedNumber(_decimal_text(rounded), approximate=approximate, exact=exact)


def _round_sig(value: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = SIGNIFICANT_DIGITS
        ctx.rounding = ROUND_HALF_EVEN
        return +value


def _decimal_text(value: Decimal) -> str:
    """Fixed notation in a human range, else `m e±k`; no trailing zeros, no `-0`."""
    if value.is_zero():
        return "0"
    magnitude = abs(value)
    if _FIXED_RANGE[0] <= magnitude < _FIXED_RANGE[1]:
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    mantissa, _, exponent = format(value.normalize(), "E").partition("E")
    if "." in mantissa:
        mantissa = mantissa.rstrip("0").rstrip(".")
    return f"{mantissa}e{int(exponent):+d}"


def fraction_text(frac: Fraction) -> str:
    """`p/q` (or `p`) for any size: chunked conversion sidesteps the 4300-digit limit."""
    num = _int_text(frac.numerator)
    return num if frac.denominator == 1 else f"{num}/{_int_text(frac.denominator)}"


def _int_text(n: int) -> str:
    if n < 0:
        return "-" + _int_text(-n)
    chunk = 10**1000
    if n < chunk:
        return str(n)
    parts: list[str] = []
    while n:
        n, rem = divmod(n, chunk)
        parts.append(str(rem))
    return parts[-1] + "".join(p.zfill(1000) for p in reversed(parts[:-1]))


def localize_number(text: str, lang: str) -> str:
    """Canonical ASCII → display form: grouping, and Persian digits/marks for `fa`.

    Scientific form becomes `m × 10^k`: an `e` would read as a letter in Persian text.
    """
    mantissa, sep, exponent = text.partition("e")
    shown = _group(mantissa, "٬" if lang == "fa" else ",")
    if sep:
        shown = f"{shown} × 10^{int(exponent)}"
    return to_persian_digits(shown) if lang == "fa" else shown


def _group(number: str, separator: str) -> str:
    sign = "-" if number.startswith("-") else ""
    whole, dot, frac = number.lstrip("-").partition(".")
    if len(whole) > 3:
        head = len(whole) % 3 or 3
        groups = [whole[:head]] + [whole[i : i + 3] for i in range(head, len(whole), 3)]
        whole = separator.join(groups)
    return f"{sign}{whole}{dot}{frac}"


def _prefix(label: str, lang: str) -> str:
    label = label.strip()
    if not label:
        return ""
    if lang != "fa" and label[0].isascii():
        label = label[0].upper() + label[1:]
    return f"{label}: "


def format_result_line(expression: str, label: str, value: CalcValue, lang: str) -> str:
    """`Average speed (km/h): 180 / 2.5 = 72` · `1/3 ≈ 0.333333333333 (exact: 1/3)`."""
    rendered = render_number(value)
    relation = "≈" if rendered.approximate else "="
    line = f"{_prefix(label, lang)}{expression} {relation} {localize_number(rendered.text, lang)}"
    if (
        rendered.approximate
        and rendered.exact is not None
        and "/" in rendered.exact
        and len(rendered.exact) <= MAX_EXACT_FRACTION_CHARS
    ):
        exact = to_persian_digits(rendered.exact) if lang == "fa" else rendered.exact
        line += f" (مقدار دقیق: {exact})" if lang == "fa" else f" (exact: {exact})"
    return line


def error_text(code: str, detail: str, lang: str) -> str:
    """English keeps the evaluator's specific detail; Persian uses a localized sentence."""
    if lang == "fa":
        return _ERROR_TEXT.get(code, _ERROR_TEXT["syntax"])["fa"]
    return detail or _ERROR_TEXT.get(code, _ERROR_TEXT["syntax"])["en"]


def format_error_line(expression: str, label: str, code: str, detail: str, lang: str) -> str:
    word = "خطا" if lang == "fa" else "error"
    return f"{_prefix(label, lang)}{expression} → {word}: {error_text(code, detail, lang)}"
