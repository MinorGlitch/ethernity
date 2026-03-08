#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Annotated

import typer

from ..config import load_cli_defaults
from . import command_registry
from .api import (
    DEBUG_MAX_BYTES_DEFAULT,
    configure_ui,
    console,
    console_err,
    empty_recover_args,
    prompt_home_action,
    ui_screen_mode,
)
from .commands.kit import _run_kit_render
from .core.common import _get_version, _paper_callback, _resolve_config_and_paper, _run_cli
from .core.types import BackupArgs, CliContextState
from .flows.backup import run_wizard
from .flows.first_run_config import run_first_run_config_wizard
from .flows.recover import run_recover_wizard
from .startup import run_startup

app = typer.Typer(add_completion=False, help="Ethernity CLI.")

_DEFAULTS_BOOTSTRAP_SUBCOMMANDS = frozenset({"backup", "recover", "kit", "render"})


def _subcommand_config_override(argv: Sequence[str]) -> str | None:
    """Extract `--config` from argv so subcommand config can bootstrap defaults."""

    args = list(argv)[1:]
    config_path: str | None = None
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--":
            break
        if arg == "--config":
            if idx + 1 < len(args):
                config_path = args[idx + 1]
                idx += 2
                continue
            break
        if arg.startswith("--config="):
            config_path = arg.split("=", 1)[1]
        idx += 1
    return config_path


def _should_use_subcommand_config_for_defaults(invoked_subcommand: str | None) -> bool:
    """Return whether defaults bootstrap should honor subcommand `--config`."""

    return invoked_subcommand in _DEFAULTS_BOOTSTRAP_SUBCOMMANDS


