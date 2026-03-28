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

import click
import typer
from typer.core import TyperGroup

from ethernity.cli.bootstrap import registry as command_registry
from ethernity.cli.bootstrap.startup import run_startup
from ethernity.cli.features.backup.orchestrator import run_wizard
from ethernity.cli.features.config.onboarding import run_first_run_config_wizard
from ethernity.cli.features.kit.command import _run_kit_render
from ethernity.cli.features.mint.workflow import run_mint_wizard
from ethernity.cli.features.recover.orchestrator import run_recover_wizard
from ethernity.cli.shared import common as cli_common, ndjson as cli_ndjson, ui_api as ui
from ethernity.cli.shared.types import BackupArgs, CliContextState
from ethernity.config import CliDefaults, load_cli_defaults
from ethernity.config.install import DEFAULT_CONFIG_PATH, resolve_api_defaults_config_path


def _argv_requests_help(argv: Sequence[str]) -> bool:
    for arg in argv:
        if arg == "--":
            break
        if arg in {"--help", "-h"}:
            return True
    return False


class _HelpAwareTyperGroup(TyperGroup):
    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        ctx.meta["help_invocation"] = _argv_requests_help(args)
        return super().parse_args(ctx, args)


app = typer.Typer(add_completion=False, help="Ethernity CLI.", cls=_HelpAwareTyperGroup)

_get_version = cli_common._get_version
_paper_callback = cli_common._paper_callback
_resolve_config_and_paper = cli_common._resolve_config_and_paper
_run_cli = cli_common._run_cli
emit_error = cli_ndjson.emit_error
error_code_for_exception = cli_ndjson.error_code_for_exception
error_details_for_exception = cli_ndjson.error_details_for_exception
ndjson_session = cli_ndjson.ndjson_session
DEBUG_MAX_BYTES_DEFAULT = ui.DEBUG_MAX_BYTES_DEFAULT
configure_ui = ui.configure_ui
console = ui.console
console_err = ui.console_err
empty_mint_args = ui.empty_mint_args
empty_recover_args = ui.empty_recover_args
prompt_home_action = ui.prompt_home_action
ui_screen_mode = ui.ui_screen_mode

_DEFAULTS_BOOTSTRAP_SUBCOMMANDS = frozenset({"api", "backup", "recover", "kit", "mint", "render"})
_GLOBAL_OPTIONS_WITH_VALUES = frozenset({"--config", "--paper", "--design", "--debug-max-bytes"})


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


def _is_api_invocation(invoked_subcommand: str | None) -> bool:
    return invoked_subcommand == "api"


def _api_argv_path(argv: Sequence[str]) -> tuple[str, ...]:
    """Return the nested API command path from argv when present."""

    args = list(argv)[1:]
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--":
            return ()
        if arg.startswith("--"):
            if "=" in arg:
                idx += 1
                continue
            idx += 2 if arg in _GLOBAL_OPTIONS_WITH_VALUES else 1
            continue
        break
    if idx >= len(args) or args[idx] != "api":
        return ()
    idx += 1
    path: list[str] = []
    while idx < len(args):
        arg = args[idx]
        if arg == "--" or arg.startswith("-"):
            break
        path.append(arg)
        idx += 1
    return tuple(path)


def _is_api_config_invocation(argv: Sequence[str]) -> bool:
    path = _api_argv_path(argv)
    return len(path) >= 2 and path[0] == "config" and path[1] in {"get", "set"}


def _is_help_invocation(ctx: click.Context, argv: Sequence[str]) -> bool:
    """Return whether the current invocation is only asking for help text."""

    meta = getattr(ctx, "meta", None)
    help_invocation = meta.get("help_invocation") if isinstance(meta, dict) else False
    return (
        bool(getattr(ctx, "resilient_parsing", False))
        or bool(help_invocation)
        or _argv_requests_help(argv[1:])
    )


def _raise_api_bootstrap_error(exc: BaseException, *, exit_code: int = 2) -> None:
    details = {"error_type": type(exc).__name__}
    details.update(error_details_for_exception(exc))
    with ndjson_session():
        emit_error(code=error_code_for_exception(exc), message=str(exc), details=details)
    raise typer.Exit(code=exit_code) from exc


