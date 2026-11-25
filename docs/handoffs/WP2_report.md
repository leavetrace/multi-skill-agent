# WP2 Handoff Report — Calculator skill: safe evaluator, tool call, exact arithmetic

- **Agent session date:** 2026-11-25
- **Branch / worktree:** `feat/calculator` / delivery **Mode B** (cloud workspace; cloned from `.worktrees/main.bundle`, base `main` = `1914418`). No worktree was created in the owner's folder.
- **Final commit:** the `docs(handoff)` commit that adds this file, on top of code commit `4a4954e` (see §11).
- **Status:** complete
- **Test platform:** Linux (Python 3.12.3 via `uv`), **not Windows**. Please re-run `uv run pytest -q` on Windows after import.

## 1. Summary
The calculator is a real tool pipeline: the model only translates language into expressions through a forced `evaluate` tool call, and a whitelisted, iterative `ast` evaluator computes every number exactly with `Fraction` (`0.1 + 0.2` is exactly `3/10`). Pure expressions (including Persian digits, `×`, `÷`, `^`, `√`, `%`, `15% of 2,480`, thousands separators) take a **direct path with zero LLM calls**. Weak tool calling degrades to a JSON-mode fallback; syntax/unsupported expressions get exactly one repair; mathematical errors (`1/0`, `sqrt(-1)`) are reported as answers. Output is formatted deterministically in English or Persian, and the label the model writes can never change a reported number. 603 new offline tests (852 total) pass, including a security suite where every hostile input is rejected in under 1 ms. During self-review I found and fixed a ReDoS in my own Persian cue regex (21 s on 2 000 spaces → linear).

