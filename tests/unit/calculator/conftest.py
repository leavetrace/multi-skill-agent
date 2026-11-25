"""Calculator test fixtures: a cross-platform hang guard and a FakeLLM skill context."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from skillagent.config import Settings
from skillagent.llm.types import ToolCall
from skillagent.prompts import PromptLoader
from skillagent.skills.base import SkillContext
from skillagent.testing import FakeLLM

SECURITY_TIMEOUT_S = 2.0
# Measured per-call durations of the security suite, reported in the WP2 handoff.
SECURITY_DURATIONS: list[tuple[str, float]] = []


def _run_with_timeout[R](fn: Callable[[], R], *, seconds: float, name: str) -> R:
    """Run `fn` in a daemon thread and fail the test if it doesn't finish in time.

    `signal.alarm` does not exist on Windows (the owner's machine) and pytest-timeout is
    not a dependency; a daemon thread works everywhere and never blocks interpreter exit
    even if the evaluator really did hang.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        start = time.perf_counter()
        try:
            box["value"] = fn()
        except BaseException as exc:  # re-raised in the test thread
            box["error"] = exc
        finally:
            box["elapsed"] = time.perf_counter() - start

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        pytest.fail(f"{name!r} did not finish within {seconds} s (possible DoS)")
    SECURITY_DURATIONS.append((name, box["elapsed"]))
    if "error" in box:
        raise box["error"]
    return box["value"]


@pytest.fixture
def within_timeout() -> Callable[..., Any]:
    """`within_timeout(fn, name=...)` → fn() or a test failure after 2 s."""

    def runner[T](fn: Callable[[], T], *, name: str, seconds: float = SECURITY_TIMEOUT_S) -> T:
        return _run_with_timeout(fn, seconds=seconds, name=name)

    return runner


def _tool_reply(*calculations: dict[str, Any] | str, **arguments: Any) -> list[ToolCall]:
    args: dict[str, Any] = arguments or {
        "calculations": [{"expression": c} if isinstance(c, str) else c for c in calculations]
    }
    return [ToolCall(id="call_1", name="evaluate", arguments=args, raw_arguments=json.dumps(args))]


@pytest.fixture
def tool_reply() -> Callable[..., list[ToolCall]]:
    """`tool_reply("1+1", {"expression": ..., "label": ...})` or `tool_reply(expression=...)`
    → a FakeLLM reply made of one `evaluate` tool call."""
    return _tool_reply


@pytest.fixture
def make_ctx() -> Callable[..., SkillContext]:
    def factory(llm: FakeLLM, **settings: Any) -> SkillContext:
        values: dict[str, Any] = {
            "llm_provider": "google",
            "google_api_key": "AIza-test-key-0000000000",
            "llm_rpm": 0,
        }
        values.update(settings)
        return SkillContext(llm=llm, settings=Settings(**values), prompts=PromptLoader())

    return factory
