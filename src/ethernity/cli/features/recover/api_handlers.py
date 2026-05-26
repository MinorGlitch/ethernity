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

from typing import Any

from ethernity.cli.features.recover.planning import (
    inspect_from_args,
    plan_from_inspection,
)
from ethernity.cli.features.recover.service import execute_recover_plan, prepare_recover_plan
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.events import (
    EventSink,
    active_event_sink,
    emit_artifact,
    emit_phase,
    emit_progress,
    emit_result,
    event_session,
)
from ethernity.cli.shared.inspection import (
    blocking_issue_from_exception,
    inspect_result_payload,
)
from ethernity.cli.shared.ndjson import SCHEMA_VERSION, ApiCommandError, emit_started
from ethernity.cli.shared.types import RecoverArgs
from ethernity.crypto import decrypt_bytes
from ethernity.extensions.recovery import (
    recover_chain_entries,
    validate_root_manifest_authority,
)
from ethernity.formats.envelope_codec import decode_envelope
from ethernity.formats.envelope_types import EnvelopeManifest


class _ForwardingWarningCollector:
    def __init__(self, sink: EventSink | None) -> None:
        self._sink = sink
        self.warning_records: list[dict[str, Any]] = []

    def emit(self, event_type: str, **payload: Any) -> None:
        if event_type == "warning":
            self.warning_records.append(
                {
                    "code": payload.get("code"),
                    "message": payload.get("message"),
                    "details": dict(payload.get("details") or {}),
                }
            )
        if self._sink is not None:
            self._sink.emit(event_type, **payload)


def _manifest_summary_payload(manifest: EnvelopeManifest) -> dict[str, object]:
    return {
        "format_version": manifest.format_version,
        "input_origin": manifest.input_origin,
        "input_roots": list(manifest.input_roots),
        "sealed": manifest.sealed,
        "payload_codec": manifest.payload_codec,
        "payload_raw_len": manifest.payload_raw_len,
        "file_count": len(manifest.files),
    }


def _inspect_replay_blocking_issue(exc: Exception) -> dict[str, object]:
    return blocking_issue_from_exception(
        exc,
        fallback_code=api_codes.RECOVERY_HEAD_UNTRUSTED,
        fallback_details={"stage": "replay"},
    )


def _inspect_decrypt_blocking_issue(exc: Exception) -> dict[str, object]:
    return blocking_issue_from_exception(
        exc,
        fallback_code="UNLOCK_FAILED",
        fallback_details={"stage": "decrypt"},
    )


def _recover_started_args(
    args: RecoverArgs,
    *,
    debug: bool,
    operation: str | None = None,
) -> dict[str, object]:
    normalized_extension_doc_hash = (
        None if args.extension_doc_hash is None else args.extension_doc_hash.strip().lower()
    )
    normalized_expected_head_doc_hash = (
        None if args.expected_head_doc_hash is None else args.expected_head_doc_hash.strip().lower()
    )
    payload: dict[str, object] = {
        "config": args.config,
        "paper": args.paper,
        "fallback_file": args.fallback_file,
        "payloads_file": args.payloads_file,
        "scan": list(args.scan or []),
        "has_passphrase": args.passphrase is not None,
        "shard_fallback_file": list(args.shard_fallback_file or []),
        "shard_payloads_file": list(args.shard_payloads_file or []),
        "shard_scan": list(args.shard_scan or []),
        "auth_fallback_file": args.auth_fallback_file,
        "auth_payloads_file": args.auth_payloads_file,
        "extension_index": args.extension_index,
        "extension_doc_hash": normalized_extension_doc_hash,
        "expected_head_doc_hash": normalized_expected_head_doc_hash,
        "quiet": args.quiet,
        "debug": debug,
    }
    if operation is not None:
        payload["operation"] = operation
    else:
        payload["output"] = args.output
    return payload


def _emit_recovered_file_artifacts(file_payloads: tuple[dict[str, object], ...]) -> None:
    for file_payload in file_payloads:
        emit_artifact(
            kind="recovered_file",
            path=str(file_payload["output_path"]),
            details=dict(file_payload),
        )


