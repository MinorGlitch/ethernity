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

from pathlib import Path

from ethernity.cli.bootstrap.startup import ensure_playwright_browsers
from ethernity.cli.features.extend.planning import require_extend_root_dir, resolve_extend_state
from ethernity.cli.features.extend.service import (
    EXTENSION_INPUT_REQUIRED,
    PublishedExtensionResult,
    encrypt_prepared_extension_document,
    execute_prepared_extend,
    prepare_extend_run,
    prepare_extend_run_from_state,
    resolve_extend_runtime,
)
from ethernity.cli.features.recover.api_handlers import _ForwardingWarningCollector
from ethernity.cli.shared.events import (
    active_event_sink,
    emit_artifact,
    emit_phase,
    emit_progress,
    emit_result,
    event_session,
)
from ethernity.cli.shared.ndjson import (
    SCHEMA_VERSION,
    ApiCommandError,
    emit_started,
    error_code_for_exception,
    error_details_for_exception,
)
from ethernity.cli.shared.types import ExtendArgs
from ethernity.core.bounds import MAX_CIPHERTEXT_BYTES
from ethernity.extensions.build import default_extension_chunker
from ethernity.extensions.layout import parse_extension_shard_filename


def _artifact_details(path: str) -> dict[str, object]:
    path_obj = Path(path)
    details: dict[str, object] = {"filename": path_obj.name}
    if path_obj.exists():
        details["size"] = path_obj.stat().st_size
    return details


def _preview_chunk_reuse(
    prepared,
) -> tuple[dict[str, int] | None, int | None]:
    encrypted = encrypt_prepared_extension_document(
        prepared,
        chunker=default_extension_chunker,
    )
    return (
        {
            "reused_chunks": encrypted.built.stats.reused_chunks,
            "new_chunks": encrypted.built.stats.new_chunks,
        },
        len(encrypted.ciphertext),
    )


def _extend_started_args(
    args: ExtendArgs,
    *,
    debug: bool,
    operation: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "config": args.config,
        "paper": args.paper,
        "design": args.design,
        "root_dir": args.root_dir,
        "input": list(args.input or []),
        "input_dir": list(args.input_dir or []),
        "base_dir": args.base_dir,
        "has_passphrase": args.passphrase is not None,
        "shard_fallback_file": list(args.shard_fallback_file or []),
        "shard_payloads_file": list(args.shard_payloads_file or []),
        "shard_scan": list(args.shard_scan or []),
        "unlock_policy": args.unlock_policy,
        "shard_threshold": args.shard_threshold,
        "shard_count": args.shard_count,
        "signing_key_mode": args.signing_key_mode,
        "signing_key_shard_threshold": args.signing_key_shard_threshold,
        "signing_key_shard_count": args.signing_key_shard_count,
        "quiet": args.quiet,
        "debug": debug,
    }
    if operation is not None:
        payload["operation"] = operation
    else:
        payload["layout_debug_dir"] = args.layout_debug_dir
        payload["qr_chunk_size"] = args.qr_chunk_size
    return payload


def _emit_extend_artifacts(result: PublishedExtensionResult) -> None:
    qr_document_path = str(result.qr_document_path)
    recovery_document_path = str(result.recovery_document_path)
    emit_artifact(
        kind="qr_document",
        path=qr_document_path,
        details=_artifact_details(qr_document_path),
    )
    emit_artifact(
        kind="recovery_document",
        path=recovery_document_path,
        details=_artifact_details(recovery_document_path),
    )
    recovery_kit_index_path = result.recovery_kit_index_path
    if recovery_kit_index_path is not None:
        emit_artifact(
            kind="recovery_kit_index",
            path=str(recovery_kit_index_path),
            details=_artifact_details(str(recovery_kit_index_path)),
        )
    for shard_path in result.shard_paths:
        emit_artifact(
            kind="shard_document",
            path=str(shard_path),
            details=_artifact_details(str(shard_path)),
        )
    for shard_path in result.signing_key_shard_paths:
        emit_artifact(
            kind="signing_key_shard_document",
            path=str(shard_path),
            details=_artifact_details(str(shard_path)),
        )


def _emit_layout_debug_artifacts(
    *,
    layout_debug_dir: str | None,
    result: PublishedExtensionResult,
) -> None:
    if layout_debug_dir is None or not layout_debug_dir.strip():
        return
    debug_dir = Path(layout_debug_dir).expanduser().resolve()
    candidates = [
        debug_dir / "qr_document.layout.json",
        debug_dir / "recovery_document.layout.json",
    ]
    if result.recovery_kit_index_path is not None:
        candidates.append(debug_dir / "recovery_kit_index.layout.json")
    for shard_path in [*result.shard_paths, *result.signing_key_shard_paths]:
        parsed = parse_extension_shard_filename(Path(shard_path).name)
        layout_name = (
            f"{parsed.doc_type}-{parsed.share_index:02d}-of-{parsed.share_count:02d}.layout.json"
        )
        candidates.append(debug_dir / layout_name)
    for path in candidates:
        if path.exists():
            emit_artifact(
                kind="layout_debug_json",
                path=str(path),
                details=_artifact_details(str(path)),
            )


