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
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import click
import typer
from typer.core import TyperGroup

from ethernity.cli.bootstrap import registry as command_registry
from ethernity.cli.bootstrap.startup import run_startup
from ethernity.cli.features.backup.orchestrator import run_wizard
from ethernity.cli.features.compact.command import run_compact_command
from ethernity.cli.features.config.onboarding import (
    FirstRunOnboardingResult,
    run_first_run_config_wizard,
)
from ethernity.cli.features.extend.command import run_extend_command
from ethernity.cli.features.kit.command import _run_kit_render
from ethernity.cli.features.mint.workflow import run_mint_wizard
from ethernity.cli.features.recover.orchestrator import run_recover_wizard
from ethernity.cli.shared import common as cli_common, ndjson as cli_ndjson, ui_api as ui
from ethernity.cli.shared.crypto import normalize_doc_hash_hex
from ethernity.cli.shared.recovery_prompts import prompt_passphrase_unlock_material
from ethernity.cli.shared.types import BackupArgs, CliContextState, CompactArgs, ExtendArgs
from ethernity.config import CliDefaults, ExtendDefaults, load_cli_defaults
from ethernity.config.install import DEFAULT_CONFIG_PATH, resolve_api_defaults_config_path
from ethernity.crypto.sharding import MAX_SHARES


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


_HELP_OPTION_NAMES = {"help_option_names": ["-h", "--help"]}


app = typer.Typer(
    help="Ethernity CLI.",
    cls=_HelpAwareTyperGroup,
    context_settings=_HELP_OPTION_NAMES,
)

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
prompt_choice = ui.prompt_choice
prompt_home_action = ui.prompt_home_action
prompt_int = ui.prompt_int
prompt_optional = ui.prompt_optional
prompt_optional_path_with_picker = ui.prompt_optional_path_with_picker
prompt_path_with_picker = ui.prompt_path_with_picker
prompt_paths_with_picker = ui.prompt_paths_with_picker
prompt_required_secret = ui.prompt_required_secret
prompt_yes_no = ui.prompt_yes_no
ui_screen_mode = ui.ui_screen_mode

_DEFAULTS_BOOTSTRAP_SUBCOMMANDS = frozenset(
    {"api", "backup", "compact", "extend", "recover", "kit", "mint", "render"}
)
_GLOBAL_OPTIONS_WITH_VALUES = frozenset({"--config", "--paper", "--design", "--debug-max-bytes"})


@dataclass(frozen=True)
class _HomeExtendOutputPolicy:
    unlock_policy: Literal["self-contained", "reuse-root"]
    shard_threshold: int | None = None
    shard_count: int | None = None
    signing_key_mode: Literal["not-stored", "sharded"] = "not-stored"
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None


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


def _argv_invokes_api(argv: Sequence[str]) -> bool:
    """Return whether argv targets the machine-readable API surface."""

    args = list(argv)[1:]
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--":
            return False
        if arg.startswith("--"):
            if "=" in arg:
                idx += 1
                continue
            idx += 2 if arg in _GLOBAL_OPTIONS_WITH_VALUES else 1
            continue
        return arg == "api"
    return False


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
        output_dir_existing_parent=True,
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


