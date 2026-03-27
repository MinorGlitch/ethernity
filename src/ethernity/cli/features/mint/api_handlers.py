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

import re
from pathlib import Path

from ethernity.cli.features.mint.workflow import execute_mint, inspect_mint_inputs
from ethernity.cli.features.recover.api_handlers import _ForwardingWarningCollector
from ethernity.cli.shared.events import (
    active_event_sink,
    emit_artifact,
    emit_phase,
    emit_progress,
    emit_result,
    event_session,
)
from ethernity.cli.shared.ndjson import SCHEMA_VERSION, emit_started
from ethernity.cli.shared.types import MintArgs, MintResult

_SHARD_LAYOUT_PATTERN = re.compile(
    r"^(?P<prefix>shard|signing-key-shard)-[0-9a-f]+-(?P<index>\d+)-of-(?P<count>\d+)\.pdf$"
)


def _artifact_details(path: str) -> dict[str, object]:
    path_obj = Path(path)
    details: dict[str, object] = {"filename": path_obj.name}
    if path_obj.exists():
        details["size"] = path_obj.stat().st_size
    return details


def _emit_mint_artifacts(result: MintResult) -> None:
    for shard_path in result.shard_paths:
        emit_artifact(kind="shard_document", path=shard_path, details=_artifact_details(shard_path))
    for shard_path in result.signing_key_shard_paths:
        emit_artifact(
            kind="signing_key_shard_document",
            path=shard_path,
            details=_artifact_details(shard_path),
        )


def _emit_layout_debug_artifacts(*, layout_debug_dir: str | None, result: MintResult) -> None:
    if layout_debug_dir is None or not layout_debug_dir.strip():
        return
    debug_dir = Path(layout_debug_dir).expanduser().resolve()
    candidates: list[Path] = []
    for shard_path in [*result.shard_paths, *result.signing_key_shard_paths]:
        match = _SHARD_LAYOUT_PATTERN.match(Path(shard_path).name)
        if match is None:
            continue
        prefix = match.group("prefix")
        index = int(match.group("index"))
        count = int(match.group("count"))
        candidates.append(debug_dir / f"{prefix}-{index:02d}-of-{count:02d}.layout.json")

    for path in candidates:
        if path.exists():
            emit_artifact(
                kind="layout_debug_json",
                path=str(path),
                details=_artifact_details(str(path)),
            )


def _mint_started_args(
    args: MintArgs,
    *,
    debug: bool,
    operation: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "config": args.config,
        "paper": args.paper,
        "design": args.design,
        "fallback_file": args.fallback_file,
        "payloads_file": args.payloads_file,
        "scan": list(args.scan or []),
        "has_passphrase": args.passphrase is not None,
        "shard_fallback_file": list(args.shard_fallback_file or []),
        "shard_payloads_file": list(args.shard_payloads_file or []),
        "shard_scan": list(args.shard_scan or []),
        "auth_fallback_file": args.auth_fallback_file,
        "auth_payloads_file": args.auth_payloads_file,
        "signing_key_shard_fallback_file": list(args.signing_key_shard_fallback_file or []),
        "signing_key_shard_payloads_file": list(args.signing_key_shard_payloads_file or []),
        "signing_key_shard_scan": list(args.signing_key_shard_scan or []),
        "shard_threshold": args.shard_threshold,
        "shard_count": args.shard_count,
        "signing_key_shard_threshold": args.signing_key_shard_threshold,
        "signing_key_shard_count": args.signing_key_shard_count,
        "passphrase_replacement_count": args.passphrase_replacement_count,
        "signing_key_replacement_count": args.signing_key_replacement_count,
        "mint_passphrase_shards": args.mint_passphrase_shards,
        "mint_signing_key_shards": args.mint_signing_key_shards,
        "quiet": args.quiet,
        "debug": debug,
    }
    if operation is not None:
        payload["operation"] = operation
    else:
        payload["layout_debug_dir"] = args.layout_debug_dir
        payload["output_dir"] = args.output_dir
    return payload


def _has_blocking_issue(
    items: tuple[dict[str, object], ...] | list[dict[str, object]],
    code: str,
) -> bool:
    return any(item.get("code") == code for item in items)


def run_mint_api_command(args: MintArgs, *, debug: bool = False) -> int:
    emit_started(
        command="mint",
        schema_version=SCHEMA_VERSION,
        args=_mint_started_args(args, debug=debug),
    )

    sink = active_event_sink()
    result = execute_mint(args, debug=debug, event_sink=sink)
    _emit_mint_artifacts(result)
    _emit_layout_debug_artifacts(layout_debug_dir=args.layout_debug_dir, result=result)
    emit_result(
        command="mint",
        doc_id=result.doc_id.hex(),
        output_dir=result.output_dir,
        artifacts={
            "shard_documents": list(result.shard_paths),
            "signing_key_shard_documents": list(result.signing_key_shard_paths),
        },
        signing_key_source=result.signing_key_source,
        notes=list(result.notes),
    )
    return 0


def run_mint_inspect_api_command(args: MintArgs, *, debug: bool = False) -> int:
    emit_started(
        command="mint",
        schema_version=SCHEMA_VERSION,
        args=_mint_started_args(args, debug=debug, operation="inspect"),
    )

    sink = _ForwardingWarningCollector(active_event_sink())
    with event_session(sink):
        emit_phase(phase="plan", label="Resolving mint inputs")
        inspection = inspect_mint_inputs(args, debug=debug)
        emit_progress(
            phase="plan",
            current=1,
            total=1,
            unit="step",
            details={
                "input_label": inspection.recovery.input_label,
                "input_detail": inspection.recovery.input_detail,
                "main_frame_count": len(inspection.recovery.main_frames),
                "auth_frame_count": len(inspection.recovery.auth_frames),
                "shard_frame_count": len(inspection.recovery.shard_frames),
                "signing_key_shard_frame_count": inspection.signing_key_frame_count,
            },
        )
        emit_result(
            command="mint",
            operation="inspect",
            doc_id=inspection.recovery.doc_id.hex(),
            auth_status=inspection.recovery.auth_status,
            input_label=inspection.recovery.input_label,
            input_detail=inspection.recovery.input_detail,
            source_summary=inspection.source_summary,
            frame_counts={
                "main": len(inspection.recovery.main_frames),
                "auth": len(inspection.recovery.auth_frames),
                "shard": len(inspection.recovery.shard_frames),
                "signing_key_shard": inspection.signing_key_frame_count,
            },
            unlock={
                "validated_passphrase_shard_count": (
                    inspection.recovery.unlock.validated_shard_count
                ),
                "required_passphrase_threshold": (
                    inspection.recovery.unlock.required_shard_threshold
                ),
                "satisfied": (
                    inspection.recovery.unlock.satisfied
                    and inspection.manifest is not None
                    and not _has_blocking_issue(list(inspection.blocking_issues), "AUTH_REQUIRED")
                ),
            },
            signing_key={
                "validated_shard_count": inspection.signing_key_validated_shard_count,
                "required_threshold": inspection.signing_key_required_threshold,
                "satisfied": inspection.signing_key_satisfied,
                "source": inspection.signing_key_source,
            },
            mint_capabilities=dict(inspection.mint_capabilities),
            blocking_issues=[dict(item) for item in inspection.blocking_issues],
            warnings=list(sink.warning_records),
        )
    return 0


__all__ = ["run_mint_api_command", "run_mint_inspect_api_command"]
