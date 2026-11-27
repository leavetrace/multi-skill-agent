# WP7b Handoff Report — README, Dockerfile and release checks

- **Agent session date:** 2026-11-27
- **Branch / worktree:** `docs/readme` / `.worktrees/wp7b` (Mode A, owner's Windows 11 PC, uv 0.13.10)
- **Final commit:** the `docs(handoff)` commit that adds this file (see §11)
- **Status:** complete. Two release checks did not fully pass: `ruff format --check` (1 architect-owned file, §7) and the Docker build (not run, daemon not running, §6.3). Both are reported, not fixed: the files are outside my ownership, and starting Docker Desktop on the owner's machine was not mine to decide.

## 1. Summary
I wrote the root `README.md` (15 sections in the order of the WP7b outline, plus an R-id checklist). It is built only from facts already in the repo, each measured number citing its source file. Dev numbers are labelled as dev or partial. The two placeholders `<!-- WP7a-EXAMPLE -->` (README §7.3) and `<!-- TEST-RESULTS -->` (README §8 "Test-set results") are in place for the architect. The scalability table was **re-measured offline** with the compact router prompt (4/10/20/24 skills → 1 879 / 2 043 / 1 934 / 1 934 estimated tokens). I added a minimal `Dockerfile` and `.dockerignore`. The release checks pass on the branch and in a fresh clone (1 292 tests, ruff check clean, CLI commands work), with the two exceptions listed under Status. The secret scan found no real key or account id; it did find the owner's Windows username in `agent_prompts/README.md`.

## 2. Deliverables
| Path | Purpose |
|---|---|
| `README.md` | Graded README: quick start (Windows first), model/provider, graph, multi-skill, fallback, calculator, prompt engineering, evaluation, Persian, scalability, limitations, assumptions, AI usage, layout, R-checklist |
| `Dockerfile` | `python:3.12-slim` + uv 0.13.10 (`COPY --from=ghcr.io/astral-sh/uv:0.13.10`), `uv sync --frozen --no-dev`, non-root user, entrypoint `uv run --no-sync python -m skillagent` |
| `.dockerignore` | Excludes `.env`/`.env.*` (keeps `.env.example`), `.git`, `.worktrees`, `.venv`, caches, `eval/reports/raw`, tests, spikes, docs, agent_prompts |
| `docs/handoffs/WP7b_report.md` | This report |

## 3. How to verify (commands actually run, Windows 11)
On the branch (`.worktrees/wp7b`):
```
uv run pytest -q                         → 1292 passed in 46.79s
uv run ruff check .                      → All checks passed!
uv run ruff format --check .             → 1 file would be reformatted, 102 files already formatted
                                           (tests\unit\llm\test_gateway.py: no newline at end of file)
uv run python -m skillagent --help       → commands ask, graph, doctor
uv run python -m skillagent ask --help   → --file/-f, --out/-o, --trace, --json
uv run python -m skillagent doctor       → provider groq, model qwen/qwen3.8-27b, key present (masked),
                                           "Configuration OK (offline check …)", exit 0
uv run python -m skillagent graph --mermaid   → identical to the Mermaid embedded in README §3
uv run python -m skillagent ask "What is 15% of 2,480?" --trace   → (15/100)*2480 = 372 (fast path)
uv run python -m skillagent ask "۲۵ درصد از ۸۴۰ چند می‌شود؟" --json --out <scratch>/fa.md
                                         → "(25/100)*840 = ۲۱۰", llm_calls 0
uv run pytest tests/scalability tests/unit/router -q -s   → tables in README §10
docker build -t skillagent:wp7b .        → failed: cannot connect to dockerDesktopLinuxEngine (daemon not running)
```
Fresh-clone test, following README §1 (Windows PowerShell) literally in a scratch folder:
```
git clone --branch docs/readme "<repo folder>" multi-skill-agent   → de7f93c
cd multi-skill-agent; uv sync                                       → OK
Copy-Item .env.example .env; uv run python -m skillagent doctor     → "api key: missing … set GROQ_API_KEY in the .env
                                                                       file …", exit 2 (expected without a key)
uv run pytest -q                                                    → 1292 passed in 22.89s
uv run ruff check .                                                 → All checks passed!
uv run python -m skillagent graph --mermaid                         → prints the diagram (no key needed)
uv run python -m eval.runner --set dev --dry-run                    → 40 cases listed, "0 calls made", exit 0
uv run python -m skillagent ask "2+2"                               → exit 2, key required even for the fast path
```
The Quick start puts the key step before any `ask`, so no README change was needed. No `.env` with a real key was created in the clone.

Secret and personal-data scan (`git grep` on tracked files of this branch):
```
gsk_[A-Za-z0-9]{8,}  → only fakes: gsk_abcdefghijklmnopqrstuvwxyz1234 (redaction test), gsk_test_000…, gsk_1234567890abcd
AIza                 → only fakes in tests (AIza-test-key-…, AIzaSyREALLOOKING1234wxyz in a masking test)
org_[0-9A-Za-z]{6,}  → only fakes in tests (org_abc123XYZ, org_01abcdefFAKE9999, …); no org_0… value
e-mail addresses     → skillagent-dev@example.invalid (6), noreply@anthropic.com (1), a1@b2.com (2, a Persian digit test)
commit identities    → all 146 commits on all branches: skillagent-dev <skillagent-dev@example.invalid>
owner's local path   → agent_prompts/README.md:10 contains `C:\Users\<owner's Windows username>\Desktop\…` (see §8)
```

## 4. Contract deviations / proposals
None. No code was changed.

## 5. Decisions made within my scope
- **Clone URL is `<repository-url>`.** The GitHub repo does not exist yet (ADR-019), so I didn't guess the URL. The architect replaces it before the push.
- **Prerequisites list uv, not a separate Python install.** uv installs the pinned Python 3.12 from `.python-version`. The fresh-clone `uv sync` confirmed this.
- **Mermaid embedded exactly as generated** (ADR-028 answer 2), including LangGraph's frontmatter, so the README matches `graph --mermaid` byte for byte. I couldn't preview GitHub's renderer offline (§7).
- **Scalability numbers.** I re-measured `tests/scalability` (bilingual weather query, short synthetic cards) on `main`'s compact prompt and also quote the router unit-test series (realistic ~74-token cards: 1 877 → 2 349 → 3 104; Top-K 2 029 at 20). Both are labelled as estimated tokens, with WP4b's measured provider ratio of ≈ 1.22×. WP5's old table (v1 prompt, 3 775…) is not used.
- **Dev numbers kept apart from test numbers.** I quote the router-only WP4b smoke (20/20, 40/40) and the partial end-to-end baseline (D01–D10 10/10) in a table titled "not reportable accuracy", each with its scope and source. The WP0 probe score is labelled as model aptitude on a draft prompt.
- **Improvement example (a)** uses only ADR-024/027 and WP4b numbers. The D16 fix is described as the one v1 miss.
- **Assumptions A9–A14** are later decisions already recorded in ADRs or WP reports (G2 reply language, mild-ambiguity default, data-not-instructions, translator reject vs summarizer truncate, chained pass-through, section order). None are new.
- **Limit defaults come from the code, not ARCHITECTURE §7:** the request deadline is 90 s (`config.py`, `.env.example`; ARCHITECTURE says 60 s), and per-step timeouts are 20–30 s from the skill budgets.
- **Docker:** `--no-sync` in the entrypoint, so `uv run` never pulls the dev group into a `--no-dev` image. `UV_PYTHON_DOWNLOADS=never` uses the image's Python. A non-root user. `.env` is excluded from the build context, not only from `COPY`.
- **AI-usage section** names the tools (Claude Code agents), the roles, and the artifacts. It contains no personal details.

## 6. Measured results
### 6.1 Release checks
| Check | Result |
|---|---|
| `uv run pytest -q` (branch / fresh clone) | 1 292 passed / 1 292 passed |
| `uv run ruff check .` | clean (both) |
| `uv run ruff format --check .` | **1 file would be reformatted**: `tests/unit/llm/test_gateway.py` lacks a final newline (architect commit `cad93ce`) |
| `--help`, `ask --help`, `doctor` offline, `graph --mermaid` | OK |
| Fresh clone following the Quick start | OK; no README fix needed |
| Secret / personal-data grep | no real secrets; owner's Windows username in `agent_prompts/README.md:10` |
| Docker build | **not run**: Docker CLI 29.4.3 is installed, but the Docker Desktop daemon was not running |

### 6.2 Scalability re-measurement (offline, 2026-11-27, `main` = `23fed3d` code)
| N skills | graph nodes | selector | cards shown | router system prompt (est.) | all cards (est.) |
|---|---|---|---|---|---|
| 4 | 11 | AllSkills | 4 | 1 879 | 1 879 |
| 10 | 17 | AllSkills | 10 | 2 043 | 2 043 |
| 20 | 27 | BM25TopK | 6 | 1 934 | 2 287 |
| 24 | 31 | BM25TopK | 6 | 1 934 | 2 391 |

Router unit tests: BM25 recall@3/6/10 = 0.975 (EN@6 1.00, FA@6 0.95). Prompt with real-size cards: 4 → 10 → 20 = 1 877 → 2 349 → 3 104 estimated tokens; Top-K at 20 = 2 029.

### 6.3 Docker
Not built. To build it: start Docker Desktop, then run `docker build -t skillagent .` and `docker run --rm --env-file .env skillagent ask "2+2"` from the repo root. The base-image tag `ghcr.io/astral-sh/uv:0.13.10` was not verified to exist. If it is missing, use `uv:0.13` or `pip install uv==0.13.10`.

## 7. Known issues, limitations, risks
- **`ruff format --check` fails on `main`** because of a missing newline at the end of `tests/unit/llm/test_gateway.py`. It's a one-line architect fix (`uv run ruff format tests/unit/llm/test_gateway.py`). I didn't touch it: it's WP1-owned, and the WP7b prompt says not to change code.
- **Docker image unbuilt** (§6.3).
- **Mermaid rendering on GitHub not previewed.** The block uses LangGraph's frontmatter `config` and `<p>` labels. If GitHub renders it badly, removing the frontmatter lines (`---` … `---`) is a safe edit.
- **README placeholders** need the architect: `<!-- WP7a-EXAMPLE -->`, `<!-- TEST-RESULTS -->` and `<repository-url>` (2×). The status line under the title says the test-set numbers are filled in at §8; update it once they are.
- **README facts that may change today:** the test count (1 292), "137 commits on `main` before this README", and the WP7a row of the WP table (`feat/prompts-v2`). Re-check them after the final merges.
- The Persian example `ask` prompts in the Quick start (translation and chain) were **not** run live (0-call rule). Only the two fast-path examples were run, offline.

## 8. Questions for the architect
1. `agent_prompts/README.md:10` contains the owner's Windows user path. Replace it with `cd "<project folder>"` before the public push?
2. Should `ARCHITECTURE.md` §7 be updated to the 90 s request deadline that the code and `.env.example` use (it says 60 s)? The README uses 90 s.
3. Keep the Mermaid frontmatter as generated, or strip it for GitHub (§7)?

## 9. Files touched outside my ownership
None. `README.md`, `Dockerfile`, `.dockerignore` and this report were delegated to WP7b (ADR-030).

## 10. Dependencies added
None.

## 11. Commits
```
de7f93c docs(readme): add README covering run, architecture, prompts, eval, Persian and scaling
3a90cec chore(docker): add minimal Dockerfile and .dockerignore
(+ docs(handoff): add WP7b report)
```

## 12. Live LLM calls made
**0.** `doctor` ran offline only. The two `ask` examples took the arithmetic fast path (`llm_calls: 0`, verified with `--json`).
