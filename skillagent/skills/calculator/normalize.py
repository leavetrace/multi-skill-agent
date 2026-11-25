"""Deterministic text → expression normalization for the calculator.

This is what lets pure expressions skip the LLM entirely (the "direct path"): Persian
digits, typographic operators, thousands separators and percent signs are all cheap,
exact string rewrites. Anything that needs understanding (number words, word problems)
is left for the model.
"""

from __future__ import annotations

import re

from skillagent.core.language import ZWNJ, normalize_persian, to_ascii_digits
from skillagent.skills.calculator.evaluator import (
    CONSTANT_NAMES,
    FUNCTION_NAMES,
    CalculatorError,
    check_expression,
)

__all__ = ["MAX_DIRECT_TEXT_CHARS", "looks_like_expression", "strip_cues", "to_expression"]

# Longer text is never treated as a pure expression (prose, or an attack on the regexes);
# the evaluator's own limit is 500 characters after normalization.
MAX_DIRECT_TEXT_CHARS = 2_000

_SYMBOLS = str.maketrans(
    {
        "×": "*", "✕": "*", "✖": "*", "·": "*", "∙": "*", "⋅": "*", "∗": "*",
        "÷": "/", "∕": "/", "⁄": "/",
        "−": "-", "–": "-", "—": "-", "‐": "-", "‑": "-", "﹣": "-", "－": "-",
        "＋": "+", "﹢": "+",
        "٪": "%", "﹪": "%", "％": "%",
        "،": ",", "（": "(", "）": ")",
        "²": "**2", "³": "**3",
    }
)  # fmt: skip

_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)"
_TIMES_LETTER = re.compile(r"(?<=\d)\s*[xX]\s*(?=[\d.(])")  # "3 x 4" (not "0x10"-style hex)
_PERCENT_WORD = re.compile(rf"({_NUMBER})\s*درصد")
_PERCENT_OF = re.compile(rf"({_NUMBER})\s*%\s*(?:of|از)\s*", re.IGNORECASE)
# A `%` not followed by an operand is a percent sign; "17 % 5" stays modulo.
_POSTFIX_PERCENT = re.compile(rf"({_NUMBER})\s*%(?!\s*[\w(.])")
_SQRT_SYMBOL = re.compile(rf"([√∛])\s*(\(|{_NUMBER}|[A-Za-z_]\w*)")
_GROUPED_NUMBER = re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?![\d,])")
_TOKEN = re.compile(
    r"(?P<space>\s*)(?:"
    r"(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
    r"|(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"|(?P<op>\*\*|//|[-+*/%,])"
    r"|(?P<open>\()|(?P<close>\))"
    r"|(?P<other>\S))"
)
_ALLOWED_CHARS = re.compile(r"[0-9A-Za-z_+\-*/%().,\s]+")
_IDENTIFIER = re.compile(r"(?<![\w.])[A-Za-z_]\w*")
_HAS_OPERATION = re.compile(r"(?:[\w).]\s*(?:\*\*|//|[-+*/%]))|(?:[A-Za-z_]\w*\s*\()")

_SP = rf"[\s{ZWNJ}]*"  # Persian phrases are typed with a space, a ZWNJ or nothing
_MI = rf"می{_SP}"
_LEADING_CUE = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"calculate|compute|evaluate|solve|what\s+is|what's|whats|how\s+much\s+is"
    rf"|حساب{_SP}کن|محاسبه{_SP}کن|حاصل|مقدار"
    r")(?![^\W\d_])\s*[:：]?\s*",  # cue must not run into a letter ("calculated")
    re.IGNORECASE,
)
# Applied after whitespace is collapsed to single spaces, and anchored on one optional
# space instead of `\s*` runs: adjacent unbounded quantifiers made this pattern cubic.
_TRAILING_CUE = re.compile(
    rf"(?:^|\s)(?:(?:را|رو)\s)?(?:"
    rf"حساب{_SP}کن|محاسبه{_SP}کن"
    rf"|چند{_SP}(?:{_MI}شود|{_MI}شه|است|هست)|چنده"
    rf"|چقدر{_SP}(?:{_MI}شود|{_MI}شه|است|هست)|چقدره"
    r")$"
)
_TRAILING_PUNCT = " =?؟!"