def _should_run_first_run_onboarding(invoked_subcommand: str | None) -> bool:
    """Return whether first-run onboarding should run in this invocation."""

    if invoked_subcommand is not None:
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _home_backup_wizard_args(
    *,
    state: CliContextState | None,
    config: str | None,
    paper: str | None,
    design: str | None,
    debug_max_bytes: int,
    debug_reveal_secrets: bool,
    quiet: bool,
) -> BackupArgs:
    """Build backup wizard args for the interactive home screen flow."""

    backup_defaults = state.backup_defaults if state is not None else None
    return BackupArgs(
        config=config,
        paper=paper,
        design=design,
        base_dir=backup_defaults.base_dir if backup_defaults is not None else None,
        output_dir=backup_defaults.output_dir if backup_defaults is not None else None,
        shard_threshold=backup_defaults.shard_threshold if backup_defaults is not None else None,
        shard_count=backup_defaults.shard_count if backup_defaults is not None else None,
        signing_key_mode=backup_defaults.signing_key_mode if backup_defaults is not None else None,
        signing_key_shard_threshold=(
            backup_defaults.signing_key_shard_threshold if backup_defaults is not None else None
        ),
        signing_key_shard_count=(
            backup_defaults.signing_key_shard_count if backup_defaults is not None else None
        ),
        debug_max_bytes=debug_max_bytes,
        debug_reveal_secrets=debug_reveal_secrets,
        quiet=quiet,
    )


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"ethernity {_get_version()}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def cli(
    ctx: typer.Context,
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            help="Use this TOML config file.",
            rich_help_panel="Global",
        ),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option(
            "--paper",
            help="Paper size override (A4/Letter).",
            callback=_paper_callback,
            rich_help_panel="Global",
        ),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option(
            "--design",
            help="Template design folder (auto-discovered under templates/).",
            rich_help_panel="Global",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Show plaintext debug details.",
            rich_help_panel="Debug",
        ),
    ] = False,
    debug_max_bytes: Annotated[
        int | None,
        typer.Option(
            "--debug-max-bytes",
            help=f"Limit debug dump size (default: {DEBUG_MAX_BYTES_DEFAULT}, 0 = no limit).",
            show_default=str(DEBUG_MAX_BYTES_DEFAULT),
            rich_help_panel="Debug",
        ),
    ] = None,
    debug_reveal_secrets: Annotated[
        bool,
        typer.Option(
            "--debug-reveal-secrets",
            help=(
                "Reveal full passphrase and private key material in debug output. "
                "Use only in a controlled local terminal; logs and screen capture "
                "can expose secrets."
            ),
            rich_help_panel="Debug",
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            help="Hide non-error output.",
            rich_help_panel="Global",
        ),
    ] = False,
    no_color: Annotated[
        bool,
        typer.Option(
            "--no-color",
            help="Disable colored output.",
            rich_help_panel="Accessibility",
        ),
    ] = False,
    no_animations: Annotated[
        bool,
        typer.Option(
            "--no-animations",
            help="Reduce motion by disabling spinners and animated updates.",
            rich_help_panel="Accessibility",
        ),
    ] = False,
    init_config: Annotated[
        bool,
        typer.Option(
            "--init-config",
            help="Copy defaults to the user config directory and exit.",
            is_eager=True,
            rich_help_panel="Config",
        ),
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
            rich_help_panel="Info",
        ),
    ] = False,
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
    except (OSError, RuntimeError, ValueError) as exc:
        console_err.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2)
    if should_exit:
        raise typer.Exit()
    try:
        if _should_run_first_run_onboarding(ctx.invoked_subcommand):
            run_first_run_config_wizard(
                config_path=config,
                quiet=quiet,
            )
    except KeyboardInterrupt:
        if debug:
            raise
        console_err.print("[warning]Cancelled by user.[/warning]")
        raise typer.Exit(code=130)
    except (OSError, RuntimeError, ValueError, TypeError, LookupError) as exc:
        if debug:
            raise
        console_err.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2)

    config_path_for_defaults = config
    if config_path_for_defaults is None and _should_use_subcommand_config_for_defaults(
        ctx.invoked_subcommand
    ):
        config_path_for_defaults = _subcommand_config_override(sys.argv)

    try:
        cli_defaults = load_cli_defaults(path=config_path_for_defaults)
    except (OSError, RuntimeError, ValueError) as exc:
        console_err.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2)

    effective_quiet = quiet or cli_defaults.ui.quiet
    effective_no_color = no_color or cli_defaults.ui.no_color
    effective_no_animations = no_animations or cli_defaults.ui.no_animations
    effective_debug_max_bytes = (
        cli_defaults.debug.max_bytes if debug_max_bytes is None else debug_max_bytes
    )
    if effective_debug_max_bytes is None:
        effective_debug_max_bytes = DEBUG_MAX_BYTES_DEFAULT

    configure_ui(no_color=effective_no_color, no_animations=effective_no_animations)

    ctx.obj = CliContextState(
        config=config,
        paper=paper,
        design=design,
        debug=debug,
        debug_max_bytes=effective_debug_max_bytes,
        debug_reveal_secrets=debug_reveal_secrets,
        quiet=effective_quiet,
        no_color=effective_no_color,
        no_animations=effective_no_animations,
        backup_defaults=cli_defaults.backup,
        recover_defaults=cli_defaults.recover,
    )
    if ctx.invoked_subcommand is None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            console_err.print(
                "[red]Error:[/red] No subcommand provided. "
                "Run `ethernity --help` for available commands."
            )
            raise typer.Exit(code=2)
        config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
        with ui_screen_mode(quiet=effective_quiet):
            action = prompt_home_action(quiet=effective_quiet)
        if action == "recover":
            args = empty_recover_args(
                config=config_value,
                paper=paper_value,
                quiet=effective_quiet,
                debug_max_bytes=effective_debug_max_bytes,
                debug_reveal_secrets=debug_reveal_secrets,
            )
            _run_cli(lambda: run_recover_wizard(args, debug=debug), debug=debug)
        elif action == "kit":
            _run_cli(
                lambda: _run_kit_render(
                    bundle=None,
                    output=None,
                    config_value=config_value,
                    paper_value=paper_value,
                    design_value=design,
                    variant_value="lean",
                    qr_chunk_size=None,
                    quiet_value=effective_quiet,
                ),
                debug=debug,
            )
        else:
            wizard_args = _home_backup_wizard_args(
                state=ctx.obj,
                config=config_value,
                paper=paper_value,
                design=design,
                debug_max_bytes=effective_debug_max_bytes,
                debug_reveal_secrets=debug_reveal_secrets,
                quiet=effective_quiet,
            )
            _run_cli(
                lambda: run_wizard(
                    debug_override=debug if debug else None,
                    debug_max_bytes=effective_debug_max_bytes,
                    debug_reveal_secrets=debug_reveal_secrets,
                    config_path=config_value,
                    paper_size=paper_value,
                    quiet=effective_quiet,
                    args=wizard_args,
                ),
                debug=debug,
            )


command_registry.register(app)


def main() -> None:
    app()
