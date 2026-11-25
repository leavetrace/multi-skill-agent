"""Safe, exact arithmetic evaluator: the calculator's real "tool" (ADR-004).

The model never computes numbers; it only writes expressions, and this module evaluates
them. Untrusted input is parsed with `ast.parse(mode="eval")` and walked against an
explicit whitelist *before* any arithmetic runs, so a forbidden construct anywhere in the
tree is rejected without evaluating cheap-looking parts first. Nothing here executes
code: no builtin code evaluators, no `compile` of user text, no CAS string parsers.

Numbers are exact `Fraction`s for as long as possible (`0.1 + 0.2 == 3/10`); only
genuinely irrational operations (trig, logs, non-integer powers) fall back to floats.
Evaluation is an explicit post-order stack walk rather than recursion, so the Python
call stack never depends on the user's input. Every operation that can blow up in time or
memory (powers, factorials, big products) is size-checked before it is computed.
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

__all__ = [
    "CONSTANT_NAMES",
    "FUNCTION_NAMES",
    "MAX_AST_NODES",
    "MAX_EXPONENT",
    "MAX_EXPRESSION_LENGTH",
    "MAX_FACTORIAL_N",
    "MAX_NESTING_DEPTH",
    "MAX_RESULT_DIGITS",
    "CalcValue",
    "CalculatorError",
    "ErrorCode",
    "check_expression",
    "evaluate",
]

# --- limits (module constants, read at call time so tests/config can patch them) -------
MAX_EXPRESSION_LENGTH = 500
MAX_AST_NODES = 300
MAX_NESTING_DEPTH = 40
MAX_EXPONENT = 10_000
MAX_RESULT_DIGITS = 5_000
MAX_FACTORIAL_N = 1_000
MAX_ROUND_DIGITS = 100  # round(x, n): |n| bound; larger n is never meaningful for display

# Snap |trig result| below this to 0: sin(pi) is 1.2e-16 only because pi is a float.
_TRIG_ZERO_EPS = 1e-15
_MAX_EXACT_ROOT = 12  # x ** (p/q) is tried exactly for q <= this
_LOG10_2 = math.log10(2)

ErrorCode = str  # one of: syntax, unsupported, div_zero, domain, too_large, too_complex


class CalculatorError(Exception):
    """Evaluation failed. `code` is machine-readable; `message` is a short English detail.

    `syntax`/`unsupported` mean the *expression* is wrong (worth one repair by the model);
    `div_zero`/`domain`/`too_large` are genuine mathematical answers; `too_complex` is a
    resource guard. User-facing localized text is produced by `formatting.py`.
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CalcValue:
    """Result of `evaluate`. `exact` is set iff the value is known exactly."""

    exact: Fraction | None
    approx: float
    is_exact: bool

    @classmethod
    def of(cls, value: Fraction | float) -> CalcValue:
        if isinstance(value, Fraction):
            return cls(exact=value, approx=_fraction_to_float_or_inf(value), is_exact=True)
        return cls(exact=None, approx=value, is_exact=False)


Num = Fraction | float

# --- whitelist ---------------------------------------------------------------------------

_BIN_OPS: dict[type[ast.operator], str] = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
    ast.Pow: "**",
}
_UNARY_OPS: dict[type[ast.unaryop], str] = {ast.UAdd: "+", ast.USub: "-"}

_FRIENDLY_NAMES: dict[type[ast.AST], str] = {
    ast.Attribute: "attribute access (a.b)",
    ast.Subscript: "indexing/subscripts (a[b])",
    ast.ListComp: "comprehensions",
    ast.SetComp: "comprehensions",
    ast.DictComp: "comprehensions",
    ast.GeneratorExp: "comprehensions",
    ast.Lambda: "lambda functions",
    ast.Compare: "comparisons",
    ast.BoolOp: "boolean operators (and/or)",
    ast.keyword: "keyword arguments",
    ast.Starred: "starred arguments",
    ast.JoinedStr: "f-strings",
    ast.FormattedValue: "f-strings",
    ast.List: "lists",
    ast.Tuple: "tuples",
    ast.Set: "sets",
    ast.Dict: "dicts",
    ast.IfExp: "conditional expressions",
    ast.NamedExpr: "assignment expressions (:=)",
    ast.Await: "await",
    ast.Yield: "yield",
    ast.YieldFrom: "yield",
    ast.Slice: "slices",
    ast.BitXor: "the ^ operator (use ** for powers)",
    ast.BitAnd: "bitwise operators",
    ast.BitOr: "bitwise operators",
    ast.LShift: "bitwise operators",
    ast.RShift: "bitwise operators",
    ast.Invert: "bitwise operators",
    ast.MatMult: "the @ operator",
    ast.Not: "the not operator",
}