def run_recover_api_command(args: RecoverArgs, *, debug: bool = False) -> int:
    if not args.output:
        raise ApiCommandError(
            code=api_codes.OUTPUT_REQUIRED,
            message="--output is required for `ethernity api recover`",
        )

    emit_started(
        command="recover",
        schema_version=SCHEMA_VERSION,
        args=_recover_started_args(args, debug=debug),
    )

    sink = active_event_sink()
    plan = prepare_recover_plan(args, event_sink=sink)
    execution = execute_recover_plan(
        plan,
        quiet=True,
        debug=debug,
        debug_max_bytes=args.debug_max_bytes,
        debug_reveal_secrets=args.debug_reveal_secrets,
        emit_file_artifacts=False,
        event_sink=sink,
    )

    _emit_recovered_file_artifacts(execution.file_payloads)
    expected_head_doc_hash = getattr(
        execution,
        "expected_head_doc_hash",
        getattr(execution.plan, "expected_head_doc_hash", None),
    )
    requested_extension_index = getattr(execution, "requested_extension_index", None)
    requested_extension_doc_hash = getattr(execution, "requested_extension_doc_hash", None)
    validated_head_doc_hash = (
        execution.selected_extension_doc_hash
        or getattr(
            execution.plan,
            "doc_hash",
            b"",
        ).hex()
    )
    emit_result(
        command="recover",
        output_path=execution.output_path,
        output_path_kind=execution.output_path_kind,
        doc_id=execution.plan.doc_id.hex(),
        selected_extension_index=execution.selected_extension_index,
        selected_extension_doc_hash=execution.selected_extension_doc_hash,
        expected_head_doc_hash=expected_head_doc_hash,
        validated_head_index=(
            execution.selected_extension_index
            if execution.selected_extension_index is not None
            else 0
        ),
        validated_head_doc_hash=validated_head_doc_hash,
        freshness_scope=(
            "supplied_carriers_only"
            if execution.selected_extension_index is not None
            or requested_extension_index is not None
            or requested_extension_doc_hash is not None
            or expected_head_doc_hash is not None
            else None
        ),
        auth_status=execution.plan.auth_status,
        input_label=execution.plan.input_label,
        input_detail=execution.plan.input_detail,
        manifest=_manifest_summary_payload(execution.manifest),
        files=list(execution.file_payloads),
    )
    return 0


def run_recover_inspect_api_command(args: RecoverArgs, *, debug: bool = False) -> int:
    emit_started(
        command="recover",
        schema_version=SCHEMA_VERSION,
        args=_recover_started_args(args, debug=debug, operation="inspect"),
    )

    sink = _ForwardingWarningCollector(active_event_sink())
    with event_session(sink):
        emit_phase(phase="plan", label="Resolving recovery inputs")
        inspection = inspect_from_args(args)
        emit_progress(
            phase="plan",
            current=1,
            total=1,
            unit="step",
            details={
                "main_frame_count": len(inspection.main_frames),
                "auth_frame_count": len(inspection.auth_frames),
                "shard_frame_count": len(inspection.shard_frames),
            },
        )

        blocking_issues = [dict(item) for item in inspection.blocking_issues]
        source_summary: dict[str, object] | None = None
        selected_extension_index: int | None = None
        selected_extension_doc_hash: str | None = None
        plan = None
        if inspection.unlock.satisfied and inspection.unlock.resolved_passphrase is not None:
            emit_phase(phase="decrypt", label="Decrypting and inspecting payload")
            try:
                plan = plan_from_inspection(args, inspection)
                if plan.import_documents:
                    chain = recover_chain_entries(plan, quiet=True, debug=debug)
                    manifest = chain.manifest
                    selected_extension_index = chain.selected_extension_index
                    selected_extension_doc_hash = chain.selected_extension_doc_hash
                else:
                    plaintext = decrypt_bytes(
                        inspection.ciphertext,
                        passphrase=inspection.unlock.resolved_passphrase,
                        debug=debug,
                    )
                    manifest, _payload = decode_envelope(plaintext)
                    validate_root_manifest_authority(manifest, inspection.auth_payload)
                source_summary = _manifest_summary_payload(manifest)
                emit_progress(
                    phase="decrypt",
                    current=1,
                    total=1,
                    unit="step",
                    details={
                        "file_count": len(manifest.files),
                        "manifest_file_count": len(manifest.files),
                    },
                )
            except Exception as exc:
                if getattr(plan, "import_documents", ()):
                    blocking_issues.append(_inspect_replay_blocking_issue(exc))
                else:
                    blocking_issues.append(_inspect_decrypt_blocking_issue(exc))

        emit_result(
            **inspect_result_payload(
                command="recover",
                source_summary=source_summary,
                frame_counts={
                    "main": len(inspection.main_frames),
                    "auth": len(inspection.auth_frames),
                    "shard": len(inspection.shard_frames),
                },
                unlock={
                    "mode": inspection.unlock.mode,
                    "passphrase_provided": inspection.unlock.passphrase_provided,
                    "validated_shard_count": inspection.unlock.validated_shard_count,
                    "required_shard_threshold": inspection.unlock.required_shard_threshold,
                    "shard_share_count": inspection.unlock.shard_share_count,
                    "satisfied": inspection.unlock.satisfied and source_summary is not None,
                },
                blocking_issues=blocking_issues,
                warnings=list(sink.warning_records),
                doc_id=inspection.doc_id.hex(),
                selected_extension_index=selected_extension_index,
                selected_extension_doc_hash=selected_extension_doc_hash,
                expected_head_doc_hash=args.expected_head_doc_hash,
                validated_head_index=(
                    selected_extension_index if selected_extension_index is not None else 0
                ),
                validated_head_doc_hash=selected_extension_doc_hash or inspection.doc_hash.hex(),
                freshness_scope=(
                    "supplied_carriers_only"
                    if selected_extension_index is not None
                    or args.extension_index is not None
                    or args.extension_doc_hash is not None
                    or args.expected_head_doc_hash is not None
                    else None
                ),
                auth_status=inspection.auth_status,
                input_label=inspection.input_label,
                input_detail=inspection.input_detail,
            )
        )
    return 0


__all__ = [
    "run_recover_api_command",
    "run_recover_inspect_api_command",
    "_ForwardingWarningCollector",
    "_manifest_summary_payload",
]
