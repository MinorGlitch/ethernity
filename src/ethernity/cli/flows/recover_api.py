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

from hashlib import sha256

from ...formats.envelope_types import EnvelopeManifest, ManifestFile
from .. import api_codes
from ..core.log import _warn
from ..core.types import RecoverArgs
from ..events import active_event_sink, emit_artifact, emit_progress, emit_result
from ..ndjson import SCHEMA_VERSION, ApiCommandError, emit_started
from .recover_service import execute_recover_plan, prepare_recover_plan


def _result_file_payload(
    entry: ManifestFile, *, written_path: str, data: bytes
) -> dict[str, object]:
    return {
        "manifest_path": entry.path,
        "output_path": written_path,
        "size": len(data),
        "sha256": sha256(data).hexdigest(),
        "mtime": entry.mtime,
    }


def _manifest_payload(manifest: EnvelopeManifest) -> dict[str, object]:
    return {
        "format_version": manifest.format_version,
        "input_origin": manifest.input_origin,
        "input_roots": list(manifest.input_roots),
        "sealed": manifest.sealed,
        "payload_codec": manifest.payload_codec,
        "payload_raw_len": manifest.payload_raw_len,
        "file_count": len(manifest.files),
    }


def run_recover_api_command(args: RecoverArgs, *, debug: bool = False) -> int:
    if not args.output:
        raise ApiCommandError(
            code=api_codes.OUTPUT_REQUIRED,
            message="--output is required for `ethernity api recover`",
        )

    emit_started(
        command="recover",
        schema_version=SCHEMA_VERSION,
        args={
            "fallback_file": args.fallback_file,
            "payloads_file": args.payloads_file,
            "scan": list(args.scan or []),
            "has_passphrase": args.passphrase is not None,
            "shard_fallback_file": list(args.shard_fallback_file or []),
            "shard_payloads_file": list(args.shard_payloads_file or []),
            "auth_fallback_file": args.auth_fallback_file,
            "auth_payloads_file": args.auth_payloads_file,
            "output": args.output,
            "allow_unsigned": args.allow_unsigned,
        },
    )

    sink = active_event_sink()
    plan = prepare_recover_plan(args, event_sink=sink)
    if plan.allow_unsigned:
        _warn(
            "Authentication check skipped - ensure you trust the source",
            quiet=args.quiet,
            code=api_codes.AUTH_CHECK_SKIPPED,
        )
    execution = execute_recover_plan(
        plan,
        quiet=True,
        debug=debug,
        debug_max_bytes=args.debug_max_bytes,
        debug_reveal_secrets=args.debug_reveal_secrets,
        event_sink=sink,
    )

    files: list[dict[str, object]] = []
    total_files = len(execution.written_paths)
    for index, ((entry, data), written_path) in enumerate(
        zip(execution.extracted, execution.written_paths, strict=True),
        start=1,
    ):
        file_payload = _result_file_payload(entry, written_path=written_path, data=data)
        files.append(file_payload)
        emit_progress(
            phase="write",
            current=index,
            total=total_files,
            unit="files",
            label=f"Wrote recovered file {index} of {total_files}",
            details={"output_path": written_path, "manifest_path": entry.path},
        )
        emit_artifact(kind="recovered_file", path=written_path, details=file_payload)

    emit_result(
        command="recover",
        output_path=execution.plan.output_path,
        doc_id=execution.plan.doc_id.hex(),
        auth_status=execution.plan.auth_status,
        input_label=execution.plan.input_label,
        input_detail=execution.plan.input_detail,
        manifest=_manifest_payload(execution.manifest),
        files=files,
    )
    return 0


__all__ = ["run_recover_api_command"]
