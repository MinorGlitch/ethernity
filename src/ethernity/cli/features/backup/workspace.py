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

"""Guided workspace for creating a backup."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ethernity.cli.features.backup.orchestrator import (
    _apply_qr_chunk_size_override,
    _build_review_rows,
    _format_backup_input_error,
    _maybe_save_backup_defaults,
    _print_completion_actions,
    _prompt_design,
    _prompt_encryption,
    _prompt_layout,
    _prompt_recovery_options,
    run_backup,
)
from ethernity.cli.features.backup.planning import build_document_plan
from ethernity.cli.shared.io.inputs import _load_input_files
from ethernity.cli.shared.plan import _validate_backup_args
from ethernity.cli.shared.types import BackupArgs, BackupResult, InputFile
from ethernity.cli.shared.ui.summary import print_backup_summary
from ethernity.cli.shared.ui_api import (
    DEBUG_MAX_BYTES_DEFAULT,
    WorkspaceSection,
    build_review_table,
    console,
    console_err,
    panel,
    print_workspace,
    progress,
    prompt_optional_path_with_picker,
    prompt_paths_with_picker,
    prompt_workspace_action,
    prompt_yes_no,
    ui_screen_mode,
    wizard_flow,
    wizard_stage,
    wizard_substep,
)
from ethernity.config import (
    AppConfig,
    apply_template_design,
    first_run_onboarding_configured_fields,
    load_app_config,
)
from ethernity.core.models import DocumentPlan, ShardingConfig, SigningSeedMode


@dataclass
class _CreateBackupState:
    args: BackupArgs
    config_path: str | None
    paper: str | None
    design: str | None
    quiet: bool
    debug_override: bool | None
    debug_max_bytes: int
    debug_reveal_secrets: bool
    config: AppConfig
    selected_paths: list[str]
    input_files: list[InputFile]
    resolved_base: Path | None
    output_dir: str | None
    input_origin: str
    input_roots: list[str]
    passphrase: str | None
    passphrase_words: int | None
    sealed: bool
    debug: bool
    signing_seed_mode: SigningSeedMode
    sharding: ShardingConfig | None
    signing_seed_sharding: ShardingConfig | None
    recovery_chosen: bool = False


def run_create_backup_workspace(
    *,
    debug_override: bool | None = None,
    debug_max_bytes: int = DEBUG_MAX_BYTES_DEFAULT,
    debug_reveal_secrets: bool = False,
    config_path: str | None = None,
    paper_size: str | None = None,
    quiet: bool = False,
    args: BackupArgs | None = None,
) -> int:
    """Run the create-backup workspace and execute the resulting backup."""

    working_args = replace(args) if args is not None else BackupArgs(quiet=quiet)
    if working_args.output_dir is not None:
        working_args.output_dir_existing_parent = True
    state = _initial_state(
        working_args,
        config_path=config_path or working_args.config,
        paper_size=paper_size or working_args.paper,
        quiet=quiet,
        debug_override=debug_override,
        debug_max_bytes=debug_max_bytes,
        debug_reveal_secrets=debug_reveal_secrets,
    )
    configured_fields = first_run_onboarding_configured_fields()

    with ui_screen_mode(quiet=quiet):
        with wizard_flow(name="Create backup", total_steps=1, quiet=quiet):
            with wizard_stage("Create a backup"):
                while True:
                    sections = _workspace_sections(state)
                    print_workspace("Create a backup", sections, quiet=quiet)
                    action = prompt_workspace_action(
                        "Choose next step",
                        sections,
                        proceed_label="Review and create backup",
                        help_text=(
                            "Fill the required sections, then review the backup before anything "
                            "is written."
                        ),
                    )
                    if action == "cancel":
                        console.print("Backup cancelled.")
                        return 1
                    if action == "files":
                        _prompt_files_and_output(state)
                        continue
                    if action == "passphrase":
                        _prompt_passphrase(state)
                        continue
                    if action == "recovery":
                        _prompt_recovery(state)
                        continue
                    if action == "layout":
                        _prompt_layout_section(state)
                        continue
                    if action != "review":
                        continue

                    result = _review_and_run(state, configured_fields=configured_fields)
                    if result is not None:
                        return result


def _initial_state(
    args: BackupArgs,
    *,
    config_path: str | None,
    paper_size: str | None,
    quiet: bool,
    debug_override: bool | None,
    debug_max_bytes: int,
    debug_reveal_secrets: bool,
) -> _CreateBackupState:
    design = args.design
    config = _resolved_config(config_path, paper_size, design, args.qr_chunk_size)
    return _CreateBackupState(
        args=args,
        config_path=config_path,
        paper=paper_size,
        design=design,
        quiet=quiet,
        debug_override=debug_override,
        debug_max_bytes=debug_max_bytes,
        debug_reveal_secrets=debug_reveal_secrets,
        config=config,
        selected_paths=[],
        input_files=[],
        resolved_base=None,
        output_dir=args.output_dir,
        input_origin="file",
        input_roots=[],
        passphrase=args.passphrase,
        passphrase_words=args.passphrase_words,
        sealed=args.sealed,
        debug=bool(debug_override),
        signing_seed_mode=SigningSeedMode(args.signing_key_mode or SigningSeedMode.EMBEDDED.value),
        sharding=_args_sharding(args),
        signing_seed_sharding=_args_signing_sharding(args),
        recovery_chosen=False,
    )


def _resolved_config(
    config_path: str | None,
    paper_size: str | None,
    design: str | None,
    qr_chunk_size: int | None,
) -> AppConfig:
    config = _apply_qr_chunk_size_override(
        apply_template_design(
            load_app_config(config_path, paper_size=paper_size),
            design,
        ),
        qr_chunk_size,
    )
    return config


def _args_sharding(args: BackupArgs) -> ShardingConfig | None:
    if args.shard_threshold is None or args.shard_count is None:
        return None
    return ShardingConfig(threshold=args.shard_threshold, shares=args.shard_count)


def _args_signing_sharding(args: BackupArgs) -> ShardingConfig | None:
    if args.signing_key_shard_threshold is None or args.signing_key_shard_count is None:
        return None
    return ShardingConfig(
        threshold=args.signing_key_shard_threshold,
        shares=args.signing_key_shard_count,
    )


def _workspace_sections(state: _CreateBackupState) -> list[WorkspaceSection]:
    return [
        WorkspaceSection(
            key="files",
            title="Files and output",
            status="ready" if state.input_files else "missing",
            summary=_files_summary(state),
            action_label="Choose files and output",
        ),
        WorkspaceSection(
            key="passphrase",
            title="Passphrase",
            status="ready" if _passphrase_ready(state) else "missing",
            summary=_passphrase_summary(state),
            action_label="Choose passphrase",
        ),
        WorkspaceSection(
            key="recovery",
            title="Recovery policy",
            status="ready" if state.recovery_chosen else "missing",
            summary=_recovery_summary(state),
            action_label="Choose recovery policy",
        ),
        WorkspaceSection(
            key="layout",
            title="Layout",
            status="ready",
            summary=_layout_summary(state),
            action_label="Review layout",
        ),
    ]


def _files_summary(state: _CreateBackupState) -> str:
    if not state.input_files:
        return "Choose files or folders and where to save the backup."
    output = state.output_dir or "default backup-<id> folder"
    return f"{len(state.input_files)} file(s), output: {output}"


def _passphrase_ready(state: _CreateBackupState) -> bool:
    return state.passphrase is not None or state.passphrase_words is not None


def _passphrase_summary(state: _CreateBackupState) -> str:
    if state.passphrase is not None:
        return "Passphrase provided."
    if state.passphrase_words is not None:
        return f"Auto-generate a {state.passphrase_words}-word passphrase."
    return "Provide a passphrase or generate a recovery phrase."


def _recovery_summary(state: _CreateBackupState) -> str:
    if not state.recovery_chosen:
        return "Choose shard recovery and signing authority handling."
    if state.sharding is None:
        return "Shard documents disabled."
    sealed = ", sealed" if state.sealed else ""
    if state.signing_seed_mode == SigningSeedMode.SHARDED:
        signing = ", signing authority shards"
    elif state.sealed:
        signing = ", signing authority not stored"
    else:
        signing = ", signing authority in main document"
    return f"{state.sharding.threshold} of {state.sharding.shares} shards{sealed}{signing}"


def _layout_summary(state: _CreateBackupState) -> str:
    design = state.design or state.config.template_path.parent.name
    return f"{state.paper or state.config.paper_size}, {design}"


def _prompt_files_and_output(state: _CreateBackupState) -> None:
    while True:
        with wizard_substep("Choose files"):
            selected_paths = prompt_paths_with_picker(
                "Files or folders to back up",
                picker_prompt="Select files or folders",
                kind="path",
                manual_help_text="Enter file or directory paths; blank line to finish.",
                picker_help_text="Open folders and add paths. Use Done when complete.",
                empty_message="Choose at least one file or folder to back up.",
                stdin_message="Stdin input is not supported in the workspace.",
                picker_id="backup-inputs",
            )
        output_help = (
            "Press Enter to keep the saved default output directory, enter a new path, or pick "
            "an existing folder."
            if state.output_dir
            else "Leave blank to create a backup-<id> folder in the current directory."
        )
        with wizard_substep("Choose output folder"):
            output_dir = prompt_optional_path_with_picker(
                "Output folder",
                kind="dir",
                allow_new=True,
                help_text=output_help,
                picker_prompt="Select output folder",
                picker_help_text="Choose an existing folder, or enter a new path manually.",
                picker_id="backup-output-folder",
            )
        if output_dir is not None:
            state.output_dir = output_dir
            state.args.output_dir = output_dir
            state.args.output_dir_existing_parent = True
        try:
            with progress(quiet=state.quiet or state.debug) as progress_bar:
                input_files, resolved_base, input_origin, input_roots = _load_input_files(
                    selected_paths,
                    [],
                    state.args.base_dir,
                    allow_stdin=False,
                    progress=progress_bar,
                )
        except ValueError as exc:
            console_err.print(f"[error]{_format_backup_input_error(exc)}[/error]")
            continue
        state.selected_paths = selected_paths
        state.input_files = input_files
        state.resolved_base = resolved_base
        state.input_origin = input_origin
        state.input_roots = input_roots
        state.args.base_dir = str(resolved_base) if resolved_base is not None else None
        input_values, input_dirs = _split_selected_paths(selected_paths)
        state.args.input = input_values or None
        state.args.input_dir = input_dirs or None
        return


def _split_selected_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    files: list[str] = []
    directories: list[str] = []
    for value in paths:
        if Path(value).is_dir():
            directories.append(value)
        else:
            files.append(value)
    return files, directories


def _prompt_passphrase(state: _CreateBackupState) -> None:
    with wizard_substep("Passphrase"):
        passphrase, passphrase_words = _prompt_encryption(state.args)
    state.passphrase = passphrase
    state.passphrase_words = passphrase_words
    state.args.passphrase = passphrase
    state.args.passphrase_words = passphrase_words


def _prompt_recovery(state: _CreateBackupState) -> None:
    with wizard_substep("Recovery policy"):
        sealed, debug, signing_seed_mode, sharding, signing_seed_sharding = (
            _prompt_recovery_options(
                state.args,
                state.debug_override,
                state.quiet,
                confirm_existing_quorums=True,
                prompt_sharding_when_missing=True,
                prompt_signing_sharding_when_missing=True,
            )
        )
    state.sealed = sealed
    state.debug = debug
    state.signing_seed_mode = signing_seed_mode
    state.sharding = sharding
    state.signing_seed_sharding = signing_seed_sharding
    state.recovery_chosen = True
    state.args.sealed = sealed
    state.args.debug = debug
    state.args.shard_threshold = sharding.threshold if sharding else None
    state.args.shard_count = sharding.shares if sharding else None
    state.args.signing_key_mode = signing_seed_mode.value
    state.args.signing_key_shard_threshold = (
        signing_seed_sharding.threshold if signing_seed_sharding else None
    )
    state.args.signing_key_shard_count = (
        signing_seed_sharding.shares if signing_seed_sharding else None
    )


def _prompt_layout_section(state: _CreateBackupState) -> None:
    with wizard_substep("Layout"):
        config_path, paper = _prompt_layout(state.config_path, state.paper)
        state.config_path = config_path
        state.paper = paper
        state.args.config = config_path
        state.args.paper = paper
        state.design = _prompt_design(state.args)
        state.args.design = state.design
        state.config = _resolved_config(
            state.config_path,
            state.paper,
            state.design,
            state.args.qr_chunk_size,
        )


def _review_and_run(
    state: _CreateBackupState,
    *,
    configured_fields: frozenset[str],
) -> int | None:
    plan = _document_plan(state)
    try:
        _validate_backup_args(state.args)
    except ValueError as exc:
        console_err.print(f"[error]{exc}[/error]")
        return None
    review_rows = _build_review_rows(
        state.passphrase,
        state.passphrase_words,
        plan,
        state.input_files,
        state.resolved_base,
        state.output_dir,
        state.config_path,
        state.paper,
        state.design,
        state.config,
        state.debug,
    )
    console.print(panel("Review backup", build_review_table(review_rows)))
    if not state.args.assume_yes and not prompt_yes_no(
        "Create backup documents",
        default=True,
        help_text="Select no to return to the workspace without writing anything.",
    ):
        console.print("Backup cancelled.")
        return 1
    result = _run_backup_from_state(state, plan)
    print_backup_summary(result, plan, state.passphrase, quiet=state.quiet)
    _print_completion_actions(result, state.quiet)
    _maybe_save_backup_defaults(
        config_path=state.config_path,
        config=state.config,
        plan=plan,
        output_dir=state.output_dir,
        quiet=state.quiet,
        configured_fields=configured_fields,
    )
    return 0


def _document_plan(state: _CreateBackupState) -> DocumentPlan:
    return build_document_plan(
        sealed=state.sealed,
        signing_seed_mode=state.signing_seed_mode,
        sharding=state.sharding,
        signing_seed_sharding=state.signing_seed_sharding,
    )


def _run_backup_from_state(state: _CreateBackupState, plan: DocumentPlan) -> BackupResult:
    return run_backup(
        input_files=state.input_files,
        base_dir=state.resolved_base,
        output_dir=state.output_dir,
        output_dir_existing_parent=state.args.output_dir_existing_parent,
        layout_debug_dir=state.args.layout_debug_dir,
        input_origin=state.input_origin,
        input_roots=state.input_roots,
        plan=plan,
        passphrase=state.passphrase,
        passphrase_words=state.passphrase_words,
        config=state.config,
        debug=state.debug,
        debug_max_bytes=state.debug_max_bytes,
        debug_reveal_secrets=state.debug_reveal_secrets,
        quiet=state.quiet,
    )


__all__ = ["run_create_backup_workspace"]
