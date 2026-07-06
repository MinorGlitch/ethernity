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

"""Guided workspace for adding files to an existing backup."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ethernity.cli.features.extend.models import PreparedExtendRun
from ethernity.cli.features.extend.service import prepare_extend_run
from ethernity.cli.shared.crypto import normalize_doc_hash_hex
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.recovery_prompts import prompt_passphrase_unlock_material
from ethernity.cli.shared.types import ExtendArgs
from ethernity.cli.shared.ui_api import (
    WorkspaceSection,
    WorkspaceStatus,
    build_review_table,
    console,
    console_err,
    panel,
    print_workspace,
    prompt_choice,
    prompt_int,
    prompt_optional,
    prompt_optional_path_with_picker,
    prompt_paths_with_picker,
    prompt_workspace_action,
    prompt_yes_no,
    ui_screen_mode,
    wizard_flow,
    wizard_stage,
    wizard_substep,
)
from ethernity.config import ExtendDefaults
from ethernity.crypto.sharding import MAX_SHARES
from ethernity.encoding.framing import Frame
from ethernity.extensions.staging import preflight_extension_publish_target

SourceKind = Literal["scan", "folder"]
UnlockPolicy = Literal["self-contained", "reuse-root"]
SigningKeyMode = Literal["not-stored", "sharded"]


@dataclass(frozen=True)
class _AddFilesOutputPolicy:
    unlock_policy: UnlockPolicy
    shard_threshold: int | None = None
    shard_count: int | None = None
    signing_key_mode: SigningKeyMode = "not-stored"
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None


@dataclass
class _AddFilesState:
    config: str | None
    paper: str | None
    design: str | None
    quiet: bool
    source_kind: SourceKind | None = None
    root_dir: str | None = None
    scan_paths: list[str] = field(default_factory=list)
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False
    passphrase: str | None = None
    shard_fallback_files: list[str] = field(default_factory=list)
    shard_payloads_file: list[str] = field(default_factory=list)
    shard_scan: list[str] = field(default_factory=list)
    shard_frames: list[Frame] = field(default_factory=list)
    selected_paths: list[str] = field(default_factory=list)
    output_policy: _AddFilesOutputPolicy | None = None


def prompt_add_files_workspace_args(
    *,
    config: str | None,
    paper: str | None,
    design: str | None,
    quiet: bool,
    extend_defaults: ExtendDefaults | None = None,
) -> ExtendArgs | None:
    """Prompt for an add-files run using a guided task workspace."""

    state = _AddFilesState(config=config, paper=paper, design=design, quiet=quiet)
    with ui_screen_mode(quiet=quiet):
        with wizard_flow(name="Add files", total_steps=1, quiet=quiet):
            with wizard_stage("Add files to a backup"):
                while True:
                    sections = _workspace_sections(state)
                    print_workspace("Add files to a backup", sections, quiet=quiet)
                    action = prompt_workspace_action(
                        "Choose next step",
                        sections,
                        proceed_label="Review and add files",
                        help_text=(
                            "Fill the required sections, then review the exact update before "
                            "anything is written."
                        ),
                    )
                    if action == "cancel":
                        console.print("Add files cancelled.")
                        return None
                    if action == "source":
                        _prompt_source(state)
                        continue
                    if action == "unlock":
                        _prompt_unlock(state)
                        continue
                    if action == "files":
                        _prompt_files(state)
                        continue
                    if action == "recovery":
                        state.output_policy = _prompt_output_policy(extend_defaults)
                        continue
                    if action != "review":
                        continue

                    args = _build_args(state)
                    prepared = _prepare_review(args)
                    if prepared is None:
                        continue
                    if _confirm_review(args, prepared):
                        return args


def _workspace_sections(state: _AddFilesState) -> list[WorkspaceSection]:
    source_status: WorkspaceStatus = "ready" if _source_ready(state) else "missing"
    if (
        state.source_kind == "scan"
        and state.root_dir
        and state.scan_paths
        and state.allow_stale_head
        and state.expected_head_doc_hash is None
    ):
        source_status = "warning"
    return [
        WorkspaceSection(
            key="source",
            title="Backup source",
            status=source_status,
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
            key="files",
            title="Files to add",
            status="ready" if state.selected_paths else "missing",
            summary=_files_summary(state.selected_paths),
            action_label="Choose files or folders",
        ),
        WorkspaceSection(
            key="recovery",
            title="Recovery policy",
            status="ready" if state.output_policy is not None else "missing",
            summary=_policy_summary(state.output_policy),
            action_label="Choose recovery policy",
        ),
    ]


def _source_ready(state: _AddFilesState) -> bool:
    if state.source_kind == "folder":
        return bool(state.root_dir)
    if state.source_kind == "scan":
        return bool(
            state.root_dir
            and state.scan_paths
            and (state.expected_head_doc_hash or state.allow_stale_head)
        )
    return False


def _unlock_ready(state: _AddFilesState) -> bool:
    return bool(
        state.passphrase
        or state.shard_fallback_files
        or state.shard_payloads_file
        or state.shard_scan
        or state.shard_frames
    )


def _source_summary(state: _AddFilesState) -> str:
    if state.source_kind == "folder" and state.root_dir:
        return f"Generated backup folder: {state.root_dir}"
    if state.source_kind == "scan" and state.root_dir and state.scan_paths:
        freshness = (
            "trusted head provided"
            if state.expected_head_doc_hash
            else "latest scans acknowledged"
            if state.allow_stale_head
            else "freshness not confirmed"
        )
        return f"{len(state.scan_paths)} scan path(s), output: {state.root_dir}, {freshness}"
    return "Choose scanned documents or a generated backup folder."


def _unlock_summary(state: _AddFilesState) -> str:
    if state.passphrase:
        return "Passphrase provided."
    shard_count = (
        len(state.shard_fallback_files)
        + len(state.shard_payloads_file)
        + len(state.shard_scan)
        + len(state.shard_frames)
    )
    if shard_count:
        return f"Shard unlock material provided ({shard_count} item(s))."
    return "Choose the passphrase or printed shard documents for the existing backup."


def _files_summary(paths: Sequence[str]) -> str:
    if not paths:
        return "Choose at least one file or folder."
    return f"{len(paths)} selected path(s)."


def _policy_summary(policy: _AddFilesOutputPolicy | None) -> str:
    if policy is None:
        return "Choose how this update can be recovered later."
    if policy.unlock_policy == "reuse-root":
        return "Reuse the root backup shard documents."
    if policy.shard_count == 0:
        return "Print the passphrase in the recovery document."
    return f"Create update shard documents ({policy.shard_threshold} of {policy.shard_count})."


def _prompt_source(state: _AddFilesState) -> None:
    with wizard_substep("Choose source"):
        source_kind = prompt_choice(
            "What backup are you adding files to",
            {
                "scan": "Printed or scanned backup documents",
                "folder": "Existing generated backup folder",
            },
            default=state.source_kind or "scan",
            help_text=(
                "Choose scans when printed documents are the source of truth. Choose a generated "
                "folder only when you intentionally kept the original export tree."
            ),
        )
    state.source_kind = "scan" if source_kind == "scan" else "folder"
    state.scan_paths = []
    state.expected_head_doc_hash = None
    state.allow_stale_head = False

    if state.source_kind == "folder":
        with wizard_substep("Choose backup folder"):
            state.root_dir = prompt_optional_path_with_picker(
                "Generated backup folder",
                kind="dir",
                help_text=(
                    "Choose the generated backup folder to append to. If you only have paper "
                    "documents or scans, choose scanned documents instead."
                ),
                picker_prompt="Select generated backup folder",
                picker_help_text="Open folders, then choose the backup folder.",
                picker_id="extend-source-folder",
            )
        return

    with wizard_substep("Choose output folder"):
        while True:
            root_dir = prompt_optional_path_with_picker(
                "Output folder for the new update",
                kind="dir",
                allow_new=True,
                help_text=(
                    "Choose a new or empty folder where the update documents will be written. "
                    "The scans remain the source for the existing backup."
                ),
                picker_prompt="Select output folder",
                picker_help_text="Choose an existing folder, or enter a new path manually.",
                picker_id="extend-output-folder",
            )
            if root_dir:
                state.root_dir = root_dir
                break
            console_err.print("[error]Choose an output folder for the update documents.[/error]")

    with wizard_substep("Choose scans"):
        state.scan_paths = prompt_paths_with_picker(
            "Backup document scans",
            kind="path",
            manual_help_text=(
                "Enter root and extension PDF/image scan paths, one per line. Blank line to finish."
            ),
            empty_message="Choose at least the root backup scan.",
            picker_prompt="Select backup document scans",
            picker_help_text=(
                "Open folders and add root or extension PDFs/images. Use Done when complete."
            ),
            picker_id="extend-source-scans",
        )
    with wizard_substep("Confirm latest backup state"):
        state.expected_head_doc_hash = _prompt_expected_head_doc_hash()
        state.allow_stale_head = state.expected_head_doc_hash is None and _prompt_stale_head_ack()


def _prompt_unlock(state: _AddFilesState) -> None:
    with wizard_substep("Unlock backup"):
        (
            passphrase,
            shard_fallback_files,
            shard_payloads_file,
            shard_scan,
            shard_frames,
        ) = prompt_passphrase_unlock_material(
            quiet=state.quiet,
            passphrase=state.passphrase,
            shard_fallback_files=state.shard_fallback_files,
            shard_payloads_file=state.shard_payloads_file,
            shard_scan=state.shard_scan,
            choice_prompt="How do you want to unlock this backup",
            passphrase_choice_label="I have the passphrase",
            shard_choice_label="I have printed shard documents",
            choice_help_text="Choose the unlock information for the existing backup.",
            passphrase_prompt="Passphrase",
            passphrase_help_text="Enter the passphrase for the backup you are updating.",
            allow_existing_review=True,
        )
    state.passphrase = passphrase
    state.shard_fallback_files = shard_fallback_files
    state.shard_payloads_file = shard_payloads_file
    state.shard_scan = shard_scan
    state.shard_frames = list(shard_frames)


def _prompt_files(state: _AddFilesState) -> None:
    with wizard_substep("Choose files"):
        state.selected_paths = prompt_paths_with_picker(
            "Files or folders to add",
            kind="path",
            manual_help_text=(
                "Enter one or more existing file or folder paths to include. Blank line to finish."
            ),
            empty_message="Choose at least one file or folder to add to the backup.",
            picker_prompt="Select files or folders",
            picker_help_text="Open folders and add paths. Use Done when complete.",
            picker_id="extend-inputs",
        )


def _prompt_output_policy(
    extend_defaults: ExtendDefaults | None,
) -> _AddFilesOutputPolicy:
    default_mode = _default_policy_mode(extend_defaults)
    with wizard_substep("Choose recovery policy"):
        mode = prompt_choice(
            "How should this update be recoverable later",
            {
                "extension-shards": "Create update passphrase shard documents",
                "reuse-root": "Use the root backup shard documents",
                "plaintext": "Print the passphrase in the update recovery document",
            },
            default=default_mode,
            help_text=(
                "Update shards are safest when you are not sure the root shard set is available."
            ),
        )
    if mode == "reuse-root":
        return _AddFilesOutputPolicy(
            unlock_policy="reuse-root",
            **_prompt_signing_key_policy(extend_defaults),
        )
    if mode == "plaintext":
        return _AddFilesOutputPolicy(unlock_policy="self-contained", shard_count=0)

    default_threshold = extend_defaults.shard_threshold if extend_defaults else None
    default_count = extend_defaults.shard_count if extend_defaults else None
    if default_threshold is not None and default_count is not None and default_count > 0:
        with wizard_substep("Use saved shard setup"):
            use_default = prompt_yes_no(
                f"Use saved update shard setup ({default_threshold} of {default_count})",
                default=True,
                help_text="Select no to choose a different threshold and document count.",
            )
        if use_default:
            signing_key_policy = _prompt_signing_key_policy(extend_defaults)
            return _AddFilesOutputPolicy(
                unlock_policy="self-contained",
                shard_threshold=default_threshold,
                shard_count=default_count,
                **signing_key_policy,
            )

    with wizard_substep("Shard count"):
        shard_count = prompt_int(
            "Update shard document count",
            minimum=1,
            maximum=MAX_SHARES,
            help_text=_shard_count_help(default_count),
        )
    with wizard_substep("Shard threshold"):
        shard_threshold = prompt_int(
            "Update shard threshold",
            minimum=1,
            maximum=shard_count,
            help_text=_shard_threshold_help(default_threshold, shard_count),
        )
    signing_key_policy = _prompt_signing_key_policy(extend_defaults)
    return _AddFilesOutputPolicy(
        unlock_policy="self-contained",
        shard_threshold=shard_threshold,
        shard_count=shard_count,
        **signing_key_policy,
    )


def _default_policy_mode(extend_defaults: ExtendDefaults | None) -> str:
    if extend_defaults is None:
        return "extension-shards"
    if extend_defaults.unlock_policy == "reuse-root":
        return "reuse-root"
    if extend_defaults.shard_count == 0:
        return "plaintext"
    return "extension-shards"


def _prompt_signing_key_policy(
    extend_defaults: ExtendDefaults | None,
) -> dict[str, Any]:
    default_mode = extend_defaults.signing_key_mode if extend_defaults is not None else "not-stored"
    with wizard_substep("Signing authority"):
        signing_key_mode = prompt_choice(
            "Store signing authority shards for future updates",
            {
                "not-stored": "No, do not store signing authority shards",
                "sharded": "Yes, create signing authority shard documents",
            },
            default=default_mode if default_mode == "sharded" else "not-stored",
            help_text=(
                "These shards can recover the authority needed to authorize future updates."
            ),
        )
    if signing_key_mode != "sharded":
        return {"signing_key_mode": "not-stored"}
    with wizard_substep("Signing shard count"):
        signing_key_shard_count = prompt_int(
            "Signing authority shard document count",
            minimum=1,
            maximum=MAX_SHARES,
            help_text=_shard_count_help(
                extend_defaults.signing_key_shard_count if extend_defaults else None
            ),
        )
    with wizard_substep("Signing shard threshold"):
        signing_key_shard_threshold = prompt_int(
            "Signing authority shard threshold",
            minimum=1,
            maximum=signing_key_shard_count,
            help_text=_shard_threshold_help(
                extend_defaults.signing_key_shard_threshold if extend_defaults else None,
                signing_key_shard_count,
            ),
        )
    return {
        "signing_key_mode": "sharded",
        "signing_key_shard_threshold": signing_key_shard_threshold,
        "signing_key_shard_count": signing_key_shard_count,
    }


def _prompt_expected_head_doc_hash() -> str | None:
    while True:
        value = prompt_optional(
            "Trusted latest backup head hash",
            help_text=(
                "Paste the latest trusted head hash to reject stale scan sets. Leave blank only "
                "when no trusted head marker is available."
            ),
        )
        if value is None:
            return None
        try:
            return normalize_doc_hash_hex(value, option="expected head doc_hash")
        except ValueError as exc:
            console_err.print(f"[error]{exc}[/error]")


def _prompt_stale_head_ack() -> bool:
    return prompt_yes_no(
        "These scans are the latest backup state",
        default=False,
        help_text=(
            "Only continue without a trusted head hash if you know these scans are the latest "
            "root and update documents."
        ),
    )


def _shard_count_help(default_count: int | None) -> str:
    suffix = f" Saved default: {default_count}." if default_count else ""
    return f"Choose how many printed shard documents to create (1-{MAX_SHARES}).{suffix}"


def _shard_threshold_help(default_threshold: int | None, shard_count: int) -> str:
    suffix = (
        f" Saved default: {default_threshold}."
        if default_threshold is not None and default_threshold <= shard_count
        else ""
    )
    return f"Choose how many of the {shard_count} shard documents are required.{suffix}"


def _split_existing_paths(paths: Sequence[str]) -> tuple[list[str], list[str]]:
    files: list[str] = []
    directories: list[str] = []
    for value in paths:
        path = Path(value)
        if path.is_dir():
            directories.append(value)
        else:
            files.append(value)
    return files, directories


def _build_args(state: _AddFilesState) -> ExtendArgs:
    if state.output_policy is None:
        raise RuntimeError("cannot build add-files args without output policy")
    input_files, input_dirs = _split_existing_paths(state.selected_paths)
    return ExtendArgs(
        config=state.config,
        paper=state.paper,
        design=state.design,
        root_dir=state.root_dir,
        scan=state.scan_paths or None,
        input=input_files or None,
        input_dir=input_dirs or None,
        passphrase=state.passphrase,
        shard_fallback_file=state.shard_fallback_files or None,
        shard_payloads_file=state.shard_payloads_file or None,
        shard_scan=state.shard_scan or None,
        shard_frames=state.shard_frames or None,
        unlock_policy=state.output_policy.unlock_policy,
        shard_threshold=state.output_policy.shard_threshold,
        shard_count=state.output_policy.shard_count,
        signing_key_mode=state.output_policy.signing_key_mode,
        signing_key_shard_threshold=state.output_policy.signing_key_shard_threshold,
        signing_key_shard_count=state.output_policy.signing_key_shard_count,
        expected_head_doc_hash=state.expected_head_doc_hash,
        allow_stale_head=state.allow_stale_head,
        quiet=state.quiet,
    )


def _prepare_review(args: ExtendArgs) -> PreparedExtendRun | None:
    with wizard_substep("Check update"):
        try:
            prepared = prepare_extend_run(args)
            preflight_extension_publish_target(
                prepared.inspection.root_dir,
                index=prepared.next_index,
                publish_layout="loose" if prepared.args.scan else "canonical",
                allow_missing_root=bool(prepared.args.scan),
                require_empty_root=bool(prepared.args.scan),
            )
        except ApiCommandError as exc:
            console_err.print(f"[error]{exc}[/error]")
            return None
        except ValueError as exc:
            console_err.print(f"[error]{exc}[/error]")
            return None
    return prepared


def _confirm_review(args: ExtendArgs, prepared: PreparedExtendRun) -> bool:
    rows = [
        ("Backup source", _review_source(args)),
        ("Output folder", str(args.root_dir)),
        ("Next update index", f"{prepared.next_index:02d}"),
        ("Changed files", str(len(prepared.changed_paths))),
        ("New files", str(len(prepared.new_paths))),
        ("Unchanged selected files", str(len(prepared.unchanged_paths))),
        ("Unlock method", "passphrase" if args.passphrase else "printed shard documents"),
        ("Recovery policy", _review_recovery_policy(args)),
        ("Signing authority", _review_signing_policy(args)),
    ]
    if args.expected_head_doc_hash:
        rows.append(("Expected head", args.expected_head_doc_hash))
    elif args.allow_stale_head:
        rows.append(("Freshness check", "latest scan set acknowledged"))
    console.print(panel("Review add-files update", build_review_table(rows)))
    return prompt_yes_no(
        "Add these files to the backup",
        default=True,
        help_text="Select no to return to the workspace without writing documents.",
    )


def _review_source(args: ExtendArgs) -> str:
    if args.scan:
        return f"scanned documents ({len(args.scan)} path(s))"
    return "generated backup folder"


def _review_recovery_policy(args: ExtendArgs) -> str:
    if args.unlock_policy == "reuse-root":
        return "reuse root backup shard documents"
    if args.shard_count == 0:
        return "plaintext passphrase in update recovery document"
    return f"update shards ({args.shard_threshold} of {args.shard_count})"


def _review_signing_policy(args: ExtendArgs) -> str:
    if args.signing_key_mode != "sharded":
        return "not stored"
    return (
        "signing authority shards "
        f"({args.signing_key_shard_threshold} of {args.signing_key_shard_count})"
    )


__all__ = ["prompt_add_files_workspace_args"]
