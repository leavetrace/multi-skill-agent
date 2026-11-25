"""LLM access layer: provider-agnostic types, the OpenAI-compatible gateway and profiles."""

from skillagent.llm.gateway import OpenAICompatGateway
from skillagent.llm.providers import PROVIDERS, ProviderProfile, get_profile, resolve_profile
from skillagent.llm.types import (
    ChatMessage,
    LLMClient,
    LLMResponse,
    LLMUsage,
    StructuredResult,
    ToolCall,
    ToolSpec,
)

__all__ = [
    "PROVIDERS",
    "ChatMessage",
    "LLMClient",
    "LLMResponse",
    "LLMUsage",
    "OpenAICompatGateway",
    "ProviderProfile",
    "StructuredResult",
    "ToolCall",
    "ToolSpec",
    "get_profile",
    "resolve_profile",
]