_CONSTANTS: dict[str, float] = {"pi": math.pi, "e": math.e, "tau": math.tau}
CONSTANT_NAMES: frozenset[str] = frozenset(_CONSTANTS)

_LITERAL = re.compile(r"(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?")


# --- public API --------------------------------------------------------------------------


def check_expression(expr: str) -> ast.Expression:
    """Parse and whitelist-validate without evaluating.

    Raises `CalculatorError` with `too_complex`, `syntax` or `unsupported`. Used by
    `looks_like_expression` so classification never pays for (or is fooled by) the
    arithmetic itself.
    """
    if len(expr) > MAX_EXPRESSION_LENGTH:
        raise CalculatorError(
            "too_complex", f"expression is longer than {MAX_EXPRESSION_LENGTH} characters"
        )
    if _bracket_depth(expr) > MAX_NESTING_DEPTH:
        raise CalculatorError(
            "too_complex", f"parentheses are nested deeper than {MAX_NESTING_DEPTH} levels"
        )
    if not expr.strip():
        raise CalculatorError("syntax", "empty expression")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        detail = "" if exc.msg == "invalid syntax" else f" ({exc.msg})"
        raise CalculatorError("syntax", f"invalid syntax{detail}") from None
    except (ValueError, RecursionError, MemoryError):  # null bytes / parser limits
        raise CalculatorError("too_complex", "expression could not be parsed safely") from None
    _validate(tree)
    return tree


def evaluate(expr: str) -> CalcValue:
    """Evaluate one arithmetic expression exactly where possible."""
    tree = check_expression(expr)
    source = expr.strip()
    value = _evaluate_tree(tree, source)
    return CalcValue.of(value)


# --- validation --------------------------------------------------------------------------


def _bracket_depth(expr: str) -> int:
    """Max bracket nesting, computed on the raw string so CPython's recursive parser is
    never handed pathological input."""
    depth = deepest = 0
    for ch in expr:
        if ch in "([{":
            depth += 1
            deepest = max(deepest, depth)
        elif ch in ")]}":
            depth = max(0, depth - 1)
    return deepest


def _validate(tree: ast.Expression) -> None:
    """Whitelist walk over the whole tree (iterative). Rejects before any computation."""
    nodes = 0
    stack: list[tuple[ast.AST, bool]] = [(tree.body, False)]
    while stack:
        node, is_func_name = stack.pop()
        nodes += 1
        if nodes > MAX_AST_NODES:
            raise CalculatorError(
                "too_complex", f"expression has more than {MAX_AST_NODES} elements"
            )
        if isinstance(node, ast.Constant):
            _validate_constant(node)
        elif isinstance(node, ast.Name):
            _validate_name(node, is_func_name)
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in _BIN_OPS:
                raise CalculatorError("unsupported", f"not allowed: {_describe(node.op)}")
            stack += [(node.right, False), (node.left, False)]
        elif isinstance(node, ast.UnaryOp):
            if type(node.op) not in _UNARY_OPS:
                raise CalculatorError("unsupported", f"not allowed: {_describe(node.op)}")
            stack.append((node.operand, False))
        elif isinstance(node, ast.Call):
            if node.keywords:
                raise CalculatorError("unsupported", "keyword arguments are not allowed")
            if not isinstance(node.func, ast.Name):
                raise CalculatorError(
                    "unsupported", f"only plain function calls are allowed: {_describe(node.func)}"
                )
            # Push args first so the function name (the likelier offender) is checked first.
            stack += [(arg, False) for arg in reversed(node.args)]
            stack.append((node.func, True))
            if node.func.id in _FUNCTIONS:
                _check_arity(node.func.id, len(node.args))
        else:
            raise CalculatorError("unsupported", f"not allowed: {_describe(node)}")