def run_extend_api_command(args: ExtendArgs, *, debug: bool = False) -> int:
    require_extend_root_dir(args, command_name="ethernity api extend")
    if not args.input and not args.input_dir:
        raise ApiCommandError(
            code=EXTENSION_INPUT_REQUIRED,
            message="extend requires at least one explicit --input or --input-dir selection",
        )

    emit_started(
        command="extend",
        schema_version=SCHEMA_VERSION,
        args=_extend_started_args(args, debug=debug),
    )
    ensure_playwright_browsers(quiet=True)
    prepared = prepare_extend_run(args)
    executed = execute_prepared_extend(prepared)
    result = executed.result
    _emit_extend_artifacts(result)
    _emit_layout_debug_artifacts(layout_debug_dir=args.layout_debug_dir, result=result)
    emit_result(
        command="extend",
        index=result.index,
        doc_id=result.doc_id.hex(),
        doc_hash=result.doc_hash.hex(),
        root_doc_id=prepared.inspection.root_doc_id,
        root_doc_hash=prepared.inspection.root_doc_hash,
        chain_id=prepared.inspection.chain_id,
        extension_dir=str(result.final_dir),
        artifacts={
            "qr_document": str(result.qr_document_path),
            "recovery_document": str(result.recovery_document_path),
            "recovery_kit_index": (
                None
                if result.recovery_kit_index_path is None
                else str(result.recovery_kit_index_path)
            ),
            "shard_documents": [str(path) for path in result.shard_paths],
            "signing_key_shard_documents": [str(path) for path in result.signing_key_shard_paths],
        },
        selected_scope=prepared.inspection.selected_scope,
        diff_summary=prepared.inspection.diff_summary,
        chunk_reuse={
            "reused_chunks": executed.publish.encrypted.built.stats.reused_chunks,
            "new_chunks": executed.publish.encrypted.built.stats.new_chunks,
        },
        extension_bytes=len(executed.publish.encrypted.ciphertext),
    )
    return 0


def run_extend_inspect_api_command(args: ExtendArgs, *, debug: bool = False) -> int:
    require_extend_root_dir(args, command_name="ethernity api inspect extend")
    emit_started(
        command="extend",
        schema_version=SCHEMA_VERSION,
        args=_extend_started_args(args, debug=debug, operation="inspect"),
    )

    sink = _ForwardingWarningCollector(active_event_sink())
    with event_session(sink):
        emit_phase(phase="plan", label="Inspecting extension layout")
        resolved = resolve_extend_state(args)
        inspection = resolved.inspection
        blocking_issues = [dict(item) for item in inspection.blocking_issues]
        chunk_reuse: dict[str, int] | None = None
        estimated_extension_bytes: int | None = None
        diff_summary = inspection.diff_summary
        if (
            not blocking_issues
            and diff_summary is not None
            and (bool(diff_summary.get("changed_paths")) or bool(diff_summary.get("new_paths")))
        ):
            try:
                prepared = prepare_extend_run_from_state(args, resolved)
                resolve_extend_runtime(prepared)
                chunk_reuse, estimated_extension_bytes = _preview_chunk_reuse(prepared)
                if (
                    estimated_extension_bytes is not None
                    and estimated_extension_bytes > MAX_CIPHERTEXT_BYTES
                ):
                    blocking_issues.append(
                        {
                            "code": "RUNTIME_ERROR",
                            "message": (
                                "extension ciphertext exceeds MAX_CIPHERTEXT_BYTES "
                                f"({MAX_CIPHERTEXT_BYTES}): "
                                f"{estimated_extension_bytes} bytes"
                            ),
                            "details": {},
                        }
                    )
                    chunk_reuse = None
                    estimated_extension_bytes = None
            except ApiCommandError as exc:
                blocking_issues.append(
                    {
                        "code": exc.code,
                        "message": str(exc),
                        "details": dict(exc.details or {}),
                    }
                )
            except Exception as exc:
                blocking_issues.append(
                    {
                        "code": error_code_for_exception(exc),
                        "message": str(exc),
                        "details": error_details_for_exception(exc),
                    }
                )

        emit_progress(
            phase="plan",
            current=1,
            total=1,
            unit="step",
            details={
                "root_dir": inspection.root_dir,
                "discovered_extension_count": len(inspection.discovered_extension_dirs),
            },
        )

        emit_result(
            command="extend",
            operation="inspect",
            doc_id=inspection.doc_id,
            input_label=inspection.input_label,
            input_detail=inspection.input_detail,
            input_kind=inspection.input_kind,
            source_summary=inspection.source_summary,
            frame_counts=inspection.frame_counts,
            root_doc_id=inspection.root_doc_id,
            root_doc_hash=inspection.root_doc_hash,
            chain_id=inspection.chain_id,
            auth_status=inspection.auth_status,
            unlock=inspection.unlock,
            discovered_extension_dirs=list(inspection.discovered_extension_dirs),
            validated_head_index=inspection.validated_head_index,
            validated_head_doc_hash=inspection.validated_head_doc_hash,
            available_extensions=list(inspection.available_extensions),
            ancestry_valid=inspection.ancestry_valid,
            validated_head_auth_status=inspection.validated_head_auth_status,
            validated_head_root_authority_verified=inspection.validated_head_root_authority_verified,
            signing_authority=inspection.signing_authority,
            selected_scope=inspection.selected_scope,
            diff_summary=inspection.diff_summary,
            chunk_reuse=chunk_reuse,
            estimated_extension_bytes=estimated_extension_bytes,
            blocking_issues=blocking_issues,
            warnings=list(sink.warning_records),
        )
    return 0


__all__ = ["run_extend_api_command", "run_extend_inspect_api_command"]