## 2. Deliverables
| Path | Purpose |
|---|---|
| `skillagent/skills/calculator/evaluator.py` | `evaluate(expr) -> CalcValue`, `check_expression`, `CalculatorError(code, message)`, limits as module constants, `FUNCTION_NAMES`, `CONSTANT_NAMES` |
| `skillagent/skills/calculator/normalize.py` | `to_expression`, `looks_like_expression`, `strip_cues`, `MAX_DIRECT_TEXT_CHARS` |
| `skillagent/skills/calculator/formatting.py` | `render_number`, `format_result_line`, `format_error_line`, `localize_number`, `error_text`, `fraction_text` |
| `skillagent/skills/calculator/tool.py` | `EVALUATE_TOOL`, `Calculation`, `CalculationPlan` (JSON fallback schema), `parse_response`, `parse_calculations` |
| `skillagent/skills/calculator/skill.py` | `async run()`: direct → tool → JSON fallback → evaluate → one repair → format; `BUDGET` |
| `skillagent/skills/calculator/__init__.py` | `SPEC` with improved bilingual router card (5 cues, 3 don'ts, 5 examples incl. the chained one) |
| `skillagent/prompts/calculator/v1.md` | System prompt (English, Persian examples) |
| `tests/unit/calculator/` | 603 offline tests: evaluator (308), security (124), normalize (71), formatting (41), skill/FakeLLM (39), tool (15), SPEC/prompt (5) |

## 3. How to verify (commands actually run, with real output excerpts)
Import on the owner's machine (Mode B):
```
git fetch .worktrees/wp2.bundle feat/calculator:feat/calculator
```
Commands run in the workspace (Linux):
```
$ uv run pytest -q
852 passed in 2.45s
$ uv run pytest -q tests/unit/calculator
603 passed in 1.12s
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
50 files already formatted
$ grep -rn "eval(\|exec(\|sympify" skillagent/ ; echo "exit=$?"
exit=1                      # no matches at all (not even docstrings); also enforced by
                            # tests/unit/calculator/test_security.py::test_no_eval_exec_or_sympify_in_the_package
$ uv run pytest -q tests/unit/calculator/test_security.py --durations=5
0.10s call  ...test_normalizer_is_linear_on_adversarial_text[repeated_cue_word]
0.07s call  ...[question_marks]
0.06s call  ...[parens]
124 passed in 0.58s
```
Example outputs (from `tests/unit/calculator/test_skill.py`, all asserted):
```
(3+4)*2^3 / 7                     -> (3+4)*2**3 / 7 = 8                  [direct, 0 LLM calls]
What is 15% of 2,480?             -> (15/100)*2480 = 372                 [direct, 0 LLM calls]
۱۲ × ۳٫۵ چند می‌شود؟  (fa)          -> 12 * 3.5 = ۴۲                        [direct, 0 LLM calls]
1/3                               -> 1/3 ≈ 0.333333333333 (exact: 1/3)
train word problem (tool)         -> Average speed (km/h): 180/2.5 = 72
same, fa                          -> میانگین سرعت (کیلومتر بر ساعت): 180/2.5 = ۷۲
«بیست و پنج ضرب در چهار، منهای دوازده» -> حاصل: 25*4 - 12 = ۸۸            [tool]
10000/3 (fa)                      -> 10000/3 ≈ ۳٬۳۳۳٫۳۳۳۳۳۳۳۳ (مقدار دقیق: ۱۰۰۰۰/۳)
10/(5-5)                          -> 10/(5-5) → error: division by zero   [no repair]
```

## 4. Contract deviations / proposals
No frozen contract was changed. Items within the WP2 prompt's latitude that the architect should know about:
1. **User message shape (additive to WP2 §5.2).** Not chained: `<task>{instruction}</task>` + `<request>{text}</request>`. Chained: `<request>{instruction}</request>` + `<previous_result>{text}</previous_result>`. Why: a non-chained `text` is the whole user prompt and may hold several intents; the router's instruction says which part is the calculator's. Our own delimiter tags are stripped from user data first.
2. **`meta` has extra keys** besides `path`, `calculations`, `prompt_version`: `llm_calls`, `repairs`, and `reason` on rejected outputs (`no_calculation` | `invalid_expressions`). Each calculation also carries `error` (code or null). `prompt_version` is `null` on the direct path (no prompt used).
3. **`meta.calculations[].value` is canonical ASCII, ungrouped** (`"372"`, `"0.333333333333"`, `"7.88657867365e+374"`), and `exact` is the exact form (`"1/3"`, full integer digits). This is what WP6's `calc_values: ["397.8"]` should compare against. Display text is localized separately.
4. **Proposal for WP4:** the router fast path should call `normalize.strip_cues` + `normalize.looks_like_expression` (or at least use `evaluator.FUNCTION_NAMES` / `CONSTANT_NAMES`) instead of a separate regex, so the router's "pure expression" and the calculator's direct path can never disagree.
5. **Observation:** `OpenAICompatGateway` always sends `tools` and ignores `ProviderProfile.supports_tools`; the calculator checks the flag itself and goes straight to JSON mode when it is `False`. WP0 should set the flag from measurements.

## 5. Decisions made within my scope
- **Iterative evaluation, validation before computation.** The whole tree is whitelist-checked (iteratively) before any arithmetic, then evaluated with an explicit post-order stack. Alternatives: recursive visitor (simpler, but stack depth depends on input). Reason: no user input can influence Python recursion depth.
- **Literal parsing from source text** with a size check *before* building the `Fraction` (`1e100000` → `too_large` without computing 10^100000).
- **Exact where cheap, beyond the required list:** `x ** (p/q)` for perfect powers (`8**(2/3) == 4`, `4**0.5 == 2`), `cbrt` of perfect cubes, `hypot` of Pythagorean triples, `log/log10/log2` of exact integer powers (`log(8, 2) == 3`, `log10(1000) == 3`), `ln(1) == 0`. Trivial bases `0`, `1`, `-1` are exempt from the exponent limit (`1 ** 10**6` costs nothing).
- **Power-size estimate** uses `log10(max(|num|, den)) · |exp| ≤ 5000` (the spec's formula). The bit-length estimate I first used overestimated by ~20% and wrongly rejected `10**4999` (fixed in `decd505`).
- **`round` is half away from zero** (`round(2.5) == 3`), not Python's banker's rounding, because that is what calculator users expect. Documented in code.
- **`floor`/`ceil`/`round` of an approximate (float) input stay approximate**; exact inputs give exact results.
- **Trig noise snapping:** `|sin/cos/tan result| < 1e-15` → `0` (`sin(pi)` shows `0`, not `1.2e-16`).
- **Wrong arity is `syntax`** (repairable), checked during validation so `check_expression` is complete.
- **`=` vs `≈`:** `≈` whenever the displayed digits are not exactly the computed value (so `tan(pi/4) ≈ 1`, `sqrt(2) ≈ 1.41421356237`). `(exact: p/q)` is appended only for non-integers when it is ≤ 40 chars.
- **Number display:** 12 significant digits via `decimal` (never `repr(float)`); fixed notation for 1e-6 ≤ |x| < 1e15, else `m × 10^k` (an `e` would read as a letter in Persian). Exact integers up to 100 digits are shown in full; longer ones in scientific form with `≈` while `meta.exact` keeps every digit. Chunked int→str conversion avoids Python's 4300-digit limit.
- **Persian formatting:** Persian digits, `٫` decimal mark, and **`٬` (U+066C) thousands separator for every number with ≥ 4 integer digits** (the prompt allowed "٬ or none"; I chose `٬` for readability). The expression stays ASCII. English uses `,`.
- **Error text:** English shows the evaluator's specific detail (e.g. `exponent 387420489 exceeds the limit of 10000`); Persian shows a localized sentence per error code.
- **Normalization rules:** thousands commas are removed only outside function-call parentheses (`max(1,234)` stays two arguments); `3 x 4` → `3*4` (hex literals aren't supported by this path); `x% of y` / «x درصد از y» are handled deterministically; postfix `17%` → `(17/100)`, so `100 - 20%` = `99.8` (spec semantics, not a phone calculator's `80`); implicit multiplication is token-based (`1e5` stays a literal, `sqrt(` stays a call).
- **Direct path** tries `text`, then `instruction`, after `strip_cues`; it is skipped for candidates over 2 000 chars (defense in depth after the ReDoS fix). LLM-written expressions go through the same `to_expression` normalization (so `^`, `×`, `15%` from a model still work).
- **Label hygiene:** one line, ≤ 80 chars, anything after `=` dropped. The label is display text only; values always come from the evaluator (tested with a label of `"result is 5 = 5"`).
- **Fallback/repair error policy:** a tool-rejecting 400 (status 400 and "tool" in the message) or an unusable reply → JSON mode; other provider errors and a failed JSON fallback (`StructuredOutputError`) propagate, per the CONTRACTS runner rule. The repair call is best effort: if it fails with an `LLMError`, the original errors are reported instead of raising. Repaired expressions replace the failing ones by position.
- **`CalculatorError`** subclasses plain `Exception` (not `SkillAgentError`): it never leaves the skill; it is converted into output lines or a rejection.
- **Timeout fixture:** a daemon-thread runner (`within_timeout`, 2 s) instead of `signal.alarm` (absent on Windows) or a new `pytest-timeout` dependency.

## 6. Measured results
**Evaluator limits** (module constants in `evaluator.py`, read at call time; `MAX_DIRECT_TEXT_CHARS` is in `normalize.py`):
| Limit | Value | Error code |
|---|---|---|
| expression length | 500 chars | `too_complex` |
| AST nodes (expression nodes) | 300 | `too_complex` |
| bracket nesting depth (pre-parse scan) | 40 | `too_complex` |
| exponent magnitude | 10 000 (bases 0/±1 exempt) | `too_large` |
| estimated power size `log10(|base|)·exp` | ≤ 5 000 digits | `too_large` |
| integer/fraction result size (numerator and denominator) | ≤ 5 000 digits (checked after every exact op; products pre-checked) | `too_large` |
| `factorial` / `comb` / `perm` | n ≤ 1 000 | `too_large` |
| `round(x, n)` precision | \|n\| ≤ 100 | `too_large` |
| float overflow / NaN | — | `too_large` / `domain` |
| direct-path candidate text | 2 000 chars (longer → LLM path) | — |

**Security suite runtime** (Linux workspace, 2026-11-25):
- `test_security.py`: 124 tests, **0.58 s wall** in total. Slowest single test 0.10 s (ReDoS regression on a 60 000-char input).
- Worst single `evaluate()` call, max of 5 runs per case: **0.057 ms** over the 45 code-execution inputs; **0.583 ms** over the 23 resource-exhaustion inputs (`-` × 450 + `1`).
- Largest *legal* computations (evaluate + Persian formatting): `factorial(1000)` 0.42 ms, `10**4999` 0.80 ms, `2**10000 / 3**6000` 1.02 ms.
- Normalizer on adversarial text (after the fix): ≤ 62 ms for `to_expression` and ≤ 14 ms for `strip_cues` on 40 000–60 000-char inputs. **Before the fix**, the trailing-cue regex alone took **21 543 ms on a 2 002-char input** (2 000 spaces).

**Tests:** 603 calculator tests, 852 total, all passing. They include a property-style check over 150 random integer expressions (depth 4, `+ - * / **`, unary minus) whose expected values are built programmatically as `Fraction`s (no `eval` in tests).

**WP0 P4 prompts, offline classification only** (no model was called): `"What is 15% of 2,480?"` and `"(3+4)*2^3 / 7"` take the direct path (0 LLM calls, results 372 and 8). The other three (Persian number words, the train word problem, «جذر ۱۴۴ به‌علاوه ۳ به توان ۲») go to the LLM tool path, as intended.

## 7. Known issues, limitations, risks
- **Not run on Windows.** Tests ran on Linux only. Nothing in the code is platform-specific, and the timeout fixture is threading-based so it works on Windows, but this is unverified.
- **No live validation.** Tool-call reliability, JSON-fallback behaviour and prompt quality against the real free models are unmeasured (0 live calls; no `.env` in the cloud workspace).
- **Bidi display:** Persian lines mix an RTL label, an ASCII expression and Persian digits. I didn't add Unicode isolate/LRM marks, because terminal support for them varies. The owner should check how `میانگین سرعت (کیلومتر بر ساعت): 180/2.5 = ۷۲` renders in the Windows console (WP5's CLI may want to handle this).
- **Deliberate ambiguity choices:** `100 - 20%` = 99.8; `sqrt(1,000,000)` stays three arguments → `syntax` → not direct → the LLM writes it; `2 3` gets no implicit `*`.
- **Repair mapping is positional.** If a model returns repaired calculations in a different order, labels could pair with the wrong expression. Values are still correct for each expression shown.
- `meta.calculations[].exact` can be up to ~5 000 characters for huge exact integers, so a trace could get large.
- `strip_cues` covers common EN/FA cue phrasings, not every variant. Misses only cost an LLM call; they never cause a wrong number.

## 8. Questions for the architect
1. Should WP4's fast path reuse `strip_cues` + `looks_like_expression` (proposal §4.4)? If yes, WP4 imports from `skillagent.skills.calculator.normalize`; no new contract is needed beyond naming it.
2. Do you accept the `<task>` + `<request>` / `<previous_result>` message shape (§4.1)?
3. Persian thousands separator `٬` on every number with ≥ 4 integer digits: OK, or should Persian results be ungrouped? (Owner's Persian review.)
4. Should `CONTRACTS` record the calculator `meta` keys (§4.2–4.3) so WP5/WP6 can depend on them formally?

## 9. Files touched outside my ownership
- `tests/unit/skills_base/test_skills_scaffold.py` (WP1, 1 line + comment): `test_stub_runner` no longer parametrizes over `calculator`, because it asserted the stub's `[stub:calculator] …` output, which this WP replaces by design. The other three skills are still checked. WP3 will need the same change for its skills.

## 10. Dependencies added
None.

## 11. Commits
`git log --oneline main..HEAD` before the report commit:
```
4a4954e test(calculator): cover normalization, formatting, tool parsing, SPEC and skill flows
947daa0 test(calculator): cover evaluator correctness, random-expression property and security
475436e test(skills): exclude the implemented calculator from the stub-runner check
e41c993 fix(calculator): make cue stripping linear and cap direct-path input length
decd505 fix(calculator): use log10 size estimate for powers and keep huge exact values finite-safe
59f1f13 feat(calculator): add skill runner and bilingual router card
a596a56 feat(prompts): add calculator prompt v1
a762b5a feat(calculator): add evaluate tool spec and tolerant tool-call parsing
0eaacde feat(calculator): add deterministic EN/FA result formatting
b56d122 feat(calculator): normalize Persian digits, operator symbols, percent and separators
8c5eb48 feat(calculator): add safe exact AST evaluator with DoS limits
```
Plus `docs(handoff): add WP2 report` (12 commits in total).

## 12. Live LLM calls made
0 (no provider key available in the cloud workspace; the optional live check in WP2 §9 was not run).
