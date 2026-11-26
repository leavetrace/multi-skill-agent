"""`Router.route`: fast path → candidates → one structured LLM call → guards (CONTRACTS §11).

Every outcome is a valid `RoutingDecision`. Model and provider failures become a
`fallback` decision instead of an exception, so the CLI never crashes on a bad reply.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from skillagent.config import Settings
from skillagent.core.errors import LLMError, StructuredOutputError
from skillagent.core.language import estimate_tokens
from skillagent.core.registry import SkillRegistry
from skillagent.core.types import LangHint, RoutingDecision, TraceEvent, UserRequest
from skillagent.llm.types import ChatMessage, LLMClient
from skillagent.prompts import PromptLoader
from skillagent.router.candidates import FALLBACK_SKILL, AllSkills, BM25TopK, CandidateSelector
from skillagent.router.cards import render_cards, render_examples
from skillagent.router.examples import ROUTER_EXAMPLES
from skillagent.router.fast_path import try_route
from skillagent.router.guards import apply_guards
from skillagent.router.preprocess import leading_segment_hint

__all__ = [
    "PROMPT_NAME",
    "PURPOSE",
    "ROUTER_VIEW_HEAD_TOKENS",
    "ROUTER_VIEW_TAIL_TOKENS",
    "ROUTER_VIEW_TOKENS",
    "RouteResult",
    "Router",
    "router_view",
]

logger = logging.getLogger("skillagent.router")

PROMPT_NAME = "router"
PURPOSE = "router"
MAX_OUTPUT_TOKENS = 600
MAX_REPAIRS = 1

# The router never needs the whole payload: instructions sit at the start or the end.
ROUTER_VIEW_TOKENS = 700
ROUTER_VIEW_HEAD_TOKENS = 500
ROUTER_VIEW_TAIL_TOKENS = 150

_USER_TAG = re.compile(r"</?\s*user_message\s*>", re.IGNORECASE)
_WORD_SPLIT = re.compile(r"(\s+)")


class RouteResult(BaseModel):
    decision: RoutingDecision
    events: list[TraceEvent]
    llm_calls: int


def router_view(
    text: str,
    *,
    max_tokens: int = ROUTER_VIEW_TOKENS,
    head_tokens: int = ROUTER_VIEW_HEAD_TOKENS,
    tail_tokens: int = ROUTER_VIEW_TAIL_TOKENS,
) -> tuple[str, int]:
    """Head + tail window of a long message, and the number of words omitted (0 if none).

    Keeps router cost flat for a 3 000-word document: routing depends on the instruction,
    and skills get the full text anyway. Cuts fall on whitespace, never inside a word.
    """
    if estimate_tokens(text) <= max_tokens:
        return text, 0
    pieces = _WORD_SPLIT.split(text)  # words at even indexes, whitespace at odd ones
    words = pieces[0::2]
    head = _fit(words, head_tokens, from_end=False)
    tail = _fit(words[head:], tail_tokens, from_end=True)
    omitted = len(words) - head - tail
    if omitted <= 0:
        return text, 0
    head_text = "".join(pieces[: max(0, 2 * head - 1)]).rstrip()
    tail_text = "".join(pieces[len(pieces) - (2 * tail - 1) :]).lstrip() if tail else ""
    marker = f"[… {omitted} words omitted …]"
    return f"{head_text}\n{marker}\n{tail_text}".rstrip(), omitted


def _fit(words: list[str], budget: int, *, from_end: bool) -> int:
    """Largest n such that the first (or last) n words fit in `budget` tokens."""
    lo, hi = 0, len(words)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        chunk = words[-mid:] if from_end else words[:mid]
        if estimate_tokens(" ".join(chunk)) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return lo


class Router:
    def __init__(
        self,
        registry: SkillRegistry,
        settings: Settings,
        prompts: PromptLoader,
        selector: CandidateSelector | None = None,
    ) -> None:
        self.registry = registry
        self.settings = settings
        self.prompts = prompts
        self.selector = selector or self._default_selector()

    def _default_selector(self) -> CandidateSelector:
        if len(self.registry) <= self.settings.router_top_k_threshold:
            return AllSkills()
        return BM25TopK(self.settings.router_top_k)

    def build_messages(
        self, request: UserRequest, candidates: list[str]
    ) -> tuple[list[ChatMessage], dict[str, Any]]:
        """System prompt rendered from the candidate specs, plus the windowed user message.

        Returned info feeds the trace: prompt version/sha, rendered sha, token estimate.
        """
        template = self.prompts.load(PROMPT_NAME)
        specs = [self.registry.get(name) for name in candidates]
        lead_hint = leading_segment_hint(request.raw_text)
        system = template.render(
            skill_names=", ".join(candidates),
            skill_cards=render_cards(specs),
            examples=render_examples(specs, ROUTER_EXAMPLES),
            max_skills=str(self.settings.max_skills_per_request),
            fallback_skill=FALLBACK_SKILL,
            lead_hint=lead_hint,
            content_hint=request.lang_hint,
        )
        view, omitted = router_view(_USER_TAG.sub("", request.normalized_text))
        user = f"<user_message>\n{view}\n</user_message>"
        info = {
            "prompt": template.name,
            "version": template.version,
            "sha": template.sha,
            "rendered_sha": hashlib.sha256(system.encode("utf-8")).hexdigest()[:12],
            "system_tokens": estimate_tokens(system),
            "user_tokens": estimate_tokens(user),
            "omitted_words": omitted,
            "lead_hint": lead_hint,
        }
        messages: list[ChatMessage] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return messages, info

    async def route(
        self,
        request: UserRequest,
        llm: LLMClient,
        *,
        elapsed_ms: Callable[[], float] = lambda: 0.0,
    ) -> RouteResult:
        events: list[TraceEvent] = []
        started = time.perf_counter()

        def emit(event: str, **data: Any) -> None:
            events.append(TraceEvent(node="router", event=event, data=data, t_ms=elapsed_ms()))

        def finish(decision: RoutingDecision, llm_calls: int) -> RouteResult:
            emit(
                "end",
                route_source=decision.route_source,
                response_language=decision.response_language,
                needs_clarification=decision.needs_clarification,
                steps=[f"{s.id}:{s.skill}<-{s.input_from}" for s in decision.steps],
                dropped_intents=len(decision.dropped_intents),
                confidence=decision.confidence,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                llm_calls=llm_calls,
            )
            return RouteResult(decision=decision, events=events, llm_calls=llm_calls)

        emit("start", lang_hint=request.lang_hint, approx_tokens=request.approx_tokens)
        fast = try_route(request, self.registry)
        if fast is not None:
            emit("fast_path", rule=fast.rule)
            return finish(fast.decision, 0)

        candidates = self.selector.select(request, self.registry)
        emit(
            "candidates",
            selector=type(self.selector).__name__,
            skills=candidates,
            count=len(candidates),
            registry_size=len(self.registry),
        )
        messages, info = self.build_messages(request, candidates)
        emit("prompt", **info)

        try:
            result = await llm.complete_structured(
                messages,
                RoutingDecision,
                validation_context={
                    "registry": self.registry,
                    "max_skills": self.settings.max_skills_per_request,
                },
                max_repairs=MAX_REPAIRS,
                temperature=0.0,
                max_tokens=MAX_OUTPUT_TOKENS,
                purpose=PURPOSE,
            )
        except (StructuredOutputError, LLMError, TimeoutError) as exc:
            calls = MAX_REPAIRS + 1 if isinstance(exc, StructuredOutputError) else 1
            logger.warning("router fallback: %s: %s", type(exc).__name__, exc)
            emit("fallback", error=type(exc).__name__, detail=str(exc)[:300])
            return finish(_fallback_decision(info["lead_hint"], exc, self.registry), calls)

        response = result.response
        emit(
            "llm",
            repairs=result.repairs,
            model=response.model,
            latency_ms=response.latency_ms,
            attempts=response.attempts,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )
        decision = result.value.model_copy(update={"route_source": "llm"})
        decision, firings = apply_guards(decision, request, self.registry, info["lead_hint"])
        for firing in firings:
            emit("guard", guard=firing.guard, **firing.detail)
        return finish(decision, 1 + result.repairs)


def _fallback_decision(
    lead_hint: LangHint, exc: Exception, registry: SkillRegistry
) -> RoutingDecision:
    """Degraded `[general_chat]` plan; the composer/skill explains in the user's language."""
    return RoutingDecision.model_validate(
        {
            "response_language": "fa" if lead_hint == "fa" else "en",
            "steps": [
                {
                    "id": "s1",
                    "skill": FALLBACK_SKILL,
                    "instruction": "Respond helpfully to the user's message.",
                    "input_from": "user",
                }
            ],
            "confidence": 0.0,
            "rationale": f"router fallback after {type(exc).__name__}",
            "route_source": "fallback",
        },
        context={"registry": registry},
    )
