"""Gateway tests against a scripted stand-in for `AsyncOpenAI` (no network).

`FakeCompletions` replays a script of outcomes (completion dict or exception) and records
the kwargs of every request, which is what the provider would actually receive.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import httpx2
import openai
import pytest
from openai.types.chat import ChatCompletion

from skillagent.config import Settings
from skillagent.core.errors import (
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    StructuredOutputError,
)
from skillagent.llm.gateway import OpenAICompatGateway
from skillagent.llm.providers import ProviderProfile
from skillagent.llm.types import ToolSpec

_REQUEST = httpx2.Request("POST", "http://test.invalid/v1/chat/completions")


def completion(
    content: str | None = "hello",
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    model: str = "test-model",
    finish_reason: str = "stop",
) -> ChatCompletion:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return ChatCompletion.model_validate(
        {
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        }
    )


def status_error(status: int, message: str = "boom", headers: dict[str, str] | None = None):
    response = httpx2.Response(status, headers=headers or {}, request=_REQUEST)
    cls = {
        400: openai.BadRequestError,
        401: openai.AuthenticationError,
        429: openai.RateLimitError,
    }.get(status, openai.InternalServerError)
    if status not in (400, 401, 429) and status < 500:
        cls = openai.APIStatusError
    return cls(message, response=response, body=None)


Outcome = ChatCompletion | BaseException | Callable[[], Any]


class FakeCompletions:
    def __init__(self, script: list[Outcome]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> ChatCompletion:
        self.requests.append(kwargs)
        outcome = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if callable(outcome):
            outcome = await outcome()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, script: list[Outcome]) -> None:
        self.completions = FakeCompletions(script)
        self.chat = self
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class Recorder:
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def make_gateway(
    settings: Settings,
    script: list[Outcome],
    profile: ProviderProfile | None = None,
) -> tuple[OpenAICompatGateway, FakeClient, Recorder]:
    client, recorder = FakeClient(script), Recorder()
    gateway = OpenAICompatGateway(
        settings, profile, client=client, sleep=recorder.sleep, rng=lambda: 0.5
    )
    return gateway, client, recorder


USER = [{"role": "user", "content": "hi"}]


async def test_basic_completion_fields(make_settings) -> None:
    gateway, client, _ = make_gateway(make_settings(), [completion("<think>x</think>\nhello")])
    response = await gateway.complete(USER, temperature=0.2, max_tokens=50, purpose="t")
    assert response.text == "hello"
    assert (response.usage.prompt_tokens, response.usage.completion_tokens) == (11, 7)
    assert response.model == "test-model"
    assert response.attempts == 1
    assert response.latency_ms >= 0
    request = client.completions.requests[0]
    assert request["model"] == "gemma-4-31b-it"
    assert (request["temperature"], request["max_tokens"]) == (0.2, 50)
    assert "response_format" not in request and "tools" not in request


async def test_retry_on_429_honours_retry_after(make_settings) -> None:
    script = [status_error(429, "slow down", {"retry-after": "3"}), completion("ok")]
    gateway, _, recorder = make_gateway(make_settings(), script)
    response = await gateway.complete(USER)
    assert response.text == "ok"
    assert response.attempts == 2
    assert recorder.sleeps == [3.0]


async def test_exponential_backoff_with_jitter(make_settings) -> None:
    script = [status_error(503), status_error(502), status_error(500), completion("ok")]
    gateway, _, recorder = make_gateway(make_settings(), script)
    gateway._rng = iter([1.0, 0.0, 0.5]).__next__  # +25%, -25%, 0%
    response = await gateway.complete(USER)
    assert response.attempts == 4
    assert recorder.sleeps == [1.25, 1.5, 4.0]


async def test_rate_limit_exhausted_raises(make_settings) -> None:
    gateway, client, _ = make_gateway(make_settings(llm_max_retries=2), [status_error(429)])
    with pytest.raises(LLMRateLimitError):
        await gateway.complete(USER)
    assert len(client.completions.requests) == 3


async def test_huge_retry_after_fails_fast(make_settings) -> None:
    script = [status_error(429, "daily quota", {"retry-after": "3600"})]
    gateway, client, recorder = make_gateway(make_settings(), script)
    with pytest.raises(LLMRateLimitError, match="3600s"):
        await gateway.complete(USER)
    assert len(client.completions.requests) == 1 and recorder.sleeps == []


async def test_no_retry_on_400(make_settings) -> None:
    gateway, client, recorder = make_gateway(make_settings(), [status_error(400, "bad request")])
    with pytest.raises(LLMProviderError, match="provider error 400: bad request") as info:
        await gateway.complete(USER)
    assert info.value.status_code == 400
    assert len(client.completions.requests) == 1 and recorder.sleeps == []


async def test_provider_message_never_leaks_key(make_settings) -> None:
    error = status_error(401, "Invalid key gsk_abcdefghijklmnopqrstuvwxyz1234 provided")
    gateway, _, _ = make_gateway(make_settings(), [error])
    with pytest.raises(LLMProviderError) as info:
        await gateway.complete(USER)
    assert "gsk_abcdefghijklmnopqrstuvwxyz1234" not in str(info.value)
    assert "gsk_…1234" in str(info.value)


async def test_connection_error_retried(make_settings) -> None:
    script = [openai.APIConnectionError(request=_REQUEST), completion("ok")]
    gateway, _, recorder = make_gateway(make_settings(), script)
    assert (await gateway.complete(USER)).attempts == 2
    assert len(recorder.sleeps) == 1


async def test_timeout_maps_to_llm_timeout_error(make_settings) -> None:
    async def hang() -> None:
        await asyncio.sleep(5)

    gateway, client, recorder = make_gateway(make_settings(llm_max_retries=1), [hang])
    with pytest.raises(LLMTimeoutError, match="timed out after 0.01s"):
        await gateway.complete(USER, timeout_s=0.01)
    assert len(client.completions.requests) == 2  # timeouts are retried
    assert len(recorder.sleeps) == 1


async def test_sdk_timeout_also_mapped(make_settings) -> None:
    gateway, _, _ = make_gateway(
        make_settings(llm_max_retries=0), [openai.APITimeoutError(_REQUEST)]
    )
    with pytest.raises(LLMTimeoutError):
        await gateway.complete(USER)


async def test_json_mode_sent_when_supported(make_settings) -> None:
    gateway, client, _ = make_gateway(make_settings(), [completion('{"a": 1}')])
    await gateway.complete(USER, json_mode=True)
    assert client.completions.requests[0]["response_format"] == {"type": "json_object"}


async def test_json_mode_fallback_when_rejected(make_settings, caplog) -> None:
    script = [status_error(400, "response_format json_object is not supported"), completion("{}")]
    gateway, client, _ = make_gateway(make_settings(), script)
    with caplog.at_level(logging.WARNING, logger="skillagent.llm"):
        response = await gateway.complete(USER, json_mode=True)
    assert response.attempts == 2
    assert "response_format" not in client.completions.requests[1]
    assert "rejected response_format" in caplog.text
    await gateway.complete(USER, json_mode=True)  # unsupported is cached
    assert "response_format" not in client.completions.requests[2]


async def test_json_mode_skipped_when_profile_says_unsupported(make_settings) -> None:
    profile = ProviderProfile("p", "http://x/v1", "m", "google_api_key", supports_json_mode=False)
    gateway, client, _ = make_gateway(make_settings(), [completion("{}")], profile)
    await gateway.complete(USER, json_mode=True)
    assert "response_format" not in client.completions.requests[0]


async def test_system_role_merged_when_unsupported(make_settings) -> None:
    profile = ProviderProfile("p", "http://x/v1", "m", "google_api_key", supports_system_role=False)
    gateway, client, _ = make_gateway(make_settings(), [completion()], profile)
    messages = [
        {"role": "system", "content": "Be brief."},
        {"role": "system", "content": "Answer in Persian."},
        {"role": "user", "content": "سلام"},
    ]
    await gateway.complete(messages)
    sent = client.completions.requests[0]["messages"]
    assert sent == [
        {
            "role": "user",
            "content": "[Instructions]\nBe brief.\n\nAnswer in Persian.\n\n[User]\nسلام",
        }
    ]
    assert messages[2]["content"] == "سلام"  # caller's list not mutated


async def test_system_role_kept_when_supported(make_settings) -> None:
    gateway, client, _ = make_gateway(make_settings(), [completion()])
    messages = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    await gateway.complete(messages)
    assert client.completions.requests[0]["messages"] == messages


async def test_tools_and_tool_call_parsing(make_settings) -> None:
    tool_calls = [
        {
            "id": "t1",
            "type": "function",
            "function": {"name": "evaluate", "arguments": '{"expression": "2+2"}'},
        },
        {"id": "t2", "type": "function", "function": {"name": "evaluate", "arguments": "{oops"}},
    ]
    gateway, client, _ = make_gateway(make_settings(), [completion(None, tool_calls=tool_calls)])
    tool = ToolSpec(name="evaluate", description="Evaluate", parameters={"type": "object"})
    response = await gateway.complete(USER, tools=[tool], tool_choice="evaluate")
    request = client.completions.requests[0]
    assert request["tools"][0]["function"]["name"] == "evaluate"
    assert request["tool_choice"] == {"type": "function", "function": {"name": "evaluate"}}
    assert response.text == ""
    assert response.tool_calls[0].arguments == {"expression": "2+2"}
    assert response.tool_calls[1].arguments == {}
    assert response.tool_calls[1].raw_arguments == "{oops"


async def test_tool_choice_required_passthrough(make_settings) -> None:
    gateway, client, _ = make_gateway(make_settings(), [completion()])
    tool = ToolSpec(name="evaluate", description="", parameters={})
    await gateway.complete(USER, tools=[tool], tool_choice="required")
    assert client.completions.requests[0]["tool_choice"] == "required"


async def test_tool_choice_must_name_a_tool(make_settings) -> None:
    gateway, _, _ = make_gateway(make_settings(), [completion()])
    with pytest.raises(ValueError, match="does not name"):
        await gateway.complete(USER, tool_choice="missing")


async def test_extra_body_applied(make_settings) -> None:
    profile = ProviderProfile(
        "p", "http://x/v1", "m", "google_api_key", extra_body={"reasoning_effort": "none"}
    )
    gateway, client, _ = make_gateway(make_settings(), [completion()], profile)
    await gateway.complete(USER)
    assert client.completions.requests[0]["extra_body"] == {"reasoning_effort": "none"}


async def test_empty_choices_is_provider_error(make_settings) -> None:
    empty = completion()
    empty.choices = []
    gateway, _, _ = make_gateway(make_settings(), [empty])
    with pytest.raises(LLMProviderError, match="no choices"):
        await gateway.complete(USER)


async def test_concurrency_never_exceeds_semaphore(make_settings) -> None:
    in_flight = peak = 0

    async def slow() -> ChatCompletion:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return completion()

    gateway, client, _ = make_gateway(make_settings(llm_max_concurrency=2), [slow])
    await asyncio.gather(*(gateway.complete(USER) for _ in range(8)))
    assert len(client.completions.requests) == 8
    assert peak == 2


async def test_rate_limiter_wired_into_gateway(make_settings) -> None:
    now = [0.0]
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    gateway = OpenAICompatGateway(
        make_settings(llm_rpm=2),
        client=FakeClient([completion()]),
        clock=lambda: now[0],
        sleep=fake_sleep,
    )
    for _ in range(3):
        await gateway.complete(USER)
    assert sleeps == [60.0]


async def test_logs_metadata_but_never_content(make_settings, caplog) -> None:
    gateway, _, _ = make_gateway(make_settings(), [completion("SECRET-ANSWER")])
    with caplog.at_level(logging.DEBUG, logger="skillagent.llm"):
        await gateway.complete([{"role": "user", "content": "SECRET-PROMPT"}], purpose="router")
    assert "purpose=router" in caplog.text and "attempts=1" in caplog.text
    assert "SECRET-PROMPT" not in caplog.text and "SECRET-ANSWER" not in caplog.text
    assert "AIza-test-key" not in caplog.text


async def test_aclose_closes_client(make_settings) -> None:
    gateway, client, _ = make_gateway(make_settings(), [completion()])
    await gateway.aclose()
    assert client.closed


async def test_builds_real_client_from_settings(make_settings) -> None:
    gateway = OpenAICompatGateway(make_settings())  # constructing makes no network call
    assert isinstance(gateway._client, openai.AsyncOpenAI)
    assert str(gateway._client.base_url).startswith("https://generativelanguage.googleapis.com")
    assert gateway._client.max_retries == 0
    await gateway.aclose()


async def test_end_to_end_through_real_sdk_with_mock_transport(make_settings) -> None:
    """Exercise the real openai client serialization via an in-memory HTTP transport."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=completion('{"ok": true}').model_dump(mode="json"))

    client = openai.AsyncOpenAI(
        api_key="test",
        base_url="http://test.invalid/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    gateway = OpenAICompatGateway(make_settings(), client=client)
    response = await gateway.complete(USER, json_mode=True, purpose="e2e")
    assert response.text == '{"ok": true}'
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert seen[0]["messages"] == USER
    await gateway.aclose()


async def test_complete_structured_uses_shared_repair_loop(make_settings) -> None:
    from pydantic import BaseModel

    class Ping(BaseModel):
        ok: bool

    script = [completion("not json"), completion('```json\n{"ok": true}\n```')]
    gateway, client, _ = make_gateway(make_settings(), script)
    result = await gateway.complete_structured(USER, Ping, purpose="router")
    assert result.value.ok is True and result.repairs == 1
    assert client.completions.requests[1]["messages"][-1]["content"].startswith(
        "Your previous output was invalid"
    )

    gateway, _, _ = make_gateway(make_settings(), [completion("still not json")])
    with pytest.raises(StructuredOutputError):
        await gateway.complete_structured(USER, Ping, max_repairs=1)


async def test_finish_reason_is_reported(make_settings) -> None:
    gateway, _, _ = make_gateway(make_settings(), [completion("cut", finish_reason="length")])
    response = await gateway.complete([{"role": "user", "content": "hi"}])
    assert response.finish_reason == "length"


def test_redact_masks_provider_account_ids() -> None:
    # Groq 429 bodies name the account's organisation id (ADR-029).
    from skillagent.config import Settings
    from skillagent.llm.gateway import OpenAICompatGateway

    gw = OpenAICompatGateway(Settings(llm_provider="groq", groq_api_key="gsk-test-0000"))
    text = gw._redact("Rate limit in organization `org_01abcdefFAKE9999` on TPD")
    assert "org_01abc" not in text and "org_<redacted>" in text