def _validate_constant(node: ast.Constant) -> None:
    value = node.value
    if type(value) is bool or not isinstance(value, int | float):
        kind = {str: "strings", bytes: "bytes", complex: "complex numbers"}.get(
            type(value), f"{type(value).__name__} literals"
        )
        raise CalculatorError("unsupported", f"not allowed: {kind}")


def _validate_name(node: ast.Name, is_func_name: bool) -> None:
    name = node.id
    if is_func_name:
        if name not in _FUNCTIONS:
            raise CalculatorError("unsupported", f"function {name!r} is not allowed")
    elif name not in _CONSTANTS:
        if name in _FUNCTIONS:
            raise CalculatorError("syntax", f"{name} is a function; call it like {name}(x)")
        raise CalculatorError(
            "unsupported", f"name {name!r} is not allowed (constants: pi, e, tau)"
        )


def _describe(node: ast.AST) -> str:
    return _FRIENDLY_NAMES.get(type(node), type(node).__name__)


# --- evaluation (iterative post-order) ---------------------------------------------------


def _evaluate_tree(tree: ast.Expression, source: str) -> Num:
    results: dict[int, Num] = {}
    stack: list[tuple[ast.AST, bool]] = [(tree.body, False)]
    while stack:
        node, children_done = stack.pop()
        if isinstance(node, ast.Constant):
            results[id(node)] = _literal(node, source)
        elif isinstance(node, ast.Name):
            results[id(node)] = _CONSTANTS[node.id]
        elif not children_done:
            stack.append((node, True))
            stack += [(child, False) for child in reversed(_operands(node))]
        elif isinstance(node, ast.BinOp):
            left, right = results.pop(id(node.left)), results.pop(id(node.right))
            results[id(node)] = _check(_binop(type(node.op), left, right))
        elif isinstance(node, ast.UnaryOp):
            operand = results.pop(id(node.operand))
            results[id(node)] = -operand if isinstance(node.op, ast.USub) else operand
        elif isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name)  # guaranteed by _validate
            args = [results.pop(id(arg)) for arg in node.args]
            results[id(node)] = _check(_call(node.func.id, args))
    return results[id(tree.body)]


def _operands(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.BinOp):
        return [node.left, node.right]
    if isinstance(node, ast.UnaryOp):
        return [node.operand]
    if isinstance(node, ast.Call):
        return list(node.args)
    raise AssertionError(f"unvalidated node {type(node).__name__}")  # pragma: no cover


def _literal(node: ast.Constant, source: str) -> Num:
    """Literal → exact Fraction from its *source text*, so `0.1` is exactly 1/10."""
    value = node.value
    if isinstance(value, int):
        return Fraction(value)
    text = (ast.get_source_segment(source, node) or repr(value)).replace("_", "")
    match = _LITERAL.fullmatch(text)
    if not match or not (match.group(1) or match.group(2)):
        return _check(float(value))  # e.g. repr like 'inf' from an overflowing literal
    whole, frac, exp = match.group(1), match.group(2) or "", int(match.group(3) or 0)
    digits = (whole + frac).lstrip("0") or "0"
    scale = exp - len(frac)
    if len(digits) + max(scale, 0) > MAX_RESULT_DIGITS or -scale > MAX_RESULT_DIGITS:
        raise CalculatorError("too_large", f"number literal {text!r} is too large")
    return Fraction(int(digits)) * Fraction(10) ** scale


# --- arithmetic --------------------------------------------------------------------------


def _check(value: Num) -> Num:
    """Uniform post-condition for every intermediate result."""
    if isinstance(value, Fraction):
        limit_bits = MAX_RESULT_DIGITS / _LOG10_2
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > limit_bits:
            raise CalculatorError("too_large", f"result exceeds {MAX_RESULT_DIGITS} digits")
        return value
    if math.isnan(value):
        raise CalculatorError("domain", "result is not a number")
    if math.isinf(value):
        raise CalculatorError("too_large", "result overflows floating point")
    return value


def _to_float(value: Num) -> float:
    if isinstance(value, float):
        return value
    try:
        return float(value)
    except OverflowError:
        raise CalculatorError("too_large", "number too large for an approximation") from None


def _fraction_to_float_or_inf(value: Fraction) -> float:
    try:
        return float(value)
    except OverflowError:
        return math.inf if value > 0 else -math.inf


