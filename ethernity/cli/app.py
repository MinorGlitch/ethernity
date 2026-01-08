#!/usr/bin/env python3
from __future__ import annotations

import sys

import typer

from .core.common import _get_version, _paper_callback, _resolve_config_and_paper, _run_cli
from .flows.backup import run_wizard
from .flows.recover import run_recover_wizard
from . import command_registry
from .startup import run_startup
from .api import (
    DEBUG_MAX_BYTES_DEFAULT,
    console,
    console_err,
    _empty_recover_args,
    _prompt_home_action,
)

app = typer.Typer(add_completion=True, help="Ethernity CLI.")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"ethernity {_get_version()}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def cli(
    ctx: typer.Context,
    config: str | None = typer.Option(
        None,
        "--config",
        help="Use this TOML config (overrides paper preset).",
        rich_help_panel="Global",
    ),
    paper: str | None = typer.Option(
        None,
        "--paper",
        help="Paper preset (A4/LETTER).",
        callback=_paper_callback,
        rich_help_panel="Global",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Show plaintext debug details.",
        rich_help_panel="Debug",
    ),
    debug_max_bytes: int = typer.Option(
        DEBUG_MAX_BYTES_DEFAULT,
        "--debug-max-bytes",
        help=f"Limit debug dump size (default: {DEBUG_MAX_BYTES_DEFAULT}, 0 = no limit).",
        rich_help_panel="Debug",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        help="Hide non-error output.",
        rich_help_panel="Global",
    ),
    no_color: bool = typer.Option(
        False,
        "--no-color",
        help="Disable colored output.",
        rich_help_panel="Accessibility",
    ),
    no_animations: bool = typer.Option(
        False,
        "--no-animations",
        help="Reduce motion by disabling spinners and animated updates.",
        rich_help_panel="Accessibility",
    ),
    init_config: bool = typer.Option(
        False,
        "--init-config",
        help="Copy defaults to the user config directory and exit.",
        is_eager=True,
        rich_help_panel="Config",
    ),
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
        rich_help_panel="Info",
    ),
) -> None:
    _ = version
    try:
        should_exit = run_startup(
            quiet=quiet,
            no_color=no_color,
            no_animations=no_animations,
            debug=debug,
            init_config=init_config,
        )
    except Exception as exc:
        console_err.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2)
    if should_exit:
        raise typer.Exit()
    ctx.ensure_object(dict)
    ctx.obj.update(
        {
            "config": config,
            "paper": paper,
            "debug": debug,
            "debug_max_bytes": debug_max_bytes,
            "quiet": quiet,
            "no_color": no_color,
            "no_animations": no_animations,
        }
    )
    if ctx.invoked_subcommand is None:
        if not sys.stdin.isatty():
            console_err.print(
                "[red]Error:[/red] No subcommand provided. Use `ethernity backup` or "
                "`ethernity recover`."
            )
            raise typer.Exit(code=2)
        config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
        action = _prompt_home_action(quiet=quiet)
        if action == "recover":
            args = _empty_recover_args(config=config_value, paper=paper_value, quiet=quiet)
            _run_cli(lambda: run_recover_wizard(args), debug=debug)
        else:
            _run_cli(
                lambda: run_wizard(
                    debug_override=debug if debug else None,
                    debug_max_bytes=debug_max_bytes,
                    config_path=config_value,
                    paper_size=paper_value,
                    quiet=quiet,
                    args=None,
                ),
                debug=debug,
            )


command_registry.register(app)


def main() -> None:
    app()
