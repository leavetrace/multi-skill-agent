from __future__ import annotations

import io

import pytest
from rich.console import Console
from typer.testing import CliRunner

from skillagent import doctor
from skillagent.config import Settings
from skillagent.core.errors import LLMRateLimitError
from skillagent.testing import FakeLLM, FakeRule


def capture() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    return Console(file=buffer, width=200, color_system=None), buffer


def test_missing_key_exits_2_without_network() -> None:
    # conftest blocks sockets: reaching the network here would raise, not return 2.
    console, out = capture()
    assert doctor.run_doctor(console=console) == doctor.EXIT_CONFIG
    text = out.getvalue()
    assert "api key  : missing" in text
    assert "GOOGLE_API_KEY" in text and ".env" in text


def test_cli_entrypoint_exit_code() -> None:
    result = CliRunner().invoke(doctor.app, [])
    assert result.exit_code == 2


def test_invalid_config_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLAGENT_LLM_PROVIDER", "acme")
    console, out = capture()
    assert doctor.run_doctor(console=console) == doctor.EXIT_CONFIG
    assert "Configuration error" in out.getvalue()


def test_offline_ok_masks_key() -> None:
    console, out = capture()
    settings = Settings(google_api_key="AIzaSyREALLOOKING1234wxyz")
    assert doctor.run_doctor(settings=settings, console=console) == doctor.EXIT_OK
    text = out.getvalue()
    assert "AIza…wxyz" in text and "AIzaSyREALLOOKING1234wxyz" not in text
    assert "gemma-4-31b-it" in text


class _FakeGateway(FakeLLM):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__([FakeRule("doctor:structured", '{"ok": true}')], default="OK")

    async def aclose(self) -> None:
        pass


def test_live_checks_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "OpenAICompatGateway", _FakeGateway)
    console, out = capture()
    settings = Settings(google_api_key="AIzaSyREALLOOKING1234wxyz")
    assert doctor.run_doctor(live=True, settings=settings, console=console) == doctor.EXIT_OK
    text = out.getvalue()
    assert "plain      : ok" in text and "structured : ok" in text


def test_live_provider_error_exits_3(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failing(_FakeGateway):
        def __init__(self, *args: object, **kwargs: object) -> None:
            FakeLLM.__init__(self, [FakeRule(".*", LLMRateLimitError("quota"))])

    monkeypatch.setattr(doctor, "OpenAICompatGateway", Failing)
    console, out = capture()
    settings = Settings(google_api_key="AIzaSyREALLOOKING1234wxyz")
    assert doctor.run_doctor(live=True, settings=settings, console=console) == doctor.EXIT_PROVIDER
    assert "LLMRateLimitError" in out.getvalue()
