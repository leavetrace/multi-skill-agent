# CONTRACTS — v1.2 (FROZEN 2026-11-25; v1.1/v1.2 additive amendments)

> **Normative.** These are the interfaces every work package builds against. Names, fields and semantics here are binding.
> Implementation lives in `skillagent/` (WP1 creates it). If an agent believes a contract is wrong, it **must not change it unilaterally**: implement as specified, describe the problem in its handoff report under "Contract deviations / proposals", and the architect decides.
> Changes are versioned here (v1.1, …) with a changelog at the bottom.

Repo: `multi-skill-agent` · Python package: `skillagent` · Python 3.12 · managed by `uv`.

---

## 1. Core types — `skillagent/core/types.py`

```python
from typing import Annotated, Any, Literal
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

LangHint = Literal["fa", "en", "mixed", "unknown"]      # deterministic script-based hint
IOKind   = Literal["text", "number"]

# Output is ALWAYS ISO 639-1 (v1.1); 3-letter inputs (fas, per, eng…) are mapped to 639-1. BeforeValidator maps common names
# ("English", "Persian", "Farsi", "فارسی", "انگلیسی", "fr-FR") to codes via
# skillagent.core.language.normalize_lang_code; unmappable -> validation error.
LangCode = Annotated[str, BeforeValidator(normalize_lang_code), Field(pattern=r"^[a-z]{2,3}$")]

SKILL_NAMES = ("summarizer", "translator", "calculator", "general_chat")   # informational; registry is the truth

class UserRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw_text: str
    normalized_text: str          # normalize_persian(raw_text); digits NOT converted
    lang_hint: LangHint
    approx_tokens: int            # estimate_tokens(raw_text)

class PlanStep(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=r"^s[1-9][0-9]*$")       # "s1", "s2", ...
    skill: str                                       # canonicalized to a registry name by validator
    instruction: str = Field(min_length=1, max_length=300)   # restated sub-task; NEVER the payload
    input_from: str = "user"                         # "user" | id of an EARLIER step
    params: dict[str, Any] = Field(default_factory=dict)

class RoutingDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")
    response_language: LangCode                      # language of the user's instruction
    steps: list[PlanStep] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None        # in response_language
    dropped_intents: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=300)        # trace only; never sent to skills; >300 chars is TRUNCATED (v1.1), not rejected
    route_source: Literal["llm", "rule", "fallback"] = "llm"  # set by code after validation
```

### 1.1 `RoutingDecision` validation rules (model_validator, mode="after")

Validation **context** (optional): `RoutingDecision.model_validate(data, context={"registry": SkillRegistry, "max_skills": int})`.

| Rule | Needs context | Behaviour |
|---|---|---|
| V1 | no | `needs_clarification=True` ⇒ `clarification_question` non-empty; `steps` is cleared to `[]` |
| V2 | no | `needs_clarification=False` ⇒ `len(steps) ≥ 1` |
| V3 | no | step ids unique |
| V4 | no | `input_from` is `"user"` or the id of a step that appears **earlier** in the list (acyclic by construction) |
| V5 | registry | `skill` resolves case-/separator-insensitively (`"General Chat"`, `"general-chat"` → `general_chat`); unknown ⇒ error |
| V6 | registry | if `input_from` is a step X: `registry[X.skill].output_kind ∈ registry[skill].accepts`, else error |
| V7 | registry | if the spec has `params_model`: `params = params_model.model_validate(params).model_dump(exclude_none=True)` (extra keys ignored); invalid ⇒ error |
| V8 | max_skills | if `len(steps) > max_skills`: keep the first `max_skills` steps; for each removed step append its `instruction` to `dropped_intents`. Kept steps can only reference earlier steps, so they stay valid. |