def _binop(op: type[ast.operator], left: Num, right: Num) -> Num:
    if op is ast.Pow:
        return _power(left, right)
    if op in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
        raise CalculatorError("div_zero", "division by zero")
    if isinstance(left, Fraction) and isinstance(right, Fraction):
        return _exact_binop(op, left, right)
    a, b = _to_float(left), _to_float(right)
    try:
        if op is ast.Add:
            return a + b
        if op is ast.Sub:
            return a - b
        if op is ast.Mult:
            return a * b
        if op is ast.Div:
            return a / b
        if op is ast.FloorDiv:
            return float(a // b)
        return a % b
    except OverflowError:
        raise CalculatorError("too_large", "result overflows floating point") from None


def _exact_binop(op: type[ast.operator], a: Fraction, b: Fraction) -> Fraction:
    if op is ast.Mult:
        _guard_digits(_digits(a) + _digits(b), "product")
    if op is ast.Add:
        return a + b
    if op is ast.Sub:
        return a - b
    if op is ast.Mult:
        return a * b
    if op is ast.Div:
        return a / b
    if op is ast.FloorDiv:
        return Fraction(a // b)
    return a % b


def _digits(value: Fraction) -> float:
    """log10 of the larger of |numerator| and denominator: the size estimate the power
    and product guards use (`math.log10` accepts huge ints, so no `str()` is needed)."""
    biggest = max(abs(value.numerator), value.denominator)
    return math.log10(biggest) if biggest > 1 else 0.0


def _guard_digits(estimated: float, what: str) -> None:
    if estimated > MAX_RESULT_DIGITS + 1:
        raise CalculatorError("too_large", f"{what} would exceed {MAX_RESULT_DIGITS} digits")


def _power(base: Num, exponent: Num) -> Num:
    if isinstance(exponent, Fraction) and exponent.denominator == 1:
        n = exponent.numerator
        if base == 0 and n < 0:
            raise CalculatorError("div_zero", "zero raised to a negative power")
        if isinstance(base, Fraction):
            return _exact_power(base, n)
        try:
            return math.pow(base, n)
        except OverflowError:
            raise CalculatorError("too_large", "power overflows floating point") from None
    # Non-integer exponent: real-valued only for a non-negative base.
    if base < 0:
        raise CalculatorError(
            "domain", "negative base with a non-integer exponent (use cbrt for cube roots)"
        )
    if base == 0 and exponent < 0:
        raise CalculatorError("div_zero", "zero raised to a negative power")
    if (
        isinstance(base, Fraction)
        and isinstance(exponent, Fraction)
        and exponent.denominator <= _MAX_EXACT_ROOT
        and (root := _exact_root(base, exponent.denominator)) is not None
    ):
        return _exact_power(root, exponent.numerator)  # 8 ** (2/3) == 4 exactly
    try:
        return math.pow(_to_float(base), _to_float(exponent))
    except OverflowError:
        raise CalculatorError("too_large", "power overflows floating point") from None


def _exact_power(base: Fraction, n: int) -> Fraction:
    # Trivial bases are exempt from the exponent limit: 1 ** 10**9 costs nothing.
    if base == 1 or base == 0:
        return Fraction(1) if n == 0 else base
    if base == -1:
        return Fraction(1 if n % 2 == 0 else -1)
    if abs(n) > MAX_EXPONENT:
        raise CalculatorError("too_large", f"exponent {n} exceeds the limit of {MAX_EXPONENT}")
    _guard_digits(_digits(base) * abs(n), "power")
    return base**n


# --- functions ---------------------------------------------------------------------------


def _as_int(value: Num, fn: str) -> int:
    if isinstance(value, Fraction) and value.denominator == 1:
        return value.numerator
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise CalculatorError("domain", f"{fn}() needs whole numbers")


def _exact_root(value: Fraction, k: int) -> Fraction | None:
    """Exact k-th root of a rational if it is a perfect power, else None."""
    p, q = value.numerator, value.denominator
    rp, rq = _int_root(abs(p), k), _int_root(q, k)
    if rp is None or rq is None:
        return None
    return Fraction(-rp if p < 0 else rp, rq)


def _int_root(n: int, k: int) -> int | None:
    if k == 2:
        r = math.isqrt(n)
        return r if r * r == n else None
    r = round(n ** (1 / k)) if n.bit_length() < 1000 else _int_kth_root(n, k)
    for cand in (r - 1, r, r + 1):
        if cand >= 0 and cand**k == n:
            return cand
    return None


def _int_kth_root(n: int, k: int) -> int:
    """Integer Newton k-th root for numbers too big for float pow."""
    x = 1 << ((n.bit_length() + k - 1) // k)
    while True:
        y = ((k - 1) * x + n // x ** (k - 1)) // k
        if y >= x:
            return x
        x = y


def _sqrt(x: Num) -> Num:
    if x < 0:
        raise CalculatorError("domain", "square root of a negative number")
    if isinstance(x, Fraction) and (root := _exact_root(x, 2)) is not None:
        return root
    return math.sqrt(_to_float(x))


def _cbrt(x: Num) -> Num:
    if isinstance(x, Fraction) and (root := _exact_root(x, 3)) is not None:
        return root
    return math.cbrt(_to_float(x))


def _exact_log(x: Fraction, base: Fraction) -> Fraction | None:
    """Integer k with base**k == x (so log(8, 2) is exactly 3), else None."""
    if base <= 0 or base == 1 or x <= 0:
        return None
    try:
        k = round(_ln(x) / _ln(base))
    except (ValueError, ZeroDivisionError):  # pragma: no cover - guarded above
        return None
    if abs(k) > MAX_EXPONENT or _digits(base) * abs(k) > MAX_RESULT_DIGITS + 1:
        return None
    return Fraction(k) if base**k == x else None


def _ln(x: Num) -> float:
    """Natural log that also works for huge exact rationals (no float overflow)."""
    if isinstance(x, Fraction):
        return math.log(x.numerator) - math.log(x.denominator)
    return math.log(x)


def _log(x: Num, base: Num | None = None) -> Num:
    if x <= 0:
        raise CalculatorError("domain", "logarithm of zero or a negative number")
    if base is None:
        if x == 1:
            return Fraction(0)
        return _ln(x)
    if base <= 0 or base == 1:
        raise CalculatorError("domain", "logarithm base must be positive and not 1")
    if isinstance(x, Fraction) and isinstance(base, Fraction):
        exact = _exact_log(x, base)
        if exact is not None:
            return exact
    return _ln(x) / _ln(base)


def _float_fn(fn: Callable[[float], float], name: str) -> Callable[[Num], float]:
    def wrapped(x: Num) -> float:
        try:
            return fn(_to_float(x))
        except ValueError:
            raise CalculatorError("domain", f"{name}() is undefined for this value") from None
        except OverflowError:
            raise CalculatorError("too_large", f"{name}() result overflows") from None

    return wrapped


def _trig(fn: Callable[[float], float], name: str) -> Callable[[Num], float]:
    inner = _float_fn(fn, name)

    def wrapped(x: Num) -> float:
        result = inner(x)
        return 0.0 if abs(result) < _TRIG_ZERO_EPS else result

    return wrapped


def _round(x: Num, ndigits: Num | None = None) -> Num:
    """Round half away from zero (what people expect from a calculator; Python's
    built-in round uses banker's rounding: round(2.5) == 2)."""
    n = 0 if ndigits is None else _as_int(ndigits, "round")
    if abs(n) > MAX_ROUND_DIGITS:
        raise CalculatorError("too_large", f"round() precision is limited to {MAX_ROUND_DIGITS}")
    exact = x if isinstance(x, Fraction) else Fraction(x)
    scale = Fraction(10) ** n
    scaled = abs(exact) * scale
    rounded = math.floor(scaled + Fraction(1, 2))
    result = Fraction(rounded if exact >= 0 else -rounded) / scale
    return result if isinstance(x, Fraction) else float(result)


def _floor(x: Num) -> Num:
    return Fraction(math.floor(x)) if isinstance(x, Fraction) else float(math.floor(x))


def _ceil(x: Num) -> Num:
    return Fraction(math.ceil(x)) if isinstance(x, Fraction) else float(math.ceil(x))


def _factorial(x: Num) -> Fraction:
    n = _as_int(x, "factorial")
    if n < 0:
        raise CalculatorError("domain", "factorial of a negative number")
    _guard_n(n, "factorial")
    return Fraction(math.factorial(n))


def _comb(n: Num, k: Num) -> Fraction:
    ni, ki = _as_int(n, "comb"), _as_int(k, "comb")
    if ni < 0 or ki < 0:
        raise CalculatorError("domain", "comb() needs non-negative whole numbers")
    _guard_n(ni, "comb")
    return Fraction(math.comb(ni, ki))


def _perm(n: Num, k: Num | None = None) -> Fraction:
    ni = _as_int(n, "perm")
    ki = None if k is None else _as_int(k, "perm")
    if ni < 0 or (ki is not None and ki < 0):
        raise CalculatorError("domain", "perm() needs non-negative whole numbers")
    _guard_n(ni, "perm")
    return Fraction(math.perm(ni, ki))


def _guard_n(n: int, fn: str) -> None:
    if n > MAX_FACTORIAL_N:
        raise CalculatorError("too_large", f"{fn}() is limited to n <= {MAX_FACTORIAL_N}")


def _gcd(*args: Num) -> Fraction:
    return Fraction(math.gcd(*(_as_int(a, "gcd") for a in args)))


def _lcm(*args: Num) -> Fraction:
    ints = [_as_int(a, "lcm") for a in args]
    _guard_digits(sum(abs(i).bit_length() for i in ints) * _LOG10_2, "lcm")
    return Fraction(math.lcm(*ints))


def _hypot(*args: Num) -> Num:
    if all(isinstance(a, Fraction) for a in args):
        squares = sum((Fraction(a) ** 2 for a in args), Fraction(0))
        _check(squares)
        if (root := _exact_root(squares, 2)) is not None:
            return root
    return math.hypot(*(_to_float(a) for a in args))


def _abs(x: Num) -> Num:
    return abs(x)


def _min(*args: Num) -> Num:
    return min(args)


def _max(*args: Num) -> Num:
    return max(args)


# name -> (implementation, min_args, max_args or None for variadic)
_FUNCTIONS: dict[str, tuple[Callable[..., Num], int, int | None]] = {
    "sqrt": (_sqrt, 1, 1),
    "cbrt": (_cbrt, 1, 1),
    "abs": (_abs, 1, 1),
    "round": (_round, 1, 2),
    "floor": (_floor, 1, 1),
    "ceil": (_ceil, 1, 1),
    "exp": (_float_fn(math.exp, "exp"), 1, 1),
    "ln": (_log, 1, 1),
    "log": (_log, 1, 2),
    "log10": (lambda x: _log(x, Fraction(10)), 1, 1),
    "log2": (lambda x: _log(x, Fraction(2)), 1, 1),
    "sin": (_trig(math.sin, "sin"), 1, 1),
    "cos": (_trig(math.cos, "cos"), 1, 1),
    "tan": (_trig(math.tan, "tan"), 1, 1),
    "asin": (_float_fn(math.asin, "asin"), 1, 1),
    "acos": (_float_fn(math.acos, "acos"), 1, 1),
    "atan": (_float_fn(math.atan, "atan"), 1, 1),
    "sinh": (_float_fn(math.sinh, "sinh"), 1, 1),
    "cosh": (_float_fn(math.cosh, "cosh"), 1, 1),
    "tanh": (_float_fn(math.tanh, "tanh"), 1, 1),
    "degrees": (_float_fn(math.degrees, "degrees"), 1, 1),
    "radians": (_float_fn(math.radians, "radians"), 1, 1),
    "factorial": (_factorial, 1, 1),
    "comb": (_comb, 2, 2),
    "perm": (_perm, 1, 2),
    "gcd": (_gcd, 1, None),
    "lcm": (_lcm, 1, None),
    "min": (_min, 1, None),
    "max": (_max, 1, None),
    "hypot": (_hypot, 1, None),
}
FUNCTION_NAMES: frozenset[str] = frozenset(_FUNCTIONS)


def _check_arity(name: str, count: int) -> None:
    _, lo, hi = _FUNCTIONS[name]
    if count < lo or (hi is not None and count > hi):
        expected = str(lo) if lo == hi else f"{lo} or more" if hi is None else f"{lo} to {hi}"
        raise CalculatorError("syntax", f"{name}() takes {expected} argument(s), {count} given")


def _call(name: str, args: list[Num]) -> Num:
    return _FUNCTIONS[name][0](*args)
