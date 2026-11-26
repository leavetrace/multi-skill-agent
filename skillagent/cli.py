"""Command-line interface: REPL, one-shot `ask`, `graph --mermaid`, `doctor`.

Windows first: stdout/stderr are forced to UTF-8 at startup, `--file`/`--out` move Persian
text through UTF-8 files (the documented workaround for RTL rendering in Windows
terminals), and configuration problems print one red line with exit code 2, never a
traceback. Responses are printed as plain text: model output must not be parsed as rich
markup.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from skillagent.api import AgentRun, run_agent
from skillagent.config import Settings
from skillagent.core.errors import ConfigError
from skillagent.llm import OpenAICompatGateway, resolve_profile

__all__ = ["EXIT_CONFIG", "app", "main"]

EXIT_CONFIG = 2
_TRACE_VALUE_CHARS = 140
_QUIT = {":quit", ":q"}
_PASTE, _PASTE_END = ":paste", ":end"

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="Multi-skill agent (summarizer, translator, calculator, general chat). "
    "Run without arguments for an interactive session.",
)


def _out() -> Console:
    return Console(highlight=False, soft_wrap=True)


def _err() -> Console:
    return Console(stderr=True, highlight=False, soft_wrap=True)


def _config_error(exc: Exception) -> typer.Exit:
    """One actionable red line; ConfigError messages already name the `.env` entry."""
    message = str(exc).splitlines()[0] if isinstance(exc, ConfigError) else _first_error(exc)
    _err().print(f"[red]Configuration error:[/red] {message}", markup=True)
    return typer.Exit(EXIT_CONFIG)


def _first_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError) and exc.errors():
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first.get("loc", ()))
        return f"invalid setting {field!r}: {first.get('msg', '')} (check your .env)"
    return str(exc)


def _load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise _config_error(exc) from None


# --- output ------------------------------------------------------------------------------


def _print_response(run: AgentRun) -> None:
    _out().print(run.response, markup=False)


def _short(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= _TRACE_VALUE_CHARS else text[: _TRACE_VALUE_CHARS - 1] + "…"


def _print_trace(run: AgentRun) -> None:
    console = _out()
    decision = run.decision
    routing = Table(title="Routing decision", show_header=False)
    if decision is None:
        routing.add_row("decision", "none (request answered before routing)")
    else:
        routing.add_row("source", decision.route_source)
        routing.add_row("response_language", decision.response_language)
        routing.add_row("confidence", f"{decision.confidence:.2f}")
        routing.add_row("clarification", str(decision.needs_clarification))
        for step in decision.steps:
            params = _short(step.params) if step.params else ""
            routing.add_row(
                f"{step.id}: {step.skill} ← {step.input_from}", f"{step.instruction} {params}"
            )
        if decision.dropped_intents:
            routing.add_row("dropped", _short(decision.dropped_intents))
        if decision.rationale:
            routing.add_row("rationale", decision.rationale)
    console.print(routing)

    steps = Table(title="Steps")
    for column in ("step", "skill", "status", "latency ms", "llm calls", "detail"):
        steps.add_column(column)
    for result in run.results.values():
        detail = result.error or _short(result.meta.get("path") or result.meta.get("reason") or "")
        steps.add_row(
            result.step_id,
            result.skill,
            result.status,
            f"{result.meta.get('latency_ms', 0):.0f}",
            str(result.meta.get("llm_calls", 0)),
            detail,
        )
    console.print(steps)

    events = Table(title="Trace events")
    for column in ("t ms", "node", "event", "data"):
        events.add_column(column)
    for event in run.trace:
        events.add_row(f"{event.t_ms:.0f}", event.node, event.event, _short(event.data))
    console.print(events)
    console.print(f"total {run.total_ms:.0f} ms · {run.llm_calls} LLM call(s)", markup=False)


# --- commands ----------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context) -> None:
    """Without a subcommand, start the interactive session."""
    if ctx.invoked_subcommand is None:
        settings = _load_settings()
        try:
            asyncio.run(_repl(settings, input))
        except ConfigError as exc:
            raise _config_error(exc) from None
        except KeyboardInterrupt:
            raise typer.Exit(130) from None


@app.command()
def ask(
    prompt: Annotated[str | None, typer.Argument(help="The request (or use --file).")] = None,
    file: Annotated[
        Path | None, typer.Option("--file", "-f", help="Read the request from a UTF-8 file.")
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Also write the response to a UTF-8 file.")
    ] = None,
    trace: Annotated[bool, typer.Option("--trace", help="Show routing, steps and trace.")] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the full AgentRun as JSON.")
    ] = False,
) -> None:
    """Answer one request and exit."""
    if (prompt is None) == (file is None):
        _err().print("[red]Give a prompt argument or --file, not both.[/red]")
        raise typer.Exit(1)
    text = file.read_text(encoding="utf-8-sig") if file is not None else prompt or ""
    settings = _load_settings()
    try:
        run = asyncio.run(run_agent(text, settings=settings))
    except ConfigError as exc:
        raise _config_error(exc) from None

    if as_json:
        typer.echo(json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        _print_response(run)
        if trace:
            _print_trace(run)
    if out is not None:
        out.write_text(run.response + "\n", encoding="utf-8")
        _err().print(f"response written to {out}", markup=False)


@app.command()
def graph(
    mermaid: Annotated[bool, typer.Option("--mermaid", help="Print Mermaid source.")] = False,
) -> None:
    """Show the agent graph (generated from the skill registry)."""
    from skillagent.graph import mermaid as draw

    if not mermaid:
        _err().print("Use --mermaid to print the diagram source.", markup=False)
        raise typer.Exit(1)
    typer.echo(draw(settings=_load_settings()))


@app.command()
def doctor(
    live: Annotated[
        bool, typer.Option("--live", help="Make 2 real LLM calls (uses free-tier quota).")
    ] = False,
) -> None:
    """Check configuration (and, with --live, provider access)."""
    from skillagent.doctor import run_doctor

    raise typer.Exit(run_doctor(live=live))


# --- REPL --------------------------------------------------------------------------------

ReadLine = Callable[[str], str]


async def _read_request(read: ReadLine) -> str | None:
    """One request: lines until an empty line, or `:paste` … `:end` for text with blank
    lines. Returns None on `:quit`/`:q` or end of input."""
    lines: list[str] = []
    prompt = "> "
    while True:
        try:
            line = await asyncio.to_thread(read, prompt)
        except EOFError:
            return None if not lines else "\n".join(lines)
        stripped = line.strip()
        if not lines and stripped in _QUIT:
            return None
        if not lines and stripped == _PASTE:
            return await _read_paste(read)
        if not stripped:
            if lines:
                return "\n".join(lines)
            continue
        lines.append(line)
        prompt = "… "


async def _read_paste(read: ReadLine) -> str | None:
    lines: list[str] = []
    while True:
        try:
            line = await asyncio.to_thread(read, "")
        except EOFError:
            return "\n".join(lines) or None
        if line.strip() == _PASTE_END:
            return "\n".join(lines)
        lines.append(line)


async def _repl(settings: Settings, read: ReadLine) -> None:
    """The whole session runs in this one loop with one gateway (ADR-021)."""
    console = _out()
    gateway = OpenAICompatGateway(settings, resolve_profile(settings))
    console.print(
        "skillagent — type a request, then an empty line to send. "
        f"{_PASTE} … {_PASTE_END} for multi-paragraph text, :quit to exit.",
        markup=False,
    )
    try:
        while True:
            text = await _read_request(read)
            if text is None:
                break
            if not text.strip():
                continue
            run = await run_agent(text, settings=settings, llm=gateway)
            _print_response(run)
            console.print(f"[dim]({run.total_ms / 1000:.1f} s · {run.llm_calls} LLM call(s))[/dim]")
    finally:
        await gateway.aclose()


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # e.g. a detached or replaced stream (test runners): keep it as it is.
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8")


def main() -> None:
    """Console entry point (`python -m skillagent`, `skillagent`)."""
    _force_utf8()
    app()
