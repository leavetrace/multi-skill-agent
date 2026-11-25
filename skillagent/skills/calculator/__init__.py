"""Calculator skill: the model writes expressions, a safe exact evaluator computes them.

Only `SPEC` is exported; the evaluator, normalizer, formatter and tool parsing live in
their own modules so each can be tested (and reviewed for safety) in isolation.
"""

from __future__ import annotations

from skillagent.skills.base import RouterExample, SkillSpec
from skillagent.skills.calculator.skill import BUDGET, run

__all__ = ["SPEC"]

SPEC = SkillSpec(
    name="calculator",
    description=(
        "Computes exact numeric answers: arithmetic, percentages, powers/roots, logs, "
        "trigonometry (radians) and word problems, via a safe evaluator tool."
    ),
    when_to_use=(
        "Any arithmetic expression or numeric result to compute, in any notation: "
        "'(3+4)*2^3', '۱۲ × ۳٫۵', '2,340 + 15%'.",
        "Percentages, averages, unit rates and other word problems that need a number "
        "(e.g. 'average speed of 180 km in 2.5 h').",
        "Numbers or operations written in words, English or Persian: 'twenty five times "
        "four', «بیست و پنج ضرب در چهار، منهای دوازده»، «جذر ۱۴۴ به‌علاوه ۳ به توان ۲».",
        "کاربر محاسبهٔ عدد می‌خواهد: «حساب کن»، «چند می‌شود؟»، «چقدر است؟»، درصد، میانگین، "
        "توان، جذر، فاکتوریل یا یک مسئلهٔ کلامی.",
        "Functions: sqrt, cbrt, log/ln, sin/cos/tan (radians; degrees are converted), "
        "factorial, comb, perm, gcd, lcm, min, max, round.",
    ),
    when_not_to_use=(
        "Explaining a math concept, proof or formula without computing a value "
        "('what is a derivative?', «مشتق یعنی چه؟») → general_chat.",
        "Translating or spelling out a number or a text that contains numbers "
        "('translate 1250 to Persian words') → translator.",
        "Summarizing a text that merely contains numbers → summarizer.",
    ),
    examples=(
        RouterExample(prompt="What is 15% of 2,480?", plan="calculator(user)"),
        RouterExample(
            prompt="If a train travels 180 km in 2.5 hours, what is its average speed?",
            plan="calculator(user)",
        ),
        RouterExample(prompt="«بیست و پنج ضرب در چهار، منهای دوازده»", plan="calculator(user)"),
        RouterExample(prompt="«جذر ۱۴۴ به‌علاوه ۳ به توان ۲ چند می‌شود؟»", plan="calculator(user)"),
        RouterExample(
            prompt="Calculate 1250 * 1.09, then translate the result into Persian.",
            plan="calculator(user) -> translator(s1, target_language=fa)",
        ),
    ),
    params_model=None,
    accepts=frozenset({"text", "number"}),
    output_kind="number",
    requires_payload=False,
    budget=BUDGET,
    run=run,
    order=30,
)