def _split_existing_paths(paths: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split validated existing paths into file and directory lists."""

    files: list[str] = []
    directories: list[str] = []
    for value in paths:
        path = Path(value)
        if path.is_dir():
            directories.append(value)
        else:
            files.append(value)
    return files, directories


def _prompt_home_auth_inputs() -> tuple[str | None, str | None]:
    if not prompt_yes_no(
        "Add extra verification data",
        default=False,
        help_text=(
            "Use this only when the backup documents do not already include "
            "usable verification data."
        ),
    ):
        return None, None

    auth_input_kind = prompt_choice(
        "How is the extra verification data stored",
        {
            "fallback": "Recovery text file",
            "payloads": "Text line file",
        },
        default="payloads",
        help_text="Choose the file format for the extra verification data you want to supply.",
    )
    if auth_input_kind == "fallback":
        return (
            prompt_path_with_picker(
                "Verification recovery text file",
                kind="file",
                help_text=(
                    "Choose the recovery text file that contains the extra verification lines."
                ),
                picker_prompt="Select verification recovery text",
                picker_help_text="Choose the verification recovery text file.",
            ),
            None,
        )
    return (
        None,
        prompt_path_with_picker(
            "Verification text line file",
            kind="file",
            help_text="Choose the text file that contains the extra verification line.",
            picker_prompt="Select verification text line file",
            picker_help_text="Choose the verification text line file.",
        ),
    )


def _prompt_home_extend_args(
    *,
    config: str | None,
    paper: str | None,
    design: str | None,
    quiet: bool,
    extend_defaults: ExtendDefaults | None = None,
) -> ExtendArgs:
    source_kind = prompt_choice(
        "What are you extending from",
        {
            "scan": "Printed or scanned backup documents",
            "folder": "Existing generated backup folder",
        },
        default="scan",
        help_text=(
            "Choose scans when the printed backup is the source of truth. Use a generated "
            "folder only when you intentionally kept the original export tree."
        ),
    )
    scan_paths: list[str] | None = None
    expected_head_doc_hash: str | None = None
    if source_kind == "scan":
        root_dir = _prompt_home_extend_scan_output_root()
        scan_paths = prompt_paths_with_picker(
            "Backup document scans",
            kind="path",
            manual_help_text=(
                "Enter root and extension PDF/image scan paths, one per line. Blank line to finish."
            ),
            empty_message="Choose at least the root backup scan.",
            picker_prompt="Select backup document scans",
            picker_help_text="Choose the scanned root and extension backup documents.",
        )
        expected_head_doc_hash = _prompt_home_extend_expected_head_doc_hash()
        allow_stale_head = expected_head_doc_hash is None and _prompt_home_extend_stale_head_ack()
    else:
        root_dir = prompt_path_with_picker(
            "Generated backup folder to append from",
            kind="dir",
            help_text=(
                "Choose this only if you kept the generated backup export tree. "
                "If you only have paper documents or fresh scans, go back and choose scans."
            ),
            picker_prompt="Select generated backup folder",
            picker_help_text="Choose the existing generated backup folder to append from.",
        )
        allow_stale_head = False
    (
        passphrase,
        shard_fallback_files,
        shard_payloads_file,
        shard_scan,
        shard_frames,
    ) = prompt_passphrase_unlock_material(
        quiet=quiet,
        choice_prompt="How do you want to unlock this backup",
        passphrase_choice_label="I have the passphrase",
        shard_choice_label="I have printed shard documents",
        choice_help_text=(
            "Choose the unlock information for the existing backup before selecting files to add."
        ),
        passphrase_prompt="Passphrase",
        passphrase_help_text="Enter the passphrase for the backup you are updating.",
    )
    selected_paths = prompt_paths_with_picker(
        "Files or folders to add",
        kind="path",
        manual_help_text=(
            "Enter one or more existing file or folder paths to include. Blank line to finish."
        ),
        empty_message="Choose at least one file or folder to add to the backup.",
    )
    input_files, input_dirs = _split_existing_paths(selected_paths)
    output_policy = _prompt_home_extend_output_policy(extend_defaults)
    return ExtendArgs(
        config=config,
        paper=paper,
        design=design,
        root_dir=root_dir,
        scan=scan_paths,
        input=input_files or None,
        input_dir=input_dirs or None,
        passphrase=passphrase,
        shard_fallback_file=shard_fallback_files or None,
        shard_payloads_file=shard_payloads_file or None,
        shard_scan=shard_scan or None,
        shard_frames=shard_frames or None,
        unlock_policy=output_policy.unlock_policy,
        shard_threshold=output_policy.shard_threshold,
        shard_count=output_policy.shard_count,
        signing_key_mode=output_policy.signing_key_mode,
        signing_key_shard_threshold=output_policy.signing_key_shard_threshold,
        signing_key_shard_count=output_policy.signing_key_shard_count,
        expected_head_doc_hash=expected_head_doc_hash,
        allow_stale_head=allow_stale_head,
        quiet=quiet,
    )


def _prompt_home_extend_expected_head_doc_hash() -> str | None:
    while True:
        value = prompt_optional(
            "Trusted latest extension head doc_hash",
            help_text=(
                "Paste the latest trusted extension head doc_hash to reject stale scan sets. "
                "Leave blank only when no trusted head marker is available."
            ),
        )
        if value is None:
            return None
        try:
            return normalize_doc_hash_hex(value, option="expected head doc_hash")
        except ValueError as exc:
            console_err.print(f"[error]{exc}[/error]")


def _prompt_home_extend_stale_head_ack() -> bool:
    return prompt_yes_no(
        "Continue without a trusted latest head hash",
        default=False,
        help_text=(
            "Only continue if these scans are known to be the latest extension chain state. "
            "Otherwise paste the trusted latest head doc_hash to reject stale scan sets."
        ),
    )


def _prompt_home_extend_scan_output_root() -> str:
    while True:
        root_dir = prompt_optional_path_with_picker(
            "Output folder for new extension artifacts",
            kind="dir",
            allow_new=True,
            help_text=(
                "Choose a new or empty folder where extension artifacts will be published. "
                "The scanned documents remain the source used to authenticate the existing chain."
            ),
            picker_prompt="Select output folder",
            picker_help_text="Choose the folder where the extension artifacts will be written.",
        )
        if root_dir:
            return root_dir
        console_err.print("[error]Choose an output folder for the extension artifacts.[/error]")


def _prompt_home_extend_output_policy(
    extend_defaults: ExtendDefaults | None,
) -> _HomeExtendOutputPolicy:
    default_shard_count = extend_defaults.shard_count if extend_defaults is not None else None
    default_shard_threshold = (
        extend_defaults.shard_threshold if extend_defaults is not None else None
    )
    mode = prompt_choice(
        "How should this extension be recoverable",
        {
            "extension-shards": "Create extension passphrase shard documents",
            "reuse-root": "Use the root backup shard documents",
            "plaintext": "Print the passphrase in the extension recovery document",
        },
        default="extension-shards",
        help_text=(
            "Choose where the recovery material for this extension should live. "
            "Extension shards are safest when you are not sure the root shard set is available."
        ),
    )
    if mode == "reuse-root":
        signing_key_policy = _prompt_home_extend_signing_key_policy(extend_defaults)
        return _HomeExtendOutputPolicy(unlock_policy="reuse-root", **signing_key_policy)
    if mode == "plaintext":
        return _HomeExtendOutputPolicy(unlock_policy="self-contained", shard_count=0)

    shard_count = prompt_int(
        "Extension shard document count",
        minimum=1,
        maximum=MAX_SHARES,
        help_text=_home_extend_shard_count_help(default_shard_count),
    )
    shard_threshold = prompt_int(
        "Extension shard threshold",
        minimum=1,
        maximum=shard_count,
        help_text=_home_extend_shard_threshold_help(default_shard_threshold, shard_count),
    )
    signing_key_policy = _prompt_home_extend_signing_key_policy(extend_defaults)
    if signing_key_policy["signing_key_mode"] != "sharded":
        return _HomeExtendOutputPolicy(
            unlock_policy="self-contained",
            shard_threshold=shard_threshold,
            shard_count=shard_count,
            **signing_key_policy,
        )

    return _HomeExtendOutputPolicy(
        unlock_policy="self-contained",
        shard_threshold=shard_threshold,
        shard_count=shard_count,
        **signing_key_policy,
    )


def _prompt_home_extend_signing_key_policy(
    extend_defaults: ExtendDefaults | None,
) -> dict[str, Any]:
    default_signing_key_mode = (
        extend_defaults.signing_key_mode if extend_defaults is not None else "not-stored"
    )
    signing_key_mode = prompt_choice(
        "Store root/chain signing authority shards for this extension",
        {
            "not-stored": "No, do not store signing authority shards",
            "sharded": "Yes, create root/chain signing authority shard documents",
        },
        default=default_signing_key_mode if default_signing_key_mode == "sharded" else "not-stored",
        help_text=(
            "These shards can recover the root/chain signing authority, which can authorize "
            "future extensions if the root signing seed is not available elsewhere."
        ),
    )
    if signing_key_mode != "sharded":
        return {"signing_key_mode": "not-stored"}

    signing_key_shard_count = prompt_int(
        "Signing authority shard document count",
        minimum=1,
        maximum=MAX_SHARES,
        help_text=_home_extend_shard_count_help(
            extend_defaults.signing_key_shard_count if extend_defaults is not None else None
        ),
    )
    signing_key_shard_threshold = prompt_int(
        "Signing authority shard threshold",
        minimum=1,
        maximum=signing_key_shard_count,
        help_text=_home_extend_shard_threshold_help(
            extend_defaults.signing_key_shard_threshold if extend_defaults is not None else None,
            signing_key_shard_count,
        ),
    )
    return {
        "signing_key_mode": "sharded",
        "signing_key_shard_threshold": signing_key_shard_threshold,
        "signing_key_shard_count": signing_key_shard_count,
    }


def _home_extend_shard_count_help(default_count: int | None) -> str:
    suffix = f" Current configured default is {default_count}." if default_count else ""
    return f"Choose how many printed shard documents to create (1-{MAX_SHARES}).{suffix}"


def _home_extend_shard_threshold_help(default_threshold: int | None, shard_count: int) -> str:
    suffix = (
        f" Current configured default is {default_threshold}."
        if default_threshold is not None and default_threshold <= shard_count
        else ""
    )
    return f"Choose how many of the {shard_count} shard documents are required.{suffix}"


def _prompt_home_compact_args(
    *,
    config: str | None,
    paper: str | None,
    design: str | None,
    quiet: bool,
) -> CompactArgs:
    source_kind = prompt_choice(
        "What are you rebuilding from",
        {
            "scan": "Printed or scanned backup documents",
            "folder": "Existing generated backup folder",
        },
        default="scan",
        help_text=(
            "Choose scans when the printed backup is the source of truth. Use a generated "
            "folder only when you intentionally kept the original export tree."
        ),
    )
    root_dir: str | None = None
    scan_paths: list[str] | None = None
    if source_kind == "scan":
        scan_paths = prompt_paths_with_picker(
            "Backup document scans",
            kind="path",
            manual_help_text=(
                "Enter root and extension PDF/image scan paths, one per line. Blank line to finish."
            ),
            empty_message="Choose at least the root backup scan.",
            picker_prompt="Select backup document scans",
            picker_help_text="Choose the scanned root and extension backup documents.",
        )
    else:
        root_dir = prompt_path_with_picker(
            "Generated backup folder to rebuild",
            kind="dir",
            help_text=(
                "Choose this only if you kept the generated backup export tree. "
                "If you only have paper documents or fresh scans, go back and choose scans."
            ),
            picker_prompt="Select generated backup folder",
            picker_help_text="Choose the existing generated backup folder to compact.",
        )
    output_dir: str | None = None
    while output_dir is None:
        output_dir = prompt_optional_path_with_picker(
            "Output directory",
            kind="path",
            allow_new=True,
            help_text="Choose a new or empty folder where the compacted backup should be written.",
            picker_prompt="Select existing output path",
            picker_help_text=(
                "Choose an existing file or folder, or switch to manual entry for a new path."
            ),
        )
    (
        passphrase,
        shard_fallback_files,
        shard_payloads_file,
        shard_scan,
        shard_frames,
    ) = prompt_passphrase_unlock_material(
        quiet=quiet,
        choice_prompt="How do you want to unlock this backup",
        passphrase_choice_label="I have the passphrase",
        shard_choice_label="I have printed shard documents",
        choice_help_text=("Choose the unlock method for the existing backup before compacting it."),
        passphrase_prompt="Passphrase",
        passphrase_help_text="Enter the passphrase for the backup you are compacting.",
    )
    return CompactArgs(
        config=config,
        paper=paper,
        design=design,
        root_dir=root_dir,
        scan=scan_paths,
        output_dir=output_dir,
        passphrase=passphrase,
        shard_fallback_file=shard_fallback_files or None,
        shard_payloads_file=shard_payloads_file or None,
        shard_scan=shard_scan or None,
        shard_frames=shard_frames or None,
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
) -> str | None:
    try:
        if _should_run_first_run_onboarding(invoked_subcommand):
            result = run_first_run_config_wizard(config_path=config_path, quiet=quiet)
            if isinstance(result, FirstRunOnboardingResult):
                return result.launch_action
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
    return None


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
        extend_defaults=cli_defaults.extend,
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
    initial_action: str | None = None,
) -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        console_err.print(
            "[red]Error:[/red] No subcommand provided. "
            "Run `ethernity --help` for available commands."
        )
        raise typer.Exit(code=2)

    config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
    state = ctx.obj if isinstance(ctx.obj, CliContextState) else CliContextState()
    action = initial_action
    if action is None:
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

    if action == "extend":
        extend_args = _prompt_home_extend_args(
            config=config_value,
            paper=paper_value,
            design=design,
            quiet=quiet,
            extend_defaults=state.extend_defaults,
        )
        _run_cli(lambda: run_extend_command(extend_args, debug=debug), debug=debug)
        return

    if action == "compact":
        compact_args = _prompt_home_compact_args(
            config=config_value,
            paper=paper_value,
            design=design,
            quiet=quiet,
        )
        _run_cli(lambda: run_compact_command(compact_args, debug=debug), debug=debug)
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
        onboarding_launch_action = _run_first_run_onboarding_if_needed(
            invoked_subcommand=ctx.invoked_subcommand,
            config_path=config,
            quiet=quiet,
            debug=debug,
        )
    else:
        onboarding_launch_action = None

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
            initial_action=onboarding_launch_action,
        )


command_registry.register(app)


def main() -> None:
    if not _argv_invokes_api(sys.argv):
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
