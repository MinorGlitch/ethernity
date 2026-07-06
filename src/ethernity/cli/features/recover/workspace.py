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

"""Guided workspace for restoring files from a backup."""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace

from ethernity.cli.features.recover.execution import (
    RecoverDecryptResult,
    decrypt_manifest_extract_selection,
    write_recovered_outputs,
)
from ethernity.cli.features.recover.planning import (
    RecoveryPlan,
    build_recovery_plan,
    plan_from_args,
    resolve_recover_config,
    validate_recover_args,
)
from ethernity.cli.features.recover.wizard import (
    _build_recovery_review_rows,
    _load_extra_auth_frames,
    _load_shard_frames,
    _prompt_key_material,
    _prompt_recovery_input,
    _prompt_recovery_retry_stage,
    print_recover_debug,
    write_plan_outputs,
)
from ethernity.cli.shared.crypto import normalize_doc_hash_hex
from ethernity.cli.shared.io.outputs import _single_entry_uses_directory_output
from ethernity.cli.shared.log import _warn
from ethernity.cli.shared.recovery_prompts import _resolve_recover_output
from ethernity.cli.shared.types import RecoverArgs
from ethernity.cli.shared.ui_api import (
    WorkspaceSection,
    build_review_table,
    console,
    console_err,
    panel,
    print_workspace,
    prompt_choice,
    prompt_int,
    prompt_optional,
    prompt_optional_path_with_picker,
    prompt_workspace_action,
    prompt_yes_no,
    ui_screen_mode,
    wizard_flow,
    wizard_stage,
    wizard_substep,
)
from ethernity.encoding.framing import Frame
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile


@dataclass
class _RestoreState:
    args: RecoverArgs
    quiet: bool
    debug: bool
    frames: list[Frame]
    input_label: str | None
    input_detail: str | None
    passphrase: str | None
    shard_fallback_files: list[str]
    shard_payloads_file: list[str]
    shard_scan: list[str]
    collected_shard_frames: list[Frame]
    output_path: str | None


def run_restore_workspace(args: RecoverArgs, *, debug: bool = False) -> int:
    """Run the restore workspace or execute directly when non-interactive."""

    quiet = args.quiet
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:
        recovery_plan = plan_from_args(args)
        if recovery_plan.allow_unsigned:
            _warn("Authentication check skipped - ensure you trust the source", quiet=quiet)
        return write_plan_outputs(
            recovery_plan,
            quiet=quiet,
            debug=debug,
            debug_max_bytes=args.debug_max_bytes,
            debug_reveal_secrets=args.debug_reveal_secrets,
        )

    validate_recover_args(args)
    resolve_recover_config(args)
    state = _initial_state(args, debug=debug)

    with ui_screen_mode(quiet=quiet):
        if not quiet:
            console.print("[title]Restore files[/title]")
        with wizard_flow(name="Restore", total_steps=1, quiet=quiet):
            with wizard_stage("Restore files from a backup"):
                while True:
                    sections = _workspace_sections(state)
                    print_workspace("Restore files from a backup", sections, quiet=quiet)
                    action = prompt_workspace_action(
                        "Choose next step",
                        sections,
                        proceed_label="Review and decrypt",
                        help_text=(
                            "Choose the backup source and unlock information, then preview the "
                            "recovered files before writing anything."
                        ),
                    )
                    if action == "cancel":
                        console.print("Restore cancelled.")
                        return 1
                    if action == "source":
                        _prompt_source(state)
                        continue
                    if action == "unlock":
                        _prompt_unlock(state)
                        continue
                    if action == "target":
                        _prompt_target(state)
                        continue
                    if action == "output":
                        _prompt_output(state)
                        continue
                    if action != "review":
                        continue

                    result = _review_decrypt_and_write(state)
                    if result is not None:
                        return result