def strip_cues(text: str) -> str:
    """Remove polite/question framing around an expression: "what is 2+2?" → "2+2",
    «۲+۲ چند می‌شود؟» → «۲+۲». Persian cues are mostly trailing verbs, so both ends are
    checked; the loop handles combinations such as a cue followed by `=` and `?`."""
    current = re.sub(r"\s+", " ", normalize_persian(text)).strip()
    for _ in range(4):
        stripped = current.rstrip(_TRAILING_PUNCT)
        stripped = _TRAILING_CUE.sub("", stripped).rstrip(_TRAILING_PUNCT)
        stripped = _LEADING_CUE.sub("", stripped).strip()
        if stripped == current:
            break
        current = stripped
    return current


def to_expression(text: str) -> str:
    """Rewrite user notation into the evaluator's Python-style syntax (no evaluation)."""
    s = to_ascii_digits(normalize_persian(text)).translate(_SYMBOLS).replace("^", "**")
    s = re.sub(r"\s+", " ", s).strip()
    s = _TIMES_LETTER.sub("*", s)
    s = _PERCENT_WORD.sub(r"\1%", s)
    s = _PERCENT_OF.sub(r"(\1/100)*", s)
    s = _POSTFIX_PERCENT.sub(r"(\1/100)", s)
    s = _SQRT_SYMBOL.sub(_expand_root, s)
    s = _remove_thousands_separators(s)
    return _insert_implicit_multiplication(s)


def looks_like_expression(text: str) -> bool:
    """True only for text that *is* a calculation: whitelisted characters and names, at
    least one operation, and parseable by the evaluator. Conservative on purpose: a
    false positive would answer a word problem with a wrong number; a false negative only
    costs one LLM call."""
    if len(text) > MAX_DIRECT_TEXT_CHARS:
        return False
    expr = to_expression(text)
    if not expr or not _ALLOWED_CHARS.fullmatch(expr):
        return False
    allowed_names = FUNCTION_NAMES | CONSTANT_NAMES
    if any(name not in allowed_names for name in _IDENTIFIER.findall(expr)):
        return False
    if not _HAS_OPERATION.search(expr):
        return False
    try:
        check_expression(expr)
    except CalculatorError as exc:
        # too_complex is still an expression: the user gets the limit message, no LLM call.
        return exc.code not in ("syntax", "unsupported")
    return True


def _expand_root(match: re.Match[str]) -> str:
    fn = "sqrt" if match.group(1) == "√" else "cbrt"
    operand = match.group(2)
    return f"{fn}(" if operand == "(" else f"{fn}({operand})"


def _remove_thousands_separators(s: str) -> str:
    """Drop grouping commas in `2,340` / `1,000,000`, but never inside a function call's
    parentheses, where `max(1,234)` is two arguments, not one thousand-something."""
    in_call = _function_call_mask(s)
    return _GROUPED_NUMBER.sub(
        lambda m: m.group(0) if in_call[m.start()] else m.group(0).replace(",", ""), s
    )


def _function_call_mask(s: str) -> list[bool]:
    """For each index: is the innermost enclosing `(` a function call's parenthesis?"""
    mask = [False] * (len(s) + 1)
    stack: list[bool] = []
    last = ""  # last non-space character, tracked so the scan stays linear
    for i, ch in enumerate(s):
        if ch == "(":
            stack.append(last.isalnum() or last == "_")
        elif ch == ")" and stack:
            stack.pop()
        mask[i] = bool(stack) and stack[-1]
        if not ch.isspace():
            last = ch
    return mask


def _insert_implicit_multiplication(s: str) -> str:
    """`2(3+4)` → `2*(3+4)`, `(1+2)(3+4)` → `(1+2)*(3+4)`, `2pi` → `2*pi`.

    Token-based so `1e5` stays a literal and `sqrt(` stays a call. Whitespace between
    tokens is kept (collapsed to one space) so the shown expression matches the input.
    """
    out: list[str] = []
    prev: str | None = None  # "value" (number, constant, ')') or None
    for m in _TOKEN.finditer(s):
        kind = m.lastgroup
        token = m.group(kind) if kind else ""
        name_is_constant = kind == "name" and token in CONSTANT_NAMES
        starts_operand = kind in ("num", "open") or kind == "name"
        if prev == "value" and starts_operand and not (kind == "num" and out and out[-1] != ")"):
            out.append("*")
        elif m.group("space") and out:
            out.append(" ")
        out.append(token)
        prev = "value" if kind in ("num", "close") or name_is_constant else None
    return "".join(out).strip()
