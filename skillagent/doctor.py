"""`uv run python -m skillagent.doctor [--live]` — check configuration before spending quota.

Without `--live` it makes no network calls. With `--live` it spends exactly two calls: a
plain completion and a structured one, which are the two paths every skill relies on.
Exit codes: 0 OK, 2 configuration error, 3 provider error.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Annotated

import typer
from pydantic import BaseModel, ValidationError
from rich.console import Console

from skillagent.config import Settings, get_settings, mask_secret
from skillagent.core.errors import ConfigError, LLMError, StructuredOutputError
from skillagent.llm.gateway import OpenAICompatGateway
from skillagent.llm.providers import ProviderProfile, resolve_profile

__all__ = ["EXIT_CONFIG", "EXIT_OK", "EXIT_PROVIDER", "run_doctor"]

EXIT_OK, EXIT_CONFIG, EXIT_PROVIDER = 0, 2, 3


class _Ping(BaseModel):
    ok: bool


def run_doctor(
    *, live: bool = False, settings: Settings | None = None, console: Console | None = None
) -> int:
    """Print diagnostics and return the exit code (kept separate from typer for testing)."""
    console = console or Console()
    try:
        settings = settings or get_settings()
        profile = resolve_profile(settings)
    except (ConfigError, ValidationError) as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        return EXIT_CONFIG
    console.print(f"provider : {profile.name}")
    console.print(f"model    : {profile.default_model}")
    console.print(f"base URL : {profile.base_url}")
    try:
        key = settings.api_key().get_secret_value()
    except ConfigError as exc:
        console.print("api key  : [red]missing[/red]")
        console.print(f"[red]Configuration error:[/red] {exc}")
        return EXIT_CONFIG
    console.print(f"api key  : present ({mask_secret(key)})")
    if not live:
        console.print(
            "[green]Configuration OK[/green] (offline check; use --live to call the model)"
        )
        return EXIT_OK
    return asyncio.run(_live_checks(settings, profile, console))


async def _live_checks(settings: Settings, profile: ProviderProfile, console: Console) -> int:
    gateway = OpenAICompatGateway(settings, profile)
    try:
        plain = await gateway.complete(
            [{"role": "user", "content": "Reply with OK"}], max_tokens=16, purpose="doctor:plain"
        )
        console.print(
            f"plain      : ok  {plain.latency_ms:.0f} ms  tokens in/out "
            f"{plain.usage.prompt_tokens}/{plain.usage.completion_tokens}  reply={plain.text!r}"
        )
        structured = await gateway.complete_structured(
            [
                {"role": "system", "content": 'Reply with a JSON object: {"ok": true}'},
                {"role": "user", "content": "Are you working?"},
            ],
            _Ping,
            purpose="doctor:structured",
        )
        resp = structured.response
        console.print(
            f"structured : ok  {resp.latency_ms:.0f} ms  tokens in/out "
            f"{resp.usage.prompt_tokens}/{resp.usage.completion_tokens}  "
            f"repairs={structured.repairs}  value={structured.value.model_dump()}"
        )
    except (LLMError, StructuredOutputError) as exc:
        console.print(f"[red]Provider error:[/red] {type(exc).__name__}: {exc}")
        return EXIT_PROVIDER
    finally:
        await gateway.aclose()
    console.print("[green]Live checks OK[/green]")
    return EXIT_OK


app = typer.Typer(add_completion=False, help="Check skillagent configuration and provider access.")


@app.command()
def main(
    live: Annotated[
        bool, typer.Option("--live", help="Make 2 real LLM calls (uses free-tier quota).")
    ] = False,
) -> None:
    raise typer.Exit(run_doctor(live=live))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy codepage
    app()