def _initial_state(args: RecoverArgs, *, debug: bool) -> _RestoreState:
    working_args = replace(args)
    return _RestoreState(
        args=working_args,
        quiet=working_args.quiet,
        debug=debug,
        frames=[],
        input_label=None,
        input_detail=None,
        passphrase=working_args.passphrase,
        shard_fallback_files=list(working_args.shard_fallback_file or []),
        shard_payloads_file=list(working_args.shard_payloads_file or []),
        shard_scan=list(working_args.shard_scan or []),
        collected_shard_frames=[],
        output_path=working_args.output,
    )


def _workspace_sections(state: _RestoreState) -> list[WorkspaceSection]:
    return [
        WorkspaceSection(
            key="source",
            title="Backup source",
            status="ready" if state.frames else "missing",
            summary=_source_summary(state),
            action_label="Choose backup source",
        ),
        WorkspaceSection(
            key="unlock",
            title="Unlock",
            status="ready" if _unlock_ready(state) else "missing",
            summary=_unlock_summary(state),
            action_label="Choose unlock method",
        ),
        WorkspaceSection(
            key="target",
            title="Restore target",
            status="ready",
            summary=_target_summary(state.args),
            action_label="Choose restore target",
        ),
        WorkspaceSection(
            key="output",
            title="Output",
            status="ready",
            summary=_output_summary(state),
            action_label="Choose output now",
        ),
    ]


def _source_summary(state: _RestoreState) -> str:
    if state.input_label:
        detail = f": {state.input_detail}" if state.input_detail else ""
        return f"{state.input_label}{detail}"
    return "Choose scanned backup PDFs/images or recovery text."


def _unlock_ready(state: _RestoreState) -> bool:
    return bool(
        state.passphrase
        or state.shard_fallback_files
        or state.shard_payloads_file
        or state.shard_scan
        or state.collected_shard_frames
    )


def _unlock_summary(state: _RestoreState) -> str:
    if state.passphrase:
        return "Passphrase provided."
    shard_count = (
        len(state.shard_fallback_files)
        + len(state.shard_payloads_file)
        + len(state.shard_scan)
        + len(state.collected_shard_frames)
    )
    if shard_count:
        return f"Shard unlock material provided ({shard_count} item(s))."
    return "Choose the passphrase or printed shard documents for this backup."


def _target_summary(args: RecoverArgs) -> str:
    if args.extension_index == 0:
        target = "Root backup only."
    elif args.extension_index is not None:
        target = f"Specific extension index: {args.extension_index}."
    elif args.extension_doc_hash:
        target = "Specific extension doc hash."
    else:
        target = "Latest supplied authenticated backup."
    if args.expected_head_doc_hash:
        return f"{target} Expected head set."
    return target


def _output_summary(state: _RestoreState) -> str:
    if state.output_path:
        return state.output_path
    return "Choose after decrypt preview."


def _prompt_source(state: _RestoreState) -> None:
    with wizard_substep("Choose backup source"):
        frames, input_label, input_detail = _prompt_recovery_input(
            state.args,
            state.args.allow_unsigned,
            state.quiet,
        )
    state.frames = list(frames)
    state.input_label = input_label
    state.input_detail = input_detail


def _prompt_unlock(state: _RestoreState) -> None:
    with wizard_substep("Unlock backup"):
        (
            passphrase,
            shard_fallback_files,
            shard_payloads_file,
            shard_scan,
            collected_shard_frames,
        ) = _prompt_key_material(state.args, quiet=state.quiet)
    state.passphrase = passphrase
    state.shard_fallback_files = list(shard_fallback_files)
    state.shard_payloads_file = list(shard_payloads_file)
    state.shard_scan = list(shard_scan)
    state.collected_shard_frames = list(collected_shard_frames)
    state.args.passphrase = passphrase
    state.args.shard_fallback_file = list(shard_fallback_files)
    state.args.shard_payloads_file = list(shard_payloads_file)
    state.args.shard_scan = list(shard_scan)


