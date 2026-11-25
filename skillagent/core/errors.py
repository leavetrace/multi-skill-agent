"""Exception hierarchy shared by every layer (CONTRACTS §5).

One root (`SkillAgentError`) lets the API layer separate "our" failures from programming
errors, and the LLM sub-tree lets the graph map provider trouble to degraded answers
without catching everything.
"""

from __future__ import annotations


class SkillAgentError(Exception):
    """Root of all errors raised deliberately by skillagent."""


class ConfigError(SkillAgentError):
    """Missing or invalid configuration (e.g. no API key). Message tells the user how to fix it."""


class UnknownSkillError(SkillAgentError, LookupError):
    """A skill name did not resolve to any registered skill."""


class DuplicateSkillError(SkillAgentError, ValueError):
    """Two specs were registered under the same canonical name."""


class LLMError(SkillAgentError):
    """Base class for failures talking to an LLM provider."""


class LLMTimeoutError(LLMError):
    """The call did not finish within its timeout (after retries)."""


class LLMRateLimitError(LLMError):
    """The provider kept answering 429 (or asked us to wait longer than we are willing to)."""


class LLMProviderError(LLMError):
    """Non-retryable provider error (4xx) or retryable error that persisted (5xx, connection)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class StructuredOutputError(SkillAgentError):
    """The model never produced JSON that parsed and validated, even after repairs.

    Carries the last raw text and a concise error summary so callers (router fallback,
    trace) can show what went wrong without re-running the call.
    """

    def __init__(self, raw_text: str, errors: str) -> None:
        super().__init__(f"structured output invalid: {errors}")
        self.raw_text = raw_text
        self.errors = errors