Errors raise `pydantic.ValidationError` (so the router's repair loop can feed the message back to the LLM).

### 1.2 Skill I/O

```python
class SkillInput(BaseModel):            # the ONLY data a skill receives
    text: str                           # original user prompt, or the dependency step's output
    instruction: str
    params: dict[str, Any] = Field(default_factory=dict)
    response_language: LangCode
    is_chained: bool = False            # True when text is another skill's output

class SkillOutput(BaseModel):           # what a skill's run() returns
    status: Literal["ok", "rejected"]   # rejected = precondition not met (too short, missing target...)
    output: str                         # for "rejected": user-facing explanation in response_language
    output_kind: IOKind = "text"
    meta: dict[str, Any] = Field(default_factory=dict)   # e.g. {"expression": "...", "prompt_version": 2}

class SkillResult(BaseModel):           # produced by the graph's skill-node wrapper (WP5)
    step_id: str
    skill: str
    status: Literal["ok", "rejected", "error", "timeout", "skipped"]
    output: str = ""
    output_kind: IOKind = "text"
    error: str | None = None            # internal detail for trace; composer writes user-facing text
    meta: dict[str, Any] = Field(default_factory=dict)

class StepTask(BaseModel):              # LangGraph Send payload
    step: PlanStep
    skill_input: SkillInput
    deadline_monotonic: float           # absolute time.monotonic() deadline for the whole request

class TraceEvent(BaseModel):
    node: str                           # "preprocess" | "router" | "scheduler" | "skill:translator" | ...
    event: str                          # "start" | "end" | "retry" | "fallback" | "fast_path" | ...
    data: dict[str, Any] = Field(default_factory=dict)
    t_ms: float                         # ms since request start
```

### 1.3 Skill parameter models (`skillagent/skills/params.py`)

```python
class TranslatorParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    target_language: LangCode | None = None     # None ⇒ default rule: source fa → en, otherwise → fa
    source_language: LangCode | None = None

class SummarizerParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    length: Literal["short", "medium", "long"] | None = None
    format: Literal["paragraph", "bullets"] | None = None
    output_language: LangCode | None = None     # None ⇒ SkillInput.response_language
# calculator, general_chat: no params (params_model=None)
```

---

## 2. Skills — `skillagent/skills/base.py`

```python
class SkillBudget(BaseModel):
    max_input_tokens: int
    max_output_tokens: int
    timeout_s: float
    temperature: float

class RouterExample(BaseModel):
    prompt: str
    plan: str     # compact notation, e.g. 'summarizer(user) -> translator(s1, target_language=fa)'

@dataclass(frozen=True)
class SkillContext:
    llm: "LLMClient"
    settings: "Settings"
    prompts: "PromptLoader"

SkillRunner = Callable[[SkillInput, SkillContext], Awaitable[SkillOutput]]
# Runners raise exceptions for failures (wrapper maps them to error/timeout). They never catch-all silently.

@dataclass(frozen=True)
class SkillSpec:
    name: str                               # snake_case, unique
    description: str                        # one line for router card
    when_to_use: tuple[str, ...]            # bilingual cues (EN + FA)
    when_not_to_use: tuple[str, ...]        # disambiguation vs other skills
    examples: tuple[RouterExample, ...]
    params_model: type[BaseModel] | None
    accepts: frozenset[IOKind]              # kinds accepted when chained
    output_kind: IOKind
    requires_payload: bool                  # needs content to operate on (summarizer, translator)
    budget: SkillBudget
    run: SkillRunner
    order: int = 100                        # ordering in router cards
```

Fixed values for the 4 skills (stubs created by WP1, owners may refine text but not these fields):

| name | accepts | output_kind | requires_payload | params_model |
|---|---|---|---|---|
| summarizer | {text} | text | True | SummarizerParams |
| translator | {text, number} | text | True | TranslatorParams |
| calculator | {text, number} | number | False | None |
| general_chat | {text, number} | text | False | None |

## 3. Registry — `skillagent/core/registry.py`

```python
class SkillRegistry:
    def register(self, spec: SkillSpec) -> None        # DuplicateSkillError
    def get(self, name: str) -> SkillSpec               # canonicalizing lookup; UnknownSkillError
    def resolve(self, name: str) -> str | None          # canonical name or None
    def names(self) -> list[str]                        # sorted by (order, name)
    def specs(self) -> list[SkillSpec]
    def __contains__(self, name: str) -> bool
    def __len__(self) -> int

# skillagent/skills/catalog.py
def build_default_registry() -> SkillRegistry           # registers exactly the 4 product skills
```
The registry does **not** render prompts; router-card rendering belongs to the router (WP4).

## 4. LLM gateway — `skillagent/llm/`

```python
class ChatMessage(TypedDict, total=False):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str
    tool_calls: list[dict[str, Any]]

class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]          # JSON Schema

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]           # parsed; {} if unparsable
    raw_arguments: str

class LLMUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

class LLMResponse(BaseModel):
    text: str                           # <think> blocks already stripped
    tool_calls: list[ToolCall] = []
    usage: LLMUsage = LLMUsage()
    latency_ms: float
    model: str
    attempts: int                       # 1 + retries
    finish_reason: str | None = None    # v1.1: "stop" | "length" | "tool_calls" | provider-specific

T = TypeVar("T", bound=BaseModel)

class StructuredResult(BaseModel, Generic[T]):
    value: T
    response: LLMResponse
    repairs: int

class LLMClient(Protocol):
    async def complete(self, messages: list[ChatMessage], *, temperature: float = 0.0,
                       max_tokens: int = 1024, json_mode: bool = False,
                       tools: list[ToolSpec] | None = None, tool_choice: str | None = None,
                       timeout_s: float | None = None, purpose: str = "") -> LLMResponse: ...

    async def complete_structured(self, messages: list[ChatMessage], schema: type[T], *,
                                  validation_context: dict[str, Any] | None = None,
                                  max_repairs: int = 1, temperature: float = 0.0,
                                  max_tokens: int = 512, timeout_s: float | None = None,
                                  purpose: str = "") -> StructuredResult[T]: ...
```
- `tool_choice`: `None` (auto) | `"required"` | a tool name (forces that tool).
- `purpose`: free label ("router", "skill:translator", "repair") used in logs/trace and by `FakeLLM` matching.
- Implementations: `OpenAICompatGateway` (`skillagent/llm/gateway.py`) and `FakeLLM` (`skillagent/testing/fake_llm.py`).
- v1.1 module placement: protocol + models in `skillagent/llm/types.py`; the shared parse→validate→repair loop in `skillagent/llm/structured.py` (used by both implementations); all re-exported from `skillagent.llm`.
- v1.1 behaviour notes (binding for callers):
  - **One gateway per event loop.** Its semaphore/lock bind to the first loop that waits on them. Create it inside the `asyncio.run(...)` it serves and reuse it for everything in that loop (CLI REPL session, one eval run). Never share it across separate `asyncio.run()` calls.
  - The gateway has **no overall deadline**: worst case ≈ (1 + `llm_max_retries`) × `timeout_s` + backoff. Callers that need a deadline (the WP5 skill-node wrapper) must wrap calls in `asyncio.wait_for`; cancellation is safe.
  - A `retry-after` > 60 s raises `LLMRateLimitError` immediately (usually an exhausted daily quota).
  - If a structured reply has `finish_reason == "length"`, the repair message says it was cut off at the token limit.
  - Constructor: `OpenAICompatGateway(settings, profile=None, *, client=None, clock=…, sleep=…, rng=…)`; keyword-only arguments are test injection points. `ProviderProfile` has a `name`; `resolve_profile(settings)` applies model/base-URL overrides.
- Test helpers: `skillagent.testing` exports `FakeLLM`, `FakeRule`, `RecordedCall`, `make_skill_spec()`, `echo_runner` (for synthetic-skill tests).

## 5. Errors — `skillagent/core/errors.py`
`SkillAgentError` → `ConfigError`, `UnknownSkillError`, `DuplicateSkillError`, `LLMError` → (`LLMTimeoutError`, `LLMRateLimitError`, `LLMProviderError`), `StructuredOutputError(raw_text: str, errors: str)`.

## 6. Language utilities — `skillagent/core/language.py`
`normalize_persian(text) -> str` · `to_ascii_digits(text) -> str` · `to_persian_digits(text) -> str` · `detect_lang_hint(text) -> LangHint` · `estimate_tokens(text) -> int` · `truncate_to_tokens(text, max_tokens) -> tuple[str, bool]` · `normalize_lang_code(value) -> str` · `strip_think(text) -> str` · `extract_json_object(text) -> str`. Behaviour is specified in `agent_prompts/WP1_foundation.md` §4.

## 7. Prompts — `skillagent/prompts/`
Files: `skillagent/prompts/<name>/v<N>.md` (e.g. `router/v1.md`). Placeholders use `string.Template` syntax (`$var` / `${var}`), so JSON braces need no escaping.
```python
class PromptTemplate(BaseModel):
    name: str; version: int; text: str; sha: str      # sha = first 12 hex of sha256(text)
    def render(self, **vars: str) -> str              # Template.substitute (missing var ⇒ KeyError)

class PromptLoader:
    def __init__(self, root: Path | None = None, pinned: dict[str, int] | None = None)
    def load(self, name: str, version: int | None = None) -> PromptTemplate
        # version None ⇒ pinned[name] if present, else highest available
    def available(self, name: str) -> list[int]
```
Pinning comes from settings `SKILLAGENT_PROMPT_VERSIONS="router=1,translator=2"` (used by eval to compare v1 vs v2).

## 8. Configuration — `skillagent/config.py`
`Settings` (pydantic-settings), loaded from env and `.env` (searched upward from CWD). Secrets use standard names; everything else uses the `SKILLAGENT_` prefix.

| Field | Env | Default |
|---|---|---|
| llm_provider | SKILLAGENT_LLM_PROVIDER | `google` (`google`\|`groq`\|`openrouter`\|`custom`) |
| llm_model | SKILLAGENT_LLM_MODEL | provider default (see providers table) |
| llm_base_url | SKILLAGENT_LLM_BASE_URL | provider default |
| google_api_key / groq_api_key / openrouter_api_key / custom_api_key | GOOGLE_API_KEY / GROQ_API_KEY / OPENROUTER_API_KEY / SKILLAGENT_CUSTOM_API_KEY | None (SecretStr) |
| llm_timeout_s | SKILLAGENT_LLM_TIMEOUT_S | 30 |
| llm_max_retries | SKILLAGENT_LLM_MAX_RETRIES | 3 |
| llm_max_concurrency | SKILLAGENT_LLM_MAX_CONCURRENCY | 4 |
| llm_rpm | SKILLAGENT_LLM_RPM | 20 |
| max_skills_per_request | SKILLAGENT_MAX_SKILLS_PER_REQUEST | 2 |
| max_parallel_steps | SKILLAGENT_MAX_PARALLEL_STEPS | 2 |
| max_waves | SKILLAGENT_MAX_WAVES | 2 |
| request_deadline_s | SKILLAGENT_REQUEST_DEADLINE_S | 90 |
| max_request_tokens | SKILLAGENT_MAX_REQUEST_TOKENS | 6000 |
| router_top_k_threshold | SKILLAGENT_ROUTER_TOP_K_THRESHOLD | 12 |
| router_top_k | SKILLAGENT_ROUTER_TOP_K | 6 |
| prompt_versions | SKILLAGENT_PROMPT_VERSIONS | "" → dict[str,int] |
| log_level | SKILLAGENT_LOG_LEVEL | WARNING |

Provider table (`skillagent/llm/providers.py`, `ProviderProfile`): `base_url`, `default_model`, `api_key_field`, `supports_system_role: bool`, `supports_json_mode: bool`, `supports_tools: bool`, `extra_body: dict` (e.g. thinking control). Initial values are **provisional** until WP0 measures them:

| provider | base_url | default_model |
|---|---|---|
| google | https://generativelanguage.googleapis.com/v1beta/openai/ | gemma-4-31b-it |
| groq | https://api.groq.com/openai/v1 | qwen/qwen3.8-27b |
| openrouter | https://openrouter.ai/api/v1 | google/gemma-4-31b-it:free |

## 9. Public API (implemented by WP5; consumed by CLI and eval)
```python
# skillagent/api.py
class AgentRun(BaseModel):
    response: str
    decision: RoutingDecision | None
    results: dict[str, SkillResult]
    trace: list[TraceEvent]
    total_ms: float
    llm_calls: int

async def run_agent(prompt: str, *, settings: Settings | None = None,
                    llm: LLMClient | None = None,
                    registry: SkillRegistry | None = None) -> AgentRun
```
`run_agent` never raises for model/provider failures; it returns a degraded `AgentRun` (bilingual apology) instead. It does raise `ConfigError` for missing configuration.

## 10. Graph state (WP5)
```python
class AgentState(TypedDict, total=False):
    request: UserRequest
    decision: RoutingDecision
    results: Annotated[dict[str, SkillResult], merge_results]   # dict merge keyed by step_id
    final_response: str
    trace: Annotated[list[TraceEvent], operator.add]
```

## 11. Router & preprocessing (v1.2, implemented by WP4; consumed by WP5)
```python
# skillagent/router/preprocess.py
def build_user_request(raw_text: str) -> UserRequest       # deterministic; no LLM
def leading_segment_hint(raw_text: str) -> LangHint        # language of the instruction part (text before
                                                           # the first ':'/newline, else first ~12 words)

# skillagent/router/candidates.py
class CandidateSelector(Protocol):
    def select(self, request: UserRequest, registry: SkillRegistry) -> list[str]   # skill names; always incl. general_chat
class AllSkills: ...                                       # used when len(registry) <= router_top_k_threshold
class BM25TopK:  def __init__(self, k: int) ...            # used above the threshold

# skillagent/router/router.py  (re-exported from skillagent.router)
class RouteResult(BaseModel):
    decision: RoutingDecision          # always valid; route_source in {"llm","rule","fallback"}
    events: list[TraceEvent]
    llm_calls: int                     # 0 for fast path

class Router:
    def __init__(self, registry: SkillRegistry, settings: Settings, prompts: PromptLoader,
                 selector: CandidateSelector | None = None) -> None
    async def route(self, request: UserRequest, llm: LLMClient, *,
                    elapsed_ms: Callable[[], float] = lambda: 0.0) -> RouteResult
```
`Router.route` **never raises** for LLM/validation failures: it returns a `fallback` decision (`general_chat`, `response_language` from `leading_segment_hint`). It raises only for programming errors.

## 12. Payload extraction (v1.2, implemented by WP3; used by summarizer & translator)
```python
# skillagent/skills/payload.py
class Payload(BaseModel):
    text: str                          # the content to operate on (instruction removed when detectable)
    method: Literal["chained", "quoted", "after_colon", "after_newline", "whole"]
    uncertain: bool                    # True when method == "whole" (prompt must tell the model to ignore the instruction part)
def extract_payload(inp: SkillInput) -> Payload
```

---

## Changelog
- v1.0 (2026-11-25) — initial freeze.
- v1.1 (2026-11-25, after WP1 review; all additive or relaxing):
  - `LLMResponse.finish_reason`
  - `rationale` truncated instead of rejected
  - `LangCode` output always ISO 639-1
  - `llm/types.py` + `llm/structured.py` module placement
  - gateway lifetime / deadline / retry-after rules
  - `ProviderProfile.name`
  - test helpers
- v1.2 (2026-11-25, before WP2–WP4):
  - §11 router public interface (`Router`, `RouteResult`, `build_user_request`, `leading_segment_hint`, `CandidateSelector`)
  - §12 payload extraction helper
