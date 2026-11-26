from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from skillagent import config
from skillagent.config import Settings, get_settings, mask_secret
from skillagent.core.errors import ConfigError
from skillagent.llm.providers import PROVIDERS, get_profile, resolve_profile

REAL_FIND_ENV_FILE = config._find_env_file  # captured at import, before fixtures patch it


def test_defaults_match_contract() -> None:
    s = Settings()
    assert s.llm_provider == "groq"
    assert (s.llm_timeout_s, s.llm_max_retries, s.llm_max_concurrency, s.llm_rpm) == (30, 3, 4, 20)
    assert (s.max_skills_per_request, s.max_parallel_steps, s.max_waves) == (2, 2, 2)
    assert (s.request_deadline_s, s.max_request_tokens) == (90, 6000)
    assert (s.router_top_k_threshold, s.router_top_k) == (12, 6)
    assert s.prompt_versions == {}
    assert s.log_level == "WARNING"


def test_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLAGENT_LLM_PROVIDER", "Groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_000000000000")
    monkeypatch.setenv("SKILLAGENT_PROMPT_VERSIONS", "router=1, translator=2")
    monkeypatch.setenv("SKILLAGENT_LLM_MODEL", "")
    monkeypatch.setenv("SKILLAGENT_LOG_LEVEL", "debug")
    s = Settings()
    assert s.llm_provider == "groq"
    assert s.api_key().get_secret_value() == "gsk_test_000000000000"
    assert s.prompt_versions == {"router": 1, "translator": 2}
    assert s.llm_model is None
    assert s.log_level == "DEBUG"


def test_invalid_prompt_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLAGENT_PROMPT_VERSIONS", "router:1")
    with pytest.raises(ValidationError, match="expected name=<int>"):
        Settings()


def test_env_file_found_upward(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("GROQ_API_KEY=gsk-from-dotenv-0000\n", encoding="utf-8")
    nested = tmp_path / ".worktrees" / "wp1"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    monkeypatch.setattr(config, "_find_env_file", REAL_FIND_ENV_FILE)  # undo conftest isolation
    assert Settings().api_key().get_secret_value() == "gsk-from-dotenv-0000"


def test_missing_key_is_actionable_config_error() -> None:
    with pytest.raises(ConfigError, match="set GROQ_API_KEY in the .env file"):
        Settings().api_key()


def test_empty_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "  ")
    with pytest.raises(ConfigError):
        Settings().api_key()


def test_limits_validated() -> None:
    with pytest.raises(ValidationError):
        Settings(llm_max_concurrency=0)


def test_get_settings_cached() -> None:
    assert get_settings() is get_settings()


def test_key_not_in_repr() -> None:
    s = Settings(google_api_key="AIza-secret-value-123")
    assert "AIza-secret-value-123" not in repr(s)


@pytest.mark.parametrize(
    ("value", "masked"), [("gsk_1234567890abcd", "gsk_…abcd"), ("short", "****")]
)
def test_mask_secret(value: str, masked: str) -> None:
    assert mask_secret(value) == masked


class TestProviders:
    def test_table(self) -> None:
        assert PROVIDERS["google"].default_model == "gemma-4-31b-it"
        assert PROVIDERS["groq"].base_url == "https://api.groq.com/openai/v1"
        assert PROVIDERS["openrouter"].default_model == "google/gemma-4-31b-it:free"
        for profile in PROVIDERS.values():
            assert profile.supports_system_role and profile.supports_json_mode
            assert profile.supports_tools
            assert profile.api_key_field in Settings.model_fields
        assert PROVIDERS["groq"].extra_body == {"reasoning_effort": "none"}  # WP0, ADR-026
        assert PROVIDERS["google"].extra_body == {}  # no working thinking-off switch

    def test_unknown_provider(self) -> None:
        with pytest.raises(ConfigError, match="unknown provider"):
            get_profile("acme")

    def test_overrides_applied(self) -> None:
        s = Settings(llm_model="other-model", llm_base_url="http://localhost:1234/v1")
        profile = resolve_profile(s)
        assert (profile.default_model, profile.base_url) == (
            "other-model",
            "http://localhost:1234/v1",
        )
        assert PROVIDERS["google"].default_model == "gemma-4-31b-it"  # table untouched

    def test_custom_requires_url_and_model(self) -> None:
        with pytest.raises(ConfigError, match="SKILLAGENT_LLM_BASE_URL"):
            resolve_profile(Settings(llm_provider="custom"))
        with pytest.raises(ConfigError, match="SKILLAGENT_LLM_MODEL"):
            resolve_profile(Settings(llm_provider="custom", llm_base_url="http://x/v1"))
