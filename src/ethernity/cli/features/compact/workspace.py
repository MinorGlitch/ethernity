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

"""Guided workspace for rebuilding a backup set."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ethernity.cli.features.compact.service import validate_compact_source_selection
from ethernity.cli.shared.crypto import normalize_doc_hash_hex
from ethernity.cli.shared.recovery_prompts import prompt_passphrase_unlock_material
from ethernity.cli.shared.types import CompactArgs
from ethernity.cli.shared.ui_api import (
    WorkspaceSection,
    WorkspaceStatus,
    build_review_table,
    console,
    console_err,
    panel,
    print_workspace,
    prompt_choice,
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
from ethernity.encoding.framing import Frame

SourceKind = Literal["scan", "folder"]


@dataclass
class _RebuildState:
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
    output_dir: str | None = None


def prompt_rebuild_workspace_args(
    *,
    config: str | None,
    paper: str | None,
    design: str | None,
    quiet: bool,
) -> CompactArgs | None:
    """Prompt for a compact run using a guided task workspace."""

    state = _RebuildState(config=config, paper=paper, design=design, quiet=quiet)
    with ui_screen_mode(quiet=quiet):
        with wizard_flow(name="Rebuild", total_steps=1, quiet=quiet):
            with wizard_stage("Rebuild a backup set"):
                while True:
                    sections = _workspace_sections(state)
                    print_workspace("Rebuild a backup set", sections, quiet=quiet)
                    action = prompt_workspace_action(
                        "Choose next step",
                        sections,
                        proceed_label="Review and rebuild",
                        help_text=(
                            "Fill the required sections, then review the rebuilt backup before "
                            "anything is written."
                        ),
                    )
                    if action == "cancel":
                        console.print("Rebuild cancelled.")
                        return None
                    if action == "source":
                        _prompt_source(state)
                        continue
                    if action == "unlock":
                        _prompt_unlock(state)
                        continue
                    if action == "output":
                        _prompt_output(state)
                        continue
                    if action != "review":
                        continue

                    args = _build_args(state)
                    if _confirm_review(args):
                        return args


def _workspace_sections(state: _RebuildState) -> list[WorkspaceSection]:
    source_status: WorkspaceStatus = "ready" if _source_ready(state) else "missing"
    if (
        state.source_kind == "scan"
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
            key="output",
            title="Output folder",
            status="ready" if state.output_dir else "missing",
            summary=_output_summary(state),
            action_label="Choose output folder",
        ),
    ]


def _source_ready(state: _RebuildState) -> bool:
    if state.source_kind == "folder":
        return bool(state.root_dir)
    if state.source_kind == "scan":
        return bool(state.scan_paths and (state.expected_head_doc_hash or state.allow_stale_head))
    return False


def _unlock_ready(state: _RebuildState) -> bool:
    return bool(
        state.passphrase
        or state.shard_fallback_files
        or state.shard_payloads_file
        or state.shard_scan
        or state.shard_frames
    )


def _source_summary(state: _RebuildState) -> str:
    if state.source_kind == "folder" and state.root_dir:
        return f"Generated backup folder: {state.root_dir}"
    if state.source_kind == "scan" and state.scan_paths:
        freshness = (
            "trusted head provided"
            if state.expected_head_doc_hash
            else "latest scans acknowledged"
            if state.allow_stale_head
            else "freshness not confirmed"
        )
        return f"{len(state.scan_paths)} scan path(s), {freshness}"
    return "Choose scanned documents or a generated backup folder."


def _unlock_summary(state: _RebuildState) -> str:
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
    return "Choose the passphrase or printed shard documents for the backup set."


def _output_summary(state: _RebuildState) -> str:
    if state.output_dir:
        return state.output_dir
    return "Choose a new or empty folder for the rebuilt backup set."


def _prompt_source(state: _RebuildState) -> None:
    with wizard_substep("Choose source"):
        source_kind = prompt_choice(
            "What backup set are you rebuilding from",
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
    state.root_dir = None
    state.scan_paths = []
    state.expected_head_doc_hash = None
    state.allow_stale_head = False

    if state.source_kind == "folder":
        with wizard_substep("Choose backup folder"):
            state.root_dir = prompt_optional_path_with_picker(
                "Generated backup folder",
                kind="dir",
                help_text=(
                    "Choose this only if you kept the generated backup export tree. If you only "
                    "have paper documents or scans, choose scanned documents instead."
                ),
                picker_prompt="Select generated backup folder",
                picker_help_text="Open folders, then choose the backup folder.",
                picker_id="compact-source-folder",
            )
        return

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
            picker_id="compact-source-scans",
        )
    with wizard_substep("Confirm latest backup state"):
        state.expected_head_doc_hash = _prompt_expected_head_doc_hash()
        state.allow_stale_head = state.expected_head_doc_hash is None and _prompt_stale_head_ack()


def _prompt_unlock(state: _RebuildState) -> None:
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
            choice_help_text="Choose the unlock information for the backup set.",
            passphrase_prompt="Passphrase",
            passphrase_help_text="Enter the passphrase for the backup set you are rebuilding.",
            allow_existing_review=True,
        )
    state.passphrase = passphrase
    state.shard_fallback_files = shard_fallback_files
    state.shard_payloads_file = shard_payloads_file
    state.shard_scan = shard_scan
    state.shard_frames = list(shard_frames)


def _prompt_output(state: _RebuildState) -> None:
    with wizard_substep("Choose output folder"):
        while True:
            output_dir = prompt_optional_path_with_picker(
                "Output folder for rebuilt backup",
                kind="dir",
                allow_new=True,
                help_text="Choose a new or empty folder where the rebuilt backup will be written.",
                picker_prompt="Select output folder",
                picker_help_text="Choose an existing folder, or enter a new path manually.",
                picker_id="compact-output-folder",
            )
            if output_dir:
                state.output_dir = output_dir
                return
            console_err.print("[error]Choose an output folder for the rebuilt backup.[/error]")


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


def _build_args(state: _RebuildState) -> CompactArgs:
    return CompactArgs(
        config=state.config,
        paper=state.paper,
        design=state.design,
        root_dir=state.root_dir,
        scan=state.scan_paths or None,
        output_dir=state.output_dir,
        passphrase=state.passphrase,
        shard_fallback_file=state.shard_fallback_files or None,
        shard_payloads_file=state.shard_payloads_file or None,
        shard_scan=state.shard_scan or None,
        shard_frames=state.shard_frames or None,
        expected_head_doc_hash=state.expected_head_doc_hash,
        allow_stale_head=state.allow_stale_head,
        quiet=state.quiet,
    )


def _confirm_review(args: CompactArgs) -> bool:
    try:
        validate_compact_source_selection(args)
    except ValueError as exc:
        console_err.print(f"[error]{exc}[/error]")
        return False

    rows = [
        ("Backup source", _review_source(args)),
        ("Output folder", str(args.output_dir)),
        ("Unlock method", "passphrase" if args.passphrase else "printed shard documents"),
    ]
    if args.expected_head_doc_hash:
        rows.append(("Expected head", args.expected_head_doc_hash))
    elif args.allow_stale_head:
        rows.append(("Freshness check", "latest scan set acknowledged"))
    console.print(panel("Review rebuilt backup", build_review_table(rows)))
    return prompt_yes_no(
        "Rebuild this backup set",
        default=True,
        help_text="Select no to return to the workspace without writing documents.",
    )


def _review_source(args: CompactArgs) -> str:
    if args.scan:
        return f"scanned documents ({len(args.scan)} path(s))"
    return "generated backup folder"


__all__ = ["prompt_rebuild_workspace_args"]
