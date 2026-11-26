"""Provider profiles: per-endpoint quirks live in data, not in `if provider == ...` branches.

Groq values were measured in the WP0 bake-off (ADR-026): system role, JSON mode and forced
tool calls all work, and `reasoning_effort: "none"` pins instruct mode. Google's Gemma 4
accepts the same features but always thinks inline (`<thought>…</thought>`), which
`strip_think` removes; no request field turns it off. The gateway keeps its fallbacks for
each flag (system-role merging, JSON-mode retry).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from skillagent.core.errors import ConfigError

if TYPE_CHECKING:
    from skillagent.config import Settings

__all__ = ["PROVIDERS", "ProviderProfile", "get_profile", "resolve_profile"]


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    base_url: str
    default_model: str
    api_key_field: str  # name of the Settings field holding this provider's key
    supports_system_role: bool = True
    supports_json_mode: bool = True
    supports_tools: bool = True
    extra_body: dict[str, Any] = field(default_factory=dict)  # e.g. thinking control


PROVIDERS: dict[str, ProviderProfile] = {
    "google": ProviderProfile(
        name="google",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemma-4-31b-it",
        api_key_field="google_api_key",
    ),
    "groq": ProviderProfile(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="qwen/qwen3.8-27b",
        api_key_field="groq_api_key",
        extra_body={"reasoning_effort": "none"},
    ),
    "openrouter": ProviderProfile(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="google/gemma-4-31b-it:free",
        api_key_field="openrouter_api_key",
    ),
    "custom": ProviderProfile(
        name="custom",
        base_url="",  # must come from SKILLAGENT_LLM_BASE_URL
        default_model="",  # must come from SKILLAGENT_LLM_MODEL
        api_key_field="custom_api_key",
    ),
}


def get_profile(provider: str) -> ProviderProfile:
    try:
        return PROVIDERS[provider]
    except KeyError:
        raise ConfigError(
            f"unknown provider {provider!r}; "
            f"set SKILLAGENT_LLM_PROVIDER to one of {sorted(PROVIDERS)}"
        ) from None


def resolve_profile(settings: Settings) -> ProviderProfile:
    """Active profile with the `SKILLAGENT_LLM_BASE_URL` / `_LLM_MODEL` overrides applied."""
    profile = get_profile(settings.llm_provider)
    profile = replace(
        profile,
        base_url=settings.llm_base_url or profile.base_url,
        default_model=settings.llm_model or profile.default_model,
    )
    if not profile.base_url:
        raise ConfigError(f"provider {profile.name!r} needs SKILLAGENT_LLM_BASE_URL in .env")
    if not profile.default_model:
        raise ConfigError(f"provider {profile.name!r} needs SKILLAGENT_LLM_MODEL in .env")
    return profile