def _prompt_target(state: _RestoreState) -> None:
    with wizard_substep("Choose restore target"):
        mode = prompt_choice(
            "Which backup state do you want to restore",
            {
                "latest": "Latest supplied authenticated backup",
                "root": "Root backup only",
                "index": "Specific extension index",
                "hash": "Specific extension doc hash",
            },
            default=_target_mode(state.args),
            help_text=(
                "Use latest unless you intentionally want the root backup or a specific update."
            ),
        )
    state.args.extension_index = None
    state.args.extension_doc_hash = None
    if mode == "root":
        state.args.extension_index = 0
    elif mode == "index":
        state.args.extension_index = prompt_int(
            "Extension index",
            minimum=0,
            help_text="Use 0 for the root backup, 1 for the first extension, and so on.",
        )
    elif mode == "hash":
        state.args.extension_doc_hash = _prompt_doc_hash("Extension doc hash")

    with wizard_substep("Trusted head"):
        state.args.expected_head_doc_hash = _prompt_optional_doc_hash(
            "Trusted latest backup head hash",
            default=state.args.expected_head_doc_hash,
        )


def _target_mode(args: RecoverArgs) -> str:
    if args.extension_index == 0:
        return "root"
    if args.extension_index is not None:
        return "index"
    if args.extension_doc_hash:
        return "hash"
    return "latest"


def _prompt_doc_hash(title: str) -> str:
    while True:
        value = prompt_optional(
            title,
            help_text="Paste a 32-byte document hash as 64 hex characters.",
        )
        if value is None:
            console_err.print("[error]A document hash is required for this restore target.[/error]")
            continue
        try:
            return normalize_doc_hash_hex(value, option=title.lower())
        except ValueError as exc:
            console_err.print(f"[error]{exc}[/error]")


def _prompt_optional_doc_hash(title: str, *, default: str | None) -> str | None:
    while True:
        value = prompt_optional(
            title,
            help_text=(
                "Paste the latest trusted head hash to reject stale scan sets. Leave blank when "
                "no trusted head marker is available."
            ),
        )
        if value is None:
            return default
        try:
            return normalize_doc_hash_hex(value, option=title.lower())
        except ValueError as exc:
            console_err.print(f"[error]{exc}[/error]")


def _prompt_output(state: _RestoreState) -> None:
    with wizard_substep("Choose output"):
        output_path = prompt_optional_path_with_picker(
            "Recovered output path",
            kind="path",
            allow_new=True,
            help_text=(
                "Leave blank to choose after decrypt preview. Use a directory for multi-file "
                "backups."
            ),
            picker_prompt="Select recovered output path",
            picker_help_text="Choose an existing file or folder, or enter a new path manually.",
            picker_id="restore-output",
        )
    state.output_path = output_path
    state.args.output = output_path


def _review_decrypt_and_write(state: _RestoreState) -> int | None:
    plan_result = _build_plan_or_prompt_fix(state)
    if isinstance(plan_result, int):
        return plan_result
    if plan_result is None:
        return None
    plan = plan_result
    review_rows = _build_recovery_review_rows(plan, state.args)
    if not state.quiet:
        console.print(panel("Review restore", build_review_table(review_rows)))
    if not state.args.assume_yes and not prompt_yes_no(
        "Decrypt and preview recovered files",
        default=True,
        help_text="Select no to return to the workspace without decrypting.",
    ):
        console.print("Restore cancelled.")
        return 1

    decrypted_result = _decrypt_or_prompt_fix(state, plan)
    if isinstance(decrypted_result, int):
        return decrypted_result
    if decrypted_result is None:
        return None
    decrypted = decrypted_result

    manifest = decrypted.manifest
    extracted = decrypted.extracted
    if state.debug:
        print_recover_debug(
            manifest=manifest,
            extracted=extracted,
            ciphertext=plan.ciphertext,
            passphrase=plan.passphrase,
            auth_status=plan.auth_status,
            allow_unsigned=plan.allow_unsigned,
            output_path=state.args.output,
            debug_max_bytes=state.args.debug_max_bytes,
            reveal_secrets=state.args.debug_reveal_secrets,
        )

    output_path = _choose_output_after_preview(state, plan, manifest, extracted)
    should_write = state.args.assume_yes or prompt_yes_no(
        "Write recovered files",
        default=True,
        help_text="Select no to return to the workspace without writing files.",
    )
    if not should_write:
        console.print("Restore cancelled.")
        return 1
    _write_restored_outputs(
        plan=plan,
        decrypted=decrypted,
        manifest=manifest,
        extracted=extracted,
        output_path=output_path,
        quiet=state.quiet,
    )
    return 0