def _raise_api_parse_error(exc: BaseException, *, exit_code: int = 2) -> None:
    message = exc.format_message() if isinstance(exc, click.ClickException) else str(exc)
    details = {"error_type": type(exc).__name__}
    details.update(error_details_for_exception(exc))
    with ndjson_session():
        emit_error(code=error_code_for_exception(exc), message=message, details=details)
    raise SystemExit(exit_code) from exc


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


def _run_non_api_startup(
    *,
    invoked_subcommand: str | None,
    quiet: bool,
    no_color: bool,
    no_animations: bool,
    debug: bool,
    init_config: bool,
) -> None:
    if _is_api_invocation(invoked_subcommand):
        return
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
        raise typer.Exit(code=2) from exc
    if should_exit:
        raise typer.Exit()


def _run_first_run_onboarding_if_needed(
    *,
    invoked_subcommand: str | None,
    config_path: str | None,
    quiet: bool,
    debug: bool,
) -> None:
    try:
        if _should_run_first_run_onboarding(invoked_subcommand):
            run_first_run_config_wizard(config_path=config_path, quiet=quiet)
    except KeyboardInterrupt:
        if debug:
            raise
        console_err.print("[warning]Cancelled by user.[/warning]")
        raise typer.Exit(code=130) from None
    except (OSError, RuntimeError, ValueError, TypeError, LookupError) as exc:
        if debug:
            raise
        console_err.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2) from exc


def _defaults_bootstrap_config_path(
    invoked_subcommand: str | None,
    config: str | None,
    argv: Sequence[str],
) -> tuple[str | None, str | None, bool]:
    explicit_config_path = config
    if explicit_config_path is None and _should_use_subcommand_config_for_defaults(
        invoked_subcommand
    ):
        explicit_config_path = _subcommand_config_override(argv)

    config_path_for_defaults = explicit_config_path
    api_config_invocation = _is_api_config_invocation(argv)
    if (
        config_path_for_defaults is None
        and _is_api_invocation(invoked_subcommand)
        and not api_config_invocation
    ):
        config_path_for_defaults = str(resolve_api_defaults_config_path() or DEFAULT_CONFIG_PATH)

    return explicit_config_path, config_path_for_defaults, api_config_invocation


def _load_bootstrap_defaults(
    *,
    invoked_subcommand: str | None,
    config_path_for_defaults: str | None,
    api_config_invocation: bool,
    help_invocation: bool,
) -> CliDefaults:
    if api_config_invocation or help_invocation:
        return CliDefaults()
    try:
        return load_cli_defaults(path=config_path_for_defaults)
    except (OSError, RuntimeError, ValueError) as exc:
        if _is_api_invocation(invoked_subcommand):
            _raise_api_bootstrap_error(exc)
        console_err.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2) from exc


def _resolve_effective_debug_max_bytes(
    cli_defaults: CliDefaults,
    debug_max_bytes: int | None,
) -> int:
    effective_debug_max_bytes = (
        cli_defaults.debug.max_bytes if debug_max_bytes is None else debug_max_bytes
    )
    if effective_debug_max_bytes is None:
        return DEBUG_MAX_BYTES_DEFAULT
    return effective_debug_max_bytes


def _configure_cli_context(
    *,
    ctx: typer.Context,
    explicit_config_path: str | None,
    config_path_for_defaults: str | None,
    paper: str | None,
    design: str | None,
    debug: bool,
    debug_max_bytes: int,
    debug_reveal_secrets: bool,
    quiet: bool,
    no_color: bool,
    no_animations: bool,
    cli_defaults: CliDefaults,
) -> None:
    ctx.obj = CliContextState(
        config=explicit_config_path
        if explicit_config_path is not None
        else config_path_for_defaults,
        config_explicit=explicit_config_path is not None,
        paper=paper,
        design=design,
        debug=debug,
        debug_max_bytes=debug_max_bytes,
        debug_reveal_secrets=debug_reveal_secrets,
        quiet=quiet,
        no_color=no_color,
        no_animations=no_animations,
        backup_defaults=cli_defaults.backup,
        recover_defaults=cli_defaults.recover,
    )


