"""Settings loaded from the environment and the nearest `.env` (CONTRACTS §8).

Every limit the architecture relies on (concurrency, RPM, skill/step caps, deadlines,
token budgets) lives here so it is tunable without code changes and visible in one place.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from dotenv import find_dotenv
from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from skillagent.core.errors import ConfigError

__all__ = ["Settings", "get_settings", "mask_secret"]

ProviderName = Literal["google", "groq", "openrouter", "custom"]
_OPTIONAL_STR_FIELDS = (
    "llm_model",
    "llm_base_url",
    "google_api_key",
    "groq_api_key",
    "openrouter_api_key",
    "custom_api_key",
)


def _find_env_file() -> str | None:
    """Search upward from the CWD, so sessions inside `.worktrees/<wp>` find the root `.env`."""
    return find_dotenv(usecwd=True) or None


def _secret(env_name: str) -> SecretStr | None:
    # Keys use their standard, un-prefixed names (GOOGLE_API_KEY, ...).
    return Field(default=None, validation_alias=AliasChoices(env_name))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SKILLAGENT_",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_by_name=True,
        validate_by_alias=True,
    )

    llm_provider: ProviderName = "google"
    llm_model: str | None = None
    llm_base_url: str | None = None

    google_api_key: SecretStr | None = _secret("GOOGLE_API_KEY")
    groq_api_key: SecretStr | None = _secret("GROQ_API_KEY")
    openrouter_api_key: SecretStr | None = _secret("OPENROUTER_API_KEY")
    custom_api_key: SecretStr | None = _secret("SKILLAGENT_CUSTOM_API_KEY")

    llm_timeout_s: float = Field(default=30, gt=0)
    llm_max_retries: int = Field(default=3, ge=0)
    llm_max_concurrency: int = Field(default=4, ge=1)
    llm_rpm: int = Field(default=20, ge=0)  # 0 disables the rate limiter

    max_skills_per_request: int = Field(default=2, ge=1)
    max_parallel_steps: int = Field(default=2, ge=1)
    max_waves: int = Field(default=2, ge=1)
    request_deadline_s: float = Field(default=90, gt=0)
    max_request_tokens: int = Field(default=6000, ge=1)

    router_top_k_threshold: int = Field(default=12, ge=1)
    router_top_k: int = Field(default=6, ge=1)

    prompt_versions: Annotated[dict[str, int], NoDecode] = Field(default_factory=dict)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "WARNING"

    def __init__(self, **values: object) -> None:
        values.setdefault("_env_file", _find_env_file())
        super().__init__(**values)

    @field_validator(*_OPTIONAL_STR_FIELDS, mode="before")
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        # `.env.example` ships `SKILLAGENT_LLM_MODEL=` etc.; empty must mean "not set".
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("llm_provider", mode="before")
    @classmethod
    def _lower_provider(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("prompt_versions", mode="before")
    @classmethod
    def _parse_prompt_versions(cls, value: object) -> object:
        """`"router=1, translator=2"` → `{"router": 1, "translator": 2}`."""
        if not isinstance(value, str):
            return value
        pins: dict[str, int] = {}
        for item in filter(None, (part.strip() for part in value.split(","))):
            name, sep, version = item.partition("=")
            if not sep or not name.strip() or not version.strip().isdigit():
                raise ValueError(
                    f"invalid SKILLAGENT_PROMPT_VERSIONS entry {item!r}; expected name=<int>, "
                    "e.g. 'router=1,translator=2'"
                )
            pins[name.strip()] = int(version)
        return pins

    def api_key(self) -> SecretStr:
        """Key of the active provider; `ConfigError` explains exactly which variable to set."""
        from skillagent.llm.providers import get_profile

        profile = get_profile(self.llm_provider)
        key = getattr(self, profile.api_key_field)
        if key is None:
            env_name = _env_name(profile.api_key_field)
            raise ConfigError(
                f"No API key for provider {self.llm_provider!r}: set {env_name} in the .env file "
                "at the repository root (copy .env.example to .env). Never paste keys in chat."
            )
        return key


def mask_secret(value: str) -> str:
    """`gsk_1234567890abcd` → `gsk_…abcd`; short values are fully hidden."""
    if len(value) < 12:
        return "****"
    return f"{value[:4]}…{value[-4:]}"


def _env_name(field_name: str) -> str:
    alias = Settings.model_fields[field_name].validation_alias
    assert isinstance(alias, AliasChoices)
    return str(alias.choices[0])


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, read once. Tests call `get_settings.cache_clear()`."""
    return Settings()