def _build_plan_or_prompt_fix(state: _RestoreState) -> RecoveryPlan | int | None:
    try:
        extra_auth_frames = _load_extra_auth_frames(
            state.args,
            state.args.allow_unsigned,
            state.quiet,
        )
        shard_frames = _load_shard_frames(
            state.shard_fallback_files,
            state.shard_payloads_file,
            state.shard_scan,
            extra_frames=state.collected_shard_frames,
            quiet=state.quiet,
        )
        plan = build_recovery_plan(
            frames=state.frames,
            extra_auth_frames=extra_auth_frames,
            shard_frames=shard_frames,
            passphrase=state.passphrase,
            allow_unsigned=state.args.allow_unsigned,
            input_label=state.input_label,
            input_detail=state.input_detail,
            shard_fallback_files=state.shard_fallback_files,
            shard_payloads_file=state.shard_payloads_file,
            shard_scan=list(state.shard_scan),
            output_path=state.args.output,
            root_dir=None,
            extension_index=state.args.extension_index,
            extension_doc_hash=state.args.extension_doc_hash,
            expected_head_doc_hash=state.args.expected_head_doc_hash,
            args=state.args,
            quiet=state.quiet,
        )
        if plan.allow_unsigned:
            _warn("Authentication check skipped - ensure you trust the source", quiet=state.quiet)
        return plan
    except ValueError as exc:
        return _handle_recoverable_error(state, exc)


def _decrypt_or_prompt_fix(
    state: _RestoreState,
    plan: RecoveryPlan,
) -> RecoverDecryptResult | int | None:
    try:
        return decrypt_manifest_extract_selection(plan, quiet=state.quiet, debug=state.debug)
    except ValueError as exc:
        return _handle_recoverable_error(state, exc)


def _handle_recoverable_error(state: _RestoreState, exc: ValueError) -> int | None:
    if state.quiet:
        raise exc
    retry_stage = _prompt_recovery_retry_stage(exc)
    if retry_stage == "cancel":
        console.print("Restore cancelled.")
        return 1
    if retry_stage == "input":
        _prompt_source(state)
        return None
    _prompt_unlock(state)
    return None


def _choose_output_after_preview(
    state: _RestoreState,
    plan: RecoveryPlan,
    manifest: EnvelopeManifest,
    extracted: list[tuple[ManifestFile, bytes]],
) -> str | None:
    with wizard_substep("Choose output"):
        output_path = _resolve_recover_output(
            extracted,
            state.args.output,
            interactive=True,
            doc_id=plan.doc_id,
            input_origin=manifest.input_origin,
            input_roots=manifest.input_roots,
        )
    state.output_path = output_path
    state.args.output = output_path
    return output_path


def _write_restored_outputs(
    *,
    plan: RecoveryPlan,
    decrypted: RecoverDecryptResult,
    manifest: EnvelopeManifest,
    extracted: list[tuple[ManifestFile, bytes]],
    output_path: str | None,
    quiet: bool,
) -> None:
    single_entry_output_is_directory = (
        output_path is not None
        and len(extracted) == 1
        and manifest.input_origin in {"directory", "mixed"}
    )
    single_entry_output_is_directory = _single_entry_uses_directory_output(
        output_path,
        single_entry_output_is_directory=single_entry_output_is_directory,
    )
    write_recovered_outputs(
        extracted,
        output_path=output_path,
        auth_status=plan.auth_status,
        allow_unsigned=plan.allow_unsigned,
        quiet=quiet,
        single_entry_output_is_directory=single_entry_output_is_directory,
        requested_extension_index=plan.extension_index,
        requested_extension_doc_hash=plan.extension_doc_hash,
        expected_head_doc_hash=plan.expected_head_doc_hash,
        selected_extension_index=decrypted.selected_extension_index,
        selected_extension_doc_hash=decrypted.selected_extension_doc_hash,
    )


__all__ = ["run_restore_workspace"]