def _run_home_screen(
    *,
    ctx: typer.Context,
    config: str | None,
    paper: str | None,
    design: str | None,
    debug: bool,
    debug_max_bytes: int,
    debug_reveal_secrets: bool,
    quiet: bool,
) -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        console_err.print(
            "[red]Error:[/red] No subcommand provided. "
            "Run `ethernity --help` for available commands."
        )
        raise typer.Exit(code=2)

    config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
    with ui_screen_mode(quiet=quiet):
        action = prompt_home_action(quiet=quiet)

    if action == "recover":
        recover_args = empty_recover_args(
            config=config_value,
            paper=paper_value,
            quiet=quiet,
            debug_max_bytes=debug_max_bytes,
            debug_reveal_secrets=debug_reveal_secrets,
        )
        _run_cli(lambda: run_recover_wizard(recover_args, debug=debug), debug=debug)
        return

    if action == "mint":
        mint_args = empty_mint_args(
            config=config_value,
            paper=paper_value,
            design=design,
            quiet=quiet,
        )
        _run_cli(lambda: run_mint_wizard(mint_args, debug=debug), debug=debug)
        return

    if action == "kit":
        _run_cli(
            lambda: _run_kit_render(
                bundle=None,
                output=None,
                config_value=config_value,
                paper_value=paper_value,
                design_value=design,
                variant_value="lean",
                qr_chunk_size=None,
                quiet_value=quiet,
            ),
            debug=debug,
        )
        return

    wizard_args = _home_backup_wizard_args(
        state=ctx.obj,
        config=config_value,
        paper=paper_value,
        design=design,
        debug_max_bytes=debug_max_bytes,
        debug_reveal_secrets=debug_reveal_secrets,
        quiet=quiet,
    )
    _run_cli(
        lambda: run_wizard(
            debug_override=debug if debug else None,
            debug_max_bytes=debug_max_bytes,
            debug_reveal_secrets=debug_reveal_secrets,
            config_path=config_value,
            paper_size=paper_value,
            quiet=quiet,
            args=wizard_args,
        ),
        debug=debug,
    )


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
    help_invocation = _is_help_invocation(ctx, sys.argv)
    if not help_invocation:
        _run_non_api_startup(
            invoked_subcommand=ctx.invoked_subcommand,
            quiet=quiet,
            no_color=no_color,
            no_animations=no_animations,
            debug=debug,
            init_config=init_config,
        )
        _run_first_run_onboarding_if_needed(
            invoked_subcommand=ctx.invoked_subcommand,
            config_path=config,
            quiet=quiet,
            debug=debug,
        )

    explicit_config_path, config_path_for_defaults, api_config_invocation = (
        _defaults_bootstrap_config_path(
            ctx.invoked_subcommand,
            config,
            sys.argv,
        )
    )
    cli_defaults = _load_bootstrap_defaults(
        invoked_subcommand=ctx.invoked_subcommand,
        config_path_for_defaults=config_path_for_defaults,
        api_config_invocation=api_config_invocation,
        help_invocation=help_invocation,
    )

    effective_quiet = quiet or cli_defaults.ui.quiet
    effective_no_color = no_color or cli_defaults.ui.no_color
    effective_no_animations = no_animations or cli_defaults.ui.no_animations
    effective_debug_max_bytes = _resolve_effective_debug_max_bytes(cli_defaults, debug_max_bytes)

    configure_ui(no_color=effective_no_color, no_animations=effective_no_animations)
    _configure_cli_context(
        ctx=ctx,
        explicit_config_path=explicit_config_path,
        config_path_for_defaults=config_path_for_defaults,
        paper=paper,
        design=design,
        debug=debug,
        debug_max_bytes=effective_debug_max_bytes,
        debug_reveal_secrets=debug_reveal_secrets,
        quiet=effective_quiet,
        no_color=effective_no_color,
        no_animations=effective_no_animations,
        cli_defaults=cli_defaults,
    )
    if ctx.invoked_subcommand is None:
        _run_home_screen(
            ctx=ctx,
            config=config,
            paper=paper,
            design=design,
            debug=debug,
            debug_max_bytes=effective_debug_max_bytes,
            debug_reveal_secrets=debug_reveal_secrets,
            quiet=effective_quiet,
        )


command_registry.register(app)


def main() -> None:
    if not _api_argv_path(sys.argv):
        app()
        return
    result: object | None = None
    try:
        result = app(standalone_mode=False)
    except click.Abort as exc:
        _raise_api_parse_error(exc, exit_code=130)
    except click.ClickException as exc:
        _raise_api_parse_error(exc, exit_code=exc.exit_code)
    except click.exceptions.Exit as exc:
        raise SystemExit(exc.exit_code) from exc
    if isinstance(result, int):
        raise SystemExit(result)
