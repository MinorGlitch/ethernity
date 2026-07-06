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

"""Guided workspace for reprinting shard documents."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Literal

from ethernity.cli.bootstrap.startup import ensure_playwright_browsers
from ethernity.cli.features.mint.workflow import (
    MAX_SHARDS,
    MintInspectionState,
    inspect_mint_inputs,
    run_mint_command,
)
from ethernity.cli.shared.crypto import normalize_doc_hash_hex
from ethernity.cli.shared.recovery_prompts import (
    _is_scan_path,
    _prompt_shard_inputs,
    prompt_passphrase_unlock_material,
)
from ethernity.cli.shared.types import MintArgs
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
from ethernity.crypto.sharding import KEY_TYPE_SIGNING_SEED
from ethernity.encoding.framing import Frame

SourceKind = Literal["scan", "fallback", "payloads"]
ShardMode = Literal["fresh", "replacement"]

_SIGNING_BLOCKER_CODES = frozenset(
    {
        "SIGNING_KEY_SHARDS_REQUIRED",
        "SIGNING_KEY_SHARDS_UNDER_QUORUM",
        "SIGNING_KEY_SHARDS_INVALID",
        "SIGNING_KEY_REPLACEMENT_NOT_READY",
    }
)
_PASSPHRASE_BLOCKER_CODES = frozenset({"PASSPHRASE_REPLACEMENT_NOT_READY"})
_SOURCE_BLOCKER_CODES = frozenset({"AUTH_REQUIRED", "RECOVERY_HEAD_UNTRUSTED"})


@dataclass(frozen=True)
class _ShardOutputPlan:
    enabled: bool
    mode: ShardMode = "fresh"
    threshold: int | None = None
    count: int | None = None
    replacement_count: int | None = None


@dataclass(frozen=True)
class _MintOutputPlan:
    passphrase: _ShardOutputPlan
    signing_key: _ShardOutputPlan


@dataclass
class _ReprintShardsState:
    config: str | None
    paper: str | None
    design: str | None
    quiet: bool
    source_kind: SourceKind | None = None
    fallback_file: str | None = None
    payloads_file: str | None = None
    scan_paths: list[str] = field(default_factory=list)
    auth_fallback_file: str | None = None
    auth_payloads_file: str | None = None
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False
    passphrase: str | None = None
    shard_fallback_files: list[str] = field(default_factory=list)
    shard_payloads_file: list[str] = field(default_factory=list)
    shard_scan: list[str] = field(default_factory=list)
    shard_frames: list[Frame] = field(default_factory=list)
    signing_key_shard_fallback_files: list[str] = field(default_factory=list)
    signing_key_shard_payloads_file: list[str] = field(default_factory=list)
    signing_key_shard_scan: list[str] = field(default_factory=list)
    signing_key_shard_frames: list[Frame] = field(default_factory=list)
    output_plan: _MintOutputPlan | None = None
    output_dir: str | None = None
    last_blocking_issues: tuple[dict[str, object], ...] = ()


def run_reprint_shards_workspace(args: MintArgs, *, debug: bool = False) -> int:
    """Run the reprint-shards workspace or execute directly when non-interactive."""

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        ensure_playwright_browsers(quiet=args.quiet)
        return run_mint_command(args, debug=debug)

    state = _initial_state(args)
    with ui_screen_mode(quiet=state.quiet):
        if not state.quiet:
            console.print("[title]Reprint shard documents[/title]")
        with wizard_flow(name="Reprint shards", total_steps=1, quiet=state.quiet):
            with wizard_stage("Reprint shard documents"):
                while True:
                    sections = _workspace_sections(state)
                    print_workspace("Reprint shard documents", sections, quiet=state.quiet)
                    action = prompt_workspace_action(
                        "Choose next step",
                        sections,
                        proceed_label="Review and reprint shards",
                        help_text=(
                            "Fill the required sections, then review the shard document plan "
                            "before anything is written."
                        ),
                    )
                    if action == "cancel":
                        console.print("Reprint shards cancelled.")
                        return 1
                    if action == "source":
                        _prompt_source(state)
                        continue
                    if action == "unlock":
                        _prompt_unlock(state)
                        continue
                    if action == "authority":
                        _prompt_signing_authority(state)
                        continue
                    if action == "shards":
                        state.output_plan = _prompt_output_plan(state)
                        continue
                    if action == "output":
                        _prompt_output(state)
                        continue
                    if action != "review":
                        continue

                    final_args = _review_args(state, debug=debug)
                    if final_args is not None:
                        ensure_playwright_browsers(quiet=state.quiet)
                        return run_mint_command(final_args, debug=debug)


def _initial_state(args: MintArgs) -> _ReprintShardsState:
    state = _ReprintShardsState(
        config=args.config,
        paper=args.paper,
        design=args.design,
        quiet=args.quiet,
        fallback_file=args.fallback_file,
        payloads_file=args.payloads_file,
        scan_paths=list(args.scan or []),
        auth_fallback_file=args.auth_fallback_file,
        auth_payloads_file=args.auth_payloads_file,
        expected_head_doc_hash=args.expected_head_doc_hash,
        allow_stale_head=args.allow_stale_head,
        passphrase=args.passphrase,
        shard_fallback_files=list(args.shard_fallback_file or []),
        shard_payloads_file=list(args.shard_payloads_file or []),
        shard_scan=list(args.shard_scan or []),
        shard_frames=list(args.shard_frames or []),
        signing_key_shard_fallback_files=list(args.signing_key_shard_fallback_file or []),
        signing_key_shard_payloads_file=list(args.signing_key_shard_payloads_file or []),
        signing_key_shard_scan=list(args.signing_key_shard_scan or []),
        signing_key_shard_frames=list(args.signing_key_shard_frames or []),
        output_dir=args.output_dir,
    )
    if args.scan:
        state.source_kind = "scan"
    elif args.fallback_file:
        state.source_kind = "fallback"
    elif args.payloads_file:
        state.source_kind = "payloads"
    if _has_output_plan(args):
        state.output_plan = _output_plan_from_args(args)
    return state


def _workspace_sections(state: _ReprintShardsState) -> list[WorkspaceSection]:
    source_status: WorkspaceStatus = "ready" if _source_ready(state) else "missing"
    source_issue = _first_issue(state.last_blocking_issues, _SOURCE_BLOCKER_CODES)
    source_summary = _source_summary(state)
    if source_issue is not None:
        source_status = "missing"
        source_summary = str(source_issue.get("message") or source_summary)
    if (
        source_issue is None
        and state.source_kind == "scan"
        and state.scan_paths
        and state.allow_stale_head
        and state.expected_head_doc_hash is None
    ):
        source_status = "warning"
    unlock_status: WorkspaceStatus = "ready" if _unlock_ready(state) else "missing"
    if _first_issue(state.last_blocking_issues, _PASSPHRASE_BLOCKER_CODES) is not None:
        unlock_status = "missing"
    signing_status, signing_summary = _signing_authority_section(state)
    return [
        WorkspaceSection(
            key="source",
            title="Backup source",
            status=source_status,
            summary=source_summary,
            action_label="Choose backup source",
        ),
        WorkspaceSection(
            key="unlock",
            title="Unlock",
            status=unlock_status,
            summary=_unlock_summary(state),
            action_label="Choose unlock method",
        ),
        WorkspaceSection(
            key="authority",
            title="Signing authority",
            status=signing_status,
            summary=signing_summary,
            action_label="Choose signing authority shards",
        ),
        WorkspaceSection(
            key="shards",
            title="Shard output",
            status="ready" if state.output_plan is not None else "missing",
            summary=_output_plan_summary(state.output_plan),
            action_label="Choose shard documents",
        ),
        WorkspaceSection(
            key="output",
            title="Output folder",
            status="ready",
            summary=_output_summary(state),
            action_label="Choose output folder",
        ),
    ]


def _source_ready(state: _ReprintShardsState) -> bool:
    if state.source_kind == "scan":
        return bool(state.scan_paths and (state.expected_head_doc_hash or state.allow_stale_head))
    if state.source_kind == "fallback":
        return bool(state.fallback_file)
    if state.source_kind == "payloads":
        return bool(state.payloads_file)
    return False


def _unlock_ready(state: _ReprintShardsState) -> bool:
    return bool(
        state.passphrase
        or state.shard_fallback_files
        or state.shard_payloads_file
        or state.shard_scan
        or state.shard_frames
    )


def _signing_authority_section(state: _ReprintShardsState) -> tuple[WorkspaceStatus, str]:
    issue = _first_issue(state.last_blocking_issues, _SIGNING_BLOCKER_CODES)
    if issue is not None:
        return "missing", str(issue.get("message") or "Signing authority shards are required.")
    if _has_signing_key_shard_inputs(state):
        return "ready", _signing_authority_summary(state)
    return "ready", "Only needed for sealed backups; checked during review."


def _source_summary(state: _ReprintShardsState) -> str:
    if state.source_kind == "scan" and state.scan_paths:
        freshness = (
            "trusted head provided"
            if state.expected_head_doc_hash
            else "latest scans acknowledged"
            if state.allow_stale_head
            else "confirm the latest chain state"
        )
        return f"{len(state.scan_paths)} scan path(s), {freshness}."
    if state.source_kind == "fallback" and state.fallback_file:
        return f"Recovery text: {state.fallback_file}"
    if state.source_kind == "payloads" and state.payloads_file:
        return f"QR text lines: {state.payloads_file}"
    return "Choose scanned backup documents, recovery text, or QR text lines."


def _unlock_summary(state: _ReprintShardsState) -> str:
    if state.passphrase:
        return "Passphrase provided."
    shard_count = (
        len(state.shard_fallback_files)
        + len(state.shard_payloads_file)
        + len(state.shard_scan)
        + len(state.shard_frames)
    )
    if shard_count:
        return f"Passphrase shard material provided ({shard_count} item(s))."
    issue = _first_issue(state.last_blocking_issues, _PASSPHRASE_BLOCKER_CODES)
    if issue is not None:
        return str(issue.get("message") or "Passphrase shard inputs need attention.")
    return "Choose the passphrase or printed passphrase shard documents."


def _signing_authority_summary(state: _ReprintShardsState) -> str:
    count = (
        len(state.signing_key_shard_fallback_files)
        + len(state.signing_key_shard_payloads_file)
        + len(state.signing_key_shard_scan)
        + len(state.signing_key_shard_frames)
    )
    if count:
        return f"Signing authority shard material provided ({count} item(s))."
    return "Only needed for sealed backups; checked during review."


def _output_plan_summary(plan: _MintOutputPlan | None) -> str:
    if plan is None:
        return "Choose which shard documents to create."
    parts: list[str] = []
    if plan.passphrase.enabled:
        parts.append(f"passphrase: {_shard_plan_summary(plan.passphrase)}")
    if plan.signing_key.enabled:
        parts.append(f"signing authority: {_shard_plan_summary(plan.signing_key)}")
    return "; ".join(parts)


def _shard_plan_summary(plan: _ShardOutputPlan) -> str:
    if plan.mode == "replacement":
        return f"{plan.replacement_count} compatible replacement(s)"
    return f"fresh set ({plan.threshold} of {plan.count})"


def _output_summary(state: _ReprintShardsState) -> str:
    if state.output_dir:
        return state.output_dir
    return "Default: mint-<backup-id>."


def _prompt_source(state: _ReprintShardsState) -> None:
    with wizard_substep("Choose backup source"):
        source_kind = prompt_choice(
            "What backup should these shard documents belong to",
            {
                "scan": "Printed or scanned backup documents",
                "fallback": "Recovery text file",
                "payloads": "QR text line file",
            },
            default=state.source_kind or "scan",
            help_text=(
                "Choose scans when printed documents are the source of truth. Use text files "
                "when you exported or copied recovery payloads."
            ),
        )
    if source_kind == "scan":
        state.source_kind = "scan"
    elif source_kind == "fallback":
        state.source_kind = "fallback"
    else:
        state.source_kind = "payloads"
    state.fallback_file = None
    state.payloads_file = None
    state.scan_paths = []
    state.expected_head_doc_hash = None
    state.allow_stale_head = False
    state.last_blocking_issues = ()

    if state.source_kind == "scan":
        with wizard_substep("Choose scans"):
            state.scan_paths = prompt_paths_with_picker(
                "Backup document scans",
                kind="path",
                manual_help_text=(
                    "Enter root and extension PDF/image scan paths, one per line. "
                    "Blank line to finish."
                ),
                empty_message="Choose at least the root backup scan.",
                picker_prompt="Select backup document scans",
                picker_help_text=(
                    "Open folders and add root or extension PDFs/images. Use Done when complete."
                ),
                picker_id="mint-source-scans",
            )
        with wizard_substep("Confirm latest backup state"):
            state.expected_head_doc_hash = _prompt_expected_head_doc_hash()
            state.allow_stale_head = (
                state.expected_head_doc_hash is None and _prompt_stale_head_ack()
            )
    elif state.source_kind == "fallback":
        state.fallback_file = _prompt_required_file(
            "Backup recovery text file",
            picker_prompt="Select backup recovery text",
            picker_id="mint-source-fallback",
        )
    else:
        state.payloads_file = _prompt_required_file(
            "Backup QR text line file",
            picker_prompt="Select backup QR text lines",
            picker_id="mint-source-payloads",
        )
    _prompt_extra_auth_inputs(state)


def _prompt_unlock(state: _ReprintShardsState) -> None:
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
            collect_all_shards=True,
            choice_prompt="How do you want to unlock this backup",
            passphrase_choice_label="I have the passphrase",
            shard_choice_label="I have printed passphrase shard documents",
            choice_help_text=(
                "Use passphrase shards when you want compatible replacements for missing "
                "passphrase shard documents."
            ),
            passphrase_prompt="Passphrase",
            passphrase_help_text="Enter the passphrase for the backup.",
            allow_existing_review=True,
        )
    state.passphrase = passphrase
    state.shard_fallback_files = shard_fallback_files
    state.shard_payloads_file = shard_payloads_file
    state.shard_scan = shard_scan
    state.shard_frames = list(shard_frames)
    state.last_blocking_issues = ()


def _prompt_signing_authority(state: _ReprintShardsState) -> None:
    with wizard_substep("Signing authority"):
        choice = prompt_choice(
            "Signing authority shard inputs",
            {
                "shards": "Choose signing authority shard documents",
                "skip": "Skip for now",
                "clear": "Clear saved signing authority inputs",
            },
            default="shards",
            help_text=(
                "Sealed backups need signing authority shards to authorize new shard documents. "
                "Unsealed backups can use the embedded signing seed."
            ),
        )
    if choice != "shards":
        if choice == "clear":
            state.signing_key_shard_fallback_files = []
            state.signing_key_shard_payloads_file = []
            state.signing_key_shard_scan = []
            state.signing_key_shard_frames = []
        state.last_blocking_issues = ()
        return

    fallback_files, payload_inputs, frames = _prompt_shard_inputs(
        quiet=state.quiet,
        key_type=KEY_TYPE_SIGNING_SEED,
        label="Signing authority shard documents",
        stop_at_quorum=False,
    )
    state.signing_key_shard_fallback_files = fallback_files
    state.signing_key_shard_payloads_file = [
        path for path in payload_inputs if not _is_scan_path(path)
    ]
    state.signing_key_shard_scan = [path for path in payload_inputs if _is_scan_path(path)]
    state.signing_key_shard_frames = list(frames)
    state.last_blocking_issues = ()


def _prompt_output_plan(state: _ReprintShardsState) -> _MintOutputPlan:
    with wizard_substep("Choose shard documents"):
        scope = prompt_choice(
            "Which shard documents do you want to reprint",
            {
                "both": "Passphrase and signing authority shards",
                "passphrase": "Passphrase shards only",
                "signing": "Signing authority shards only",
            },
            default="both",
            help_text=(
                "Passphrase shards unlock the backup. Signing authority shards authorize future "
                "updates and shard reprints."
            ),
        )
    passphrase_plan = _ShardOutputPlan(enabled=False)
    signing_plan = _ShardOutputPlan(enabled=False)
    if scope in {"both", "passphrase"}:
        passphrase_plan = _prompt_single_shard_plan(
            label="Passphrase",
            has_existing_shards=_has_passphrase_shard_inputs(state),
        )
    if scope in {"both", "signing"}:
        signing_plan = _prompt_signing_shard_plan(state, passphrase_plan=passphrase_plan)
    return _MintOutputPlan(passphrase=passphrase_plan, signing_key=signing_plan)


def _prompt_single_shard_plan(
    *,
    label: str,
    has_existing_shards: bool,
) -> _ShardOutputPlan:
    choices = {"fresh": f"Create a full fresh {label.lower()} shard set"}
    if has_existing_shards:
        choices["replacement"] = f"Create compatible replacement {label.lower()} shards"
    with wizard_substep(f"{label} shard mode"):
        mode = prompt_choice(
            f"{label} shard mode",
            choices,
            default="fresh",
            help_text=(
                "Fresh sets replace the old shard set. Compatible replacements fill missing "
                "slots in an existing shard set."
            ),
        )
    if mode == "replacement":
        with wizard_substep(f"{label} replacements"):
            replacement_count = prompt_int(
                f"{label} replacement document count",
                minimum=1,
                maximum=MAX_SHARDS,
                help_text="Choose how many compatible replacement shard documents to create.",
            )
        return _ShardOutputPlan(
            enabled=True,
            mode="replacement",
            replacement_count=replacement_count,
        )
    threshold, count = _prompt_quorum(label)
    return _ShardOutputPlan(enabled=True, mode="fresh", threshold=threshold, count=count)


def _prompt_signing_shard_plan(
    state: _ReprintShardsState,
    *,
    passphrase_plan: _ShardOutputPlan,
) -> _ShardOutputPlan:
    has_existing_shards = _has_signing_key_shard_inputs(state)
    choices = {"fresh": "Create a full fresh signing authority shard set"}
    if has_existing_shards:
        choices["replacement"] = "Create compatible replacement signing authority shards"
    with wizard_substep("Signing authority shard mode"):
        mode = prompt_choice(
            "Signing authority shard mode",
            choices,
            default="fresh",
            help_text=(
                "Compatible replacements require existing signing authority shards from the "
                "current set."
            ),
        )
    if mode == "replacement":
        with wizard_substep("Signing authority replacements"):
            replacement_count = prompt_int(
                "Signing authority replacement document count",
                minimum=1,
                maximum=MAX_SHARDS,
                help_text="Choose how many compatible replacement shard documents to create.",
            )
        return _ShardOutputPlan(
            enabled=True,
            mode="replacement",
            replacement_count=replacement_count,
        )
    if (
        passphrase_plan.enabled
        and passphrase_plan.mode == "fresh"
        and passphrase_plan.threshold is not None
        and passphrase_plan.count is not None
    ):
        with wizard_substep("Signing authority quorum"):
            use_same = prompt_yes_no(
                (
                    "Use same quorum as passphrase shards "
                    f"({passphrase_plan.threshold} of {passphrase_plan.count})"
                ),
                default=True,
                help_text="Select no to choose a separate signing authority shard quorum.",
            )
        if use_same:
            return _ShardOutputPlan(
                enabled=True,
                mode="fresh",
                threshold=passphrase_plan.threshold,
                count=passphrase_plan.count,
            )
    threshold, count = _prompt_quorum("Signing authority")
    return _ShardOutputPlan(enabled=True, mode="fresh", threshold=threshold, count=count)


def _prompt_quorum(label: str) -> tuple[int, int]:
    with wizard_substep(f"{label} shard count"):
        count = prompt_int(
            f"{label} shard document count",
            minimum=1,
            maximum=MAX_SHARDS,
            help_text=f"Choose how many printed {label.lower()} shard documents to create.",
        )
    with wizard_substep(f"{label} shard threshold"):
        threshold = prompt_int(
            f"{label} shard threshold",
            minimum=1,
            maximum=count,
            help_text=f"Choose how many of the {count} shard documents are required.",
        )
    return threshold, count


def _prompt_output(state: _ReprintShardsState) -> None:
    with wizard_substep("Choose output folder"):
        state.output_dir = prompt_optional_path_with_picker(
            "Output folder",
            kind="dir",
            allow_new=True,
            help_text=(
                "Choose a new output folder, or choose an existing parent folder to create "
                "mint-<backup-id> inside it. Leave blank for the default."
            ),
            picker_prompt="Select output folder",
            picker_help_text="Choose an existing folder, or enter a new path manually.",
            picker_id="mint-output",
        )


def _prompt_required_file(label: str, *, picker_prompt: str, picker_id: str) -> str:
    while True:
        value = prompt_optional_path_with_picker(
            label,
            kind="file",
            help_text="Choose the file, or switch to manual entry.",
            picker_prompt=picker_prompt,
            picker_help_text="Open folders, then choose the file.",
            picker_id=picker_id,
        )
        if value:
            return value
        console_err.print(f"[error]Choose {label.lower()}.[/error]")


def _prompt_extra_auth_inputs(state: _ReprintShardsState) -> None:
    with wizard_substep("Extra verification"):
        add_auth = prompt_yes_no(
            "Add extra verification data",
            default=bool(state.auth_fallback_file or state.auth_payloads_file),
            help_text=(
                "Use this only when the selected backup source does not already include "
                "verification data."
            ),
        )
    if not add_auth:
        state.auth_fallback_file = None
        state.auth_payloads_file = None
        return
    with wizard_substep("Verification format"):
        kind = prompt_choice(
            "How is the extra verification data stored",
            {
                "fallback": "Recovery text file",
                "payloads": "QR text line file",
            },
            default="payloads",
            help_text="Choose the file format for the verification data.",
        )
    if kind == "fallback":
        state.auth_fallback_file = _prompt_required_file(
            "Verification recovery text file",
            picker_prompt="Select verification recovery text",
            picker_id="mint-auth-fallback",
        )
        state.auth_payloads_file = None
        return
    state.auth_fallback_file = None
    state.auth_payloads_file = _prompt_required_file(
        "Verification QR text line file",
        picker_prompt="Select verification QR text lines",
        picker_id="mint-auth-payloads",
    )


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


def _review_args(state: _ReprintShardsState, *, debug: bool) -> MintArgs | None:
    args = _build_args(state)
    try:
        inspection = inspect_mint_inputs(args, debug=debug)
    except Exception as exc:
        state.last_blocking_issues = (
            {"code": "MINT_REVIEW_FAILED", "message": str(exc), "details": {}},
        )
        _print_blocking_issues(state.last_blocking_issues)
        return None

    blockers = _review_blockers(args, inspection)
    if blockers:
        state.last_blocking_issues = tuple(blockers)
        _print_blocking_issues(state.last_blocking_issues)
        return None
    state.last_blocking_issues = ()
    if _confirm_review(args, inspection):
        return args
    return None


def _review_blockers(args: MintArgs, inspection: MintInspectionState) -> list[dict[str, object]]:
    blockers = [dict(issue) for issue in inspection.blocking_issues]
    capabilities = inspection.mint_capabilities
    if args.mint_passphrase_shards and not capabilities.get("can_mint_passphrase_shards", False):
        _append_blocker_once(
            blockers,
            {
                "code": "PASSPHRASE_SHARDS_NOT_READY",
                "message": "passphrase shard documents are not ready to reprint",
                "details": {},
            },
        )
    if args.mint_signing_key_shards and not capabilities.get("can_mint_signing_key_shards", False):
        _append_blocker_once(
            blockers,
            {
                "code": "SIGNING_KEY_SHARDS_NOT_READY",
                "message": "signing authority shard documents are not ready to reprint",
                "details": {},
            },
        )
    return blockers


def _append_blocker_once(
    blockers: list[dict[str, object]],
    blocker: dict[str, object],
) -> None:
    code = blocker.get("code")
    if any(existing.get("code") == code for existing in blockers):
        return
    blockers.append(blocker)


def _print_blocking_issues(issues: tuple[dict[str, object], ...]) -> None:
    if not issues:
        return
    lines = [f"- {issue.get('message', 'Review needs attention.')}" for issue in issues]
    console_err.print(panel("Review needs attention", "\n".join(lines), style="warning"))


def _confirm_review(args: MintArgs, inspection: MintInspectionState) -> bool:
    rows = _review_rows(args, inspection)
    if not args.quiet:
        console.print(panel("Shard document plan", build_review_table(rows)))
    return prompt_yes_no(
        "Reprint these shard documents",
        default=True,
        help_text="Select no to go back without writing anything.",
    )


def _review_rows(args: MintArgs, inspection: MintInspectionState) -> list[tuple[str, str]]:
    rows = [
        ("Backup source", _review_source(args)),
        ("Authenticated backup", inspection.recovery.doc_id.hex()),
        ("Verification", "authenticated" if inspection.recovery.auth_payload else "missing"),
        ("Unlock", _review_unlock(args)),
        ("Signing authority", inspection.signing_key_source or _review_signing_authority(args)),
        ("Passphrase shards", _review_shard_output(args, passphrase=True)),
        ("Signing authority shards", _review_shard_output(args, passphrase=False)),
        ("Output folder", args.output_dir or "mint-<backup-id>"),
    ]
    if inspection.selected_extension_index is not None:
        rows.append(("Extension index", str(inspection.selected_extension_index)))
    if inspection.selected_extension_doc_hash is not None:
        rows.append(("Extension doc hash", inspection.selected_extension_doc_hash))
    source_summary = inspection.source_summary or {}
    file_count = source_summary.get("file_count")
    if file_count is not None:
        rows.append(("Files in backup", str(file_count)))
    return rows


def _review_source(args: MintArgs) -> str:
    if args.scan:
        return f"{len(args.scan)} scan path(s)"
    if args.fallback_file:
        return f"Recovery text: {args.fallback_file}"
    if args.payloads_file:
        return f"QR text lines: {args.payloads_file}"
    return args.input_label or "Backup recovery input"


def _review_unlock(args: MintArgs) -> str:
    if args.passphrase:
        return "passphrase"
    shard_count = (
        len(args.shard_fallback_file or [])
        + len(args.shard_payloads_file or [])
        + len(args.shard_scan or [])
        + len(args.shard_frames or [])
    )
    return f"passphrase shard material ({shard_count} item(s))"


def _review_signing_authority(args: MintArgs) -> str:
    count = (
        len(args.signing_key_shard_fallback_file or [])
        + len(args.signing_key_shard_payloads_file or [])
        + len(args.signing_key_shard_scan or [])
        + len(args.signing_key_shard_frames or [])
    )
    if count:
        return f"signing authority shard material ({count} item(s))"
    return "embedded signing seed if available"


def _review_shard_output(args: MintArgs, *, passphrase: bool) -> str:
    if passphrase:
        if not args.mint_passphrase_shards:
            return "off"
        if args.passphrase_replacement_count is not None:
            return f"{args.passphrase_replacement_count} compatible replacement(s)"
        return f"fresh set ({args.shard_threshold} of {args.shard_count})"
    if not args.mint_signing_key_shards:
        return "off"
    if args.signing_key_replacement_count is not None:
        return f"{args.signing_key_replacement_count} compatible replacement(s)"
    threshold = args.signing_key_shard_threshold or args.shard_threshold
    count = args.signing_key_shard_count or args.shard_count
    return f"fresh set ({threshold} of {count})"


def _build_args(state: _ReprintShardsState) -> MintArgs:
    if state.output_plan is None:
        raise RuntimeError("cannot build mint args without a shard output plan")
    passphrase_plan = state.output_plan.passphrase
    signing_plan = state.output_plan.signing_key
    return MintArgs(
        config=state.config,
        paper=state.paper,
        design=state.design,
        fallback_file=state.fallback_file,
        payloads_file=state.payloads_file,
        scan=state.scan_paths or None,
        passphrase=state.passphrase,
        shard_fallback_file=state.shard_fallback_files or None,
        shard_payloads_file=state.shard_payloads_file or None,
        shard_scan=state.shard_scan or None,
        shard_frames=state.shard_frames or None,
        auth_fallback_file=state.auth_fallback_file,
        auth_payloads_file=state.auth_payloads_file,
        expected_head_doc_hash=state.expected_head_doc_hash,
        allow_stale_head=state.allow_stale_head,
        signing_key_shard_fallback_file=state.signing_key_shard_fallback_files or None,
        signing_key_shard_payloads_file=state.signing_key_shard_payloads_file or None,
        signing_key_shard_scan=state.signing_key_shard_scan or None,
        signing_key_shard_frames=state.signing_key_shard_frames or None,
        output_dir=state.output_dir,
        output_dir_existing_parent=True,
        shard_threshold=passphrase_plan.threshold,
        shard_count=passphrase_plan.count,
        signing_key_shard_threshold=signing_plan.threshold,
        signing_key_shard_count=signing_plan.count,
        passphrase_replacement_count=passphrase_plan.replacement_count,
        signing_key_replacement_count=signing_plan.replacement_count,
        mint_passphrase_shards=passphrase_plan.enabled,
        mint_signing_key_shards=signing_plan.enabled,
        quiet=state.quiet,
    )


def _has_output_plan(args: MintArgs) -> bool:
    return bool(
        args.passphrase_replacement_count is not None
        or args.signing_key_replacement_count is not None
        or args.shard_threshold is not None
        or args.shard_count is not None
        or args.signing_key_shard_threshold is not None
        or args.signing_key_shard_count is not None
        or not args.mint_passphrase_shards
        or not args.mint_signing_key_shards
    )


def _output_plan_from_args(args: MintArgs) -> _MintOutputPlan:
    passphrase = _ShardOutputPlan(
        enabled=args.mint_passphrase_shards,
        mode="replacement" if args.passphrase_replacement_count is not None else "fresh",
        threshold=args.shard_threshold,
        count=args.shard_count,
        replacement_count=args.passphrase_replacement_count,
    )
    signing_key = _ShardOutputPlan(
        enabled=args.mint_signing_key_shards,
        mode="replacement" if args.signing_key_replacement_count is not None else "fresh",
        threshold=args.signing_key_shard_threshold,
        count=args.signing_key_shard_count,
        replacement_count=args.signing_key_replacement_count,
    )
    return _MintOutputPlan(passphrase=passphrase, signing_key=signing_key)


def _has_passphrase_shard_inputs(state: _ReprintShardsState) -> bool:
    return bool(
        state.shard_fallback_files
        or state.shard_payloads_file
        or state.shard_scan
        or state.shard_frames
    )


def _has_signing_key_shard_inputs(state: _ReprintShardsState) -> bool:
    return bool(
        state.signing_key_shard_fallback_files
        or state.signing_key_shard_payloads_file
        or state.signing_key_shard_scan
        or state.signing_key_shard_frames
    )


def _first_issue(
    issues: tuple[dict[str, object], ...],
    codes: frozenset[str],
) -> dict[str, object] | None:
    for issue in issues:
        code = issue.get("code")
        if isinstance(code, str) and code in codes:
            return issue
    return None
