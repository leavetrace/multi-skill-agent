# WP7b — README, Dockerfile and release checks (deadline day; no live LLM calls)

You are a **senior engineer and technical writer**. The README is graded directly ("documentation quality, architectural thinking") and must cover every mandatory item of the brief. All facts already exist in the repo; your job is to turn them into a clear, honest, well-structured README that a reviewer can follow on a fresh Windows machine, plus an optional minimal Dockerfile. **Today is the delivery deadline: aim to finish in about 75 minutes.** No prior conversation context exists.

## 0. Read first
`docs/REQUIREMENTS.md` (R1–R23 and assumptions A1–A8: the README must satisfy R13–R20) · `docs/ARCHITECTURE.md` · `docs/DECISIONS.md` (all ADRs; ADR-026–029 are the newest) · `docs/CONTRACTS.md` v1.4 (skim) · every `docs/handoffs/*_report.md` (measured numbers live there) · `docs/handoffs/WP0_persian_scores.md`, `WP3_samples_groq_scores.md` · `eval/README.md` · `skillagent/cli.py` (real commands and flags) · `.env.example` · `CLAUDE.md` and `agent_prompts/` (AI-usage disclosure)

Branch `docs/readme`, worktree `.worktrees/wp7b`, from `main`.
**You own (delegated by the architect for this WP, ADR-030):** `README.md`, `Dockerfile`, `.dockerignore`, `docs/handoffs/WP7b_report.md`. This delegation is an explicit exception to CLAUDE.md §2 ("README belongs to the architect"); it is not a conflict, so proceed. Don't change code.

## 1. README structure (in this order; concise, scannable, tables over prose)
1. **Title + one-paragraph summary**: what it is, the 4 skills, ≤2 per request, EN/FA, LangGraph, free-tier model, CLI.
2. **Quick start (Windows PowerShell first, then macOS/Linux)**: prerequisites (Python 3.12, uv, a free Groq key), clone, `uv sync`, copy `.env.example` to `.env` and set `GROQ_API_KEY`, `uv run python -m skillagent doctor`, REPL, `ask` examples (EN, FA, chain, parallel), `--file`/`--out`/`--trace`/`--json`, `graph --mermaid`, tests (`uv run pytest -q`), eval runner usage. Note the Windows RTL rendering caveat and the `--out` workaround. Docker usage if you add the Dockerfile.
3. **Model and provider (R9, R10):** Groq free tier, `qwen/qwen3.8-27b`, 27B dense (≤35B), how it was chosen (WP0 table: Groq vs Gemma, ADR-026), free-tier limits that shaped the design (8K tokens/min, 200K tokens/day), alternate provider via config.
4. **Graph architecture (R3, R4, R11, R14):** the Mermaid diagram (generate it: `uv run python -m skillagent graph --mermaid`), node-by-node table, the validated plan (`RoutingDecision`, rules V1–V8), router fast path, why plan-then-execute with `Send` (ADR-001) and the alternatives rejected.
5. **Multi-skill strategy (R5, R6):** chain vs parallel by declared data dependency, one mechanism; the 2-skill limit enforced in code; dropped-intents notice; examples.
6. **Fallback and ambiguity (R7):** the ARCHITECTURE §5 matrix, degraded mode, clarification without memory (A6).
7. **Calculator (R2):** tool call → safe AST evaluator, exact arithmetic, DoS guards, direct path, no eval/sympify.
8. **Prompt engineering (R15):** per skill: design and rationale (from the prompt files' comment blocks and WP3 report). **Improvement example(s):** (a) the router prompt compaction (WP4b: 4 732 → ~2 293 provider tokens, dev D01–D20 plan 19/20 → 20/20, p50 latency 36.5 s → 0.92 s; why: Groq's 8K tokens/min limit); (b) leave a clearly marked placeholder `<!-- WP7a-EXAMPLE -->` for the summarizer/translator v1 → v2 example, which the architect fills after the owner's review.
9. **Evaluation (R16):** the dataset design (`eval/README.md` test-set table: 15 cases, categories), split discipline (dev/test, frozen test set), metrics definitions, how to run. **Results:** leave a marked placeholder `<!-- TEST-RESULTS -->` for the test-set table (the architect runs it today); include the measured dev numbers that exist (WP4b router dev check, WP6b partial baseline) clearly labelled as dev. Include the owner's native-speaker Persian scores (WP0 probes and WP3 samples on Groq).
10. **Persian handling (R8, R17):** normalization, language hints vs `response_language`, instruction-language rule, Finglish, payload extraction, Persian digits and punctuation, ZWNJ rules in prompts, native-speaker review loop, known weaknesses (from the owner's scores).
11. **Scalability (O1, O2):** what actually breaks at 20+ skills (ARCHITECTURE §1 table), the nine code-enforced mechanisms (§7), and the measured evidence: graph node count 4/10/20/24 (WP5), router prompt tokens vs N (re-measure offline now with the compact prompt: `Router.build_messages` with synthetic skills, as WP5's scalability test does), BM25 recall@k (WP4).
12. **Known limitations and production gaps (R18).**
13. **Assumptions (R19):** A1–A8 plus later ones (e.g. Groq free tier qualifies; summary language rule; clarification is terminal).
14. **Development process and AI usage (R20, R22):** multi-agent workflow (architect + WP agents, worktree per WP, conventional commits, review by reproduction), pointers to `CLAUDE.md`, `agent_prompts/`, `docs/`.
15. **Repository layout.**

Rules: measured numbers only, each with its source file; label dev vs test; no marketing language; English only except Persian examples (correct ی/ک, ZWNJ). Never include API keys, account ids or the owner's personal details.

## 2. Dockerfile (optional, a plus)
Minimal: `python:3.12-slim`, install uv, `uv sync --frozen --no-dev`, entrypoint `uv run python -m skillagent`; `.env` passed at runtime (`--env-file .env`), never copied into the image (`.dockerignore` excludes `.env`, `.worktrees`, `eval/reports/raw`). If Docker is installed on this machine, build it once and record the result; otherwise say it was not built.

## 3. Release checks (run and report, no live calls)
- `uv run pytest -q`, ruff check/format, `uv run python -m skillagent --help`, `doctor` offline, `graph --mermaid`.
- Fresh-clone test: `git clone` this repo into a temp folder, `uv sync`, `uv run pytest -q`; follow your Quick start literally and fix the README where it is wrong.
- Grep the tracked files for secrets and personal data: `gsk_`, `AIza`, `org_0`, email addresses other than the placeholder.

## 4. Acceptance
- [ ] Every R13–R20 item has a README section; a short checklist table maps R-ids to sections.
- [ ] Placeholders `<!-- WP7a-EXAMPLE -->` and `<!-- TEST-RESULTS -->` present for the architect.
- [ ] Release checks pass; report in `docs/handoffs/WP7b_report.md`; 3–6 Conventional Commits on `docs/readme`.
