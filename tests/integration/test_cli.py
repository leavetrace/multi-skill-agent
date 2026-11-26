"""CLI through typer's `CliRunner`, offline: `run_agent` gets a `FakeLLM` injected."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from skillagent import cli
from skillagent.api import run_agent
from skillagent.testing import FakeLLM, FakeRule

PERSIAN_REPLY = "سلام! حالم خوب است، ممنون که پرسیدی."


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_agent(monkeypatch: pytest.MonkeyPatch, plan, mk_step) -> FakeLLM:
    """Route every CLI request to general chat answering in Persian."""
    llm = FakeLLM(
        [
            FakeRule(
                match=lambda m, p: p == "router",
                reply=plan("fa", mk_step("s1", "general_chat", "پاسخ به احوال‌پرسی")),
            ),
            FakeRule(match=lambda m, p: p == "skill:general_chat", reply=PERSIAN_REPLY),
        ]
    )

    async def with_fake(prompt: str, **kwargs: Any) -> Any:
        kwargs["llm"] = llm
        return await run_agent(prompt, **kwargs)

    monkeypatch.setattr(cli, "run_agent", with_fake)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-test-key-0000000000")
    monkeypatch.setenv("SKILLAGENT_LLM_PROVIDER", "google")
    return llm


def test_ask_prints_response(runner: CliRunner, fake_agent: FakeLLM) -> None:
    result = runner.invoke(cli.app, ["ask", "سلام، حالت چطوره؟"])
    assert result.exit_code == 0, result.output
    assert PERSIAN_REPLY in result.output
    assert [c.purpose for c in fake_agent.calls] == ["router", "skill:general_chat"]


def test_ask_reads_file_and_writes_utf8_out(
    runner: CliRunner, fake_agent: FakeLLM, tmp_path: Path
) -> None:
    source = tmp_path / "in.txt"
    source.write_text("سلام، حالت چطوره؟\nخوبی؟", encoding="utf-8")
    out = tmp_path / "answer.md"
    result = runner.invoke(cli.app, ["ask", "--file", str(source), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_bytes().decode("utf-8") == PERSIAN_REPLY + "\n"
    router_input = next(c for c in fake_agent.calls if c.purpose == "router").messages[-1]
    assert "خوبی؟" in router_input["content"]


def test_ask_json_is_an_agent_run(runner: CliRunner, fake_agent: FakeLLM) -> None:
    result = runner.invoke(cli.app, ["ask", "سلام", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["response"] == PERSIAN_REPLY
    assert data["llm_calls"] == 2
    assert data["results"]["s1"]["status"] == "ok"
    assert PERSIAN_REPLY in result.output  # ensure_ascii=False: no \\u escapes


def test_ask_trace_shows_tables(runner: CliRunner, fake_agent: FakeLLM) -> None:
    result = runner.invoke(cli.app, ["ask", "سلام", "--trace"])
    assert result.exit_code == 0, result.output
    for title in ("Routing decision", "Steps", "Trace events", "skill:general_chat"):
        assert title in result.output
    assert "2 LLM call(s)" in result.output


def test_ask_needs_exactly_one_input(runner: CliRunner, fake_agent: FakeLLM) -> None:
    assert runner.invoke(cli.app, ["ask"]).exit_code == 1


def test_missing_key_is_one_red_line_exit_2(runner: CliRunner) -> None:
    result = runner.invoke(cli.app, ["ask", "hello"])  # isolated env: no GROQ_API_KEY
    assert result.exit_code == 2
    assert "Configuration error" in result.output
    assert "GROQ_API_KEY" in result.output
    assert "Traceback" not in result.output
    assert not isinstance(result.exception, Exception) or isinstance(result.exception, SystemExit)


def test_invalid_setting_is_a_config_error(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SKILLAGENT_MAX_WAVES", "zero")
    result = runner.invoke(cli.app, ["ask", "hello"])
    assert result.exit_code == 2
    assert "max_waves" in result.output
    assert "Traceback" not in result.output


def test_graph_mermaid(runner: CliRunner) -> None:
    result = runner.invoke(cli.app, ["graph", "--mermaid"])
    assert result.exit_code == 0, result.output
    for node in ("preprocess", "router", "clarify", "scheduler", "composer"):
        assert node in result.output
    for skill in ("summarizer", "translator", "calculator", "general_chat"):
        assert f"scheduler -.-> skill_{skill};" in result.output
        assert f"skill_{skill} --> scheduler;" in result.output


def test_doctor_delegates(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_doctor(*, live: bool = False) -> int:
        seen["live"] = live
        return 0

    monkeypatch.setattr("skillagent.doctor.run_doctor", fake_doctor)
    assert runner.invoke(cli.app, ["doctor", "--live"]).exit_code == 0
    assert seen == {"live": True}


# --- REPL --------------------------------------------------------------------------------


def scripted(lines: list[str]) -> Callable[[str], str]:
    queue = list(lines)

    def read(prompt: str) -> str:
        if not queue:
            raise EOFError
        return queue.pop(0)

    return read


async def test_read_request_multiline_and_paste() -> None:
    read = scripted(["first line", "second line", "", ":paste", "a", "", "b", ":end", ":q"])
    assert await cli._read_request(read) == "first line\nsecond line"
    assert await cli._read_request(read) == "a\n\nb"
    assert await cli._read_request(read) is None


async def test_repl_reuses_one_gateway(
    monkeypatch: pytest.MonkeyPatch, fake_agent: FakeLLM, make_settings
) -> None:
    created: list[Any] = []

    class FakeGateway:
        def __init__(self, settings: Any, profile: Any) -> None:
            created.append(self)
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    llms: list[Any] = []

    async def record(prompt: str, **kwargs: Any) -> Any:
        llms.append(kwargs.pop("llm"))
        return await run_agent(prompt, llm=fake_agent, **kwargs)

    monkeypatch.setattr(cli, "OpenAICompatGateway", FakeGateway)
    monkeypatch.setattr(cli, "run_agent", record)
    await cli._repl(make_settings(), scripted(["سلام", "", "hello again", "", ":quit"]))
    assert len(created) == 1 and created[0].closed
    assert llms == [created[0], created[0]]


def test_quiet_retries_is_scoped_and_skipped_with_trace() -> None:
    import logging

    from skillagent.cli import _quiet_retries

    logger = logging.getLogger("skillagent.llm")
    before = logger.level
    with _quiet_retries(trace=False):
        assert logger.level == logging.ERROR
    assert logger.level == before
    with _quiet_retries(trace=True):
        assert logger.level == before
