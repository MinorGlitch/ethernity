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

from .. import api_codes
from ..core.types import BackupArgs, BackupResult
from ..events import active_event_sink, emit_artifact, emit_result
from ..ndjson import SCHEMA_VERSION, ApiCommandError, emit_started
from .backup_service import execute_prepared_backup, prepare_backup_run


def _artifact_details(path: str) -> dict[str, object]:
    path_obj = Path(path)
    details: dict[str, object] = {"filename": path_obj.name}
    if path_obj.exists():
        details["size"] = path_obj.stat().st_size
    return details


def _emit_backup_artifacts(result: BackupResult) -> None:
    emit_artifact(
        kind="qr_document", path=result.qr_path, details=_artifact_details(result.qr_path)
    )
    emit_artifact(
        kind="recovery_document",
        path=result.recovery_path,
        details=_artifact_details(result.recovery_path),
    )
    if result.kit_index_path is not None:
        emit_artifact(
            kind="recovery_kit_index",
            path=result.kit_index_path,
            details=_artifact_details(result.kit_index_path),
        )
    for shard_path in result.shard_paths:
        emit_artifact(kind="shard_document", path=shard_path, details=_artifact_details(shard_path))
    for shard_path in result.signing_key_shard_paths:
        emit_artifact(
            kind="signing_key_shard_document",
            path=shard_path,
            details=_artifact_details(shard_path),
        )


def run_backup_api_command(args: BackupArgs) -> int:
    if not args.input and not args.input_dir:
        raise ApiCommandError(
            code=api_codes.INPUT_REQUIRED,
            message="Use --input PATH, --input-dir DIR, or --input - for stdin.",
        )

    emit_started(
        command="backup",
        schema_version=SCHEMA_VERSION,
        args={
            "input": list(args.input or []),
            "input_dir": list(args.input_dir or []),
            "base_dir": args.base_dir,
            "output_dir": args.output_dir,
            "has_passphrase": args.passphrase is not None,
            "passphrase_generate": args.passphrase_generate,
            "passphrase_words": args.passphrase_words,
            "sealed": args.sealed,
            "shard_threshold": args.shard_threshold,
            "shard_count": args.shard_count,
            "signing_key_mode": args.signing_key_mode,
            "signing_key_shard_threshold": args.signing_key_shard_threshold,
            "signing_key_shard_count": args.signing_key_shard_count,
        },
    )

    sink = active_event_sink()
    prepared = prepare_backup_run(args, event_sink=sink)
    result = execute_prepared_backup(prepared, event_sink=sink)

    _emit_backup_artifacts(result)
    emit_result(
        command="backup",
        doc_id=result.doc_id.hex(),
        output_dir=str(Path(result.qr_path).parent),
        input_origin=prepared.input_origin,
        input_roots=list(prepared.input_roots),
        input_count=len(prepared.input_files),
        passphrase=result.passphrase_used,
        artifacts={
            "qr_document": result.qr_path,
            "recovery_document": result.recovery_path,
            "recovery_kit_index": result.kit_index_path,
            "shard_documents": list(result.shard_paths),
            "signing_key_shard_documents": list(result.signing_key_shard_paths),
        },
        plan={
            "sealed": prepared.plan.sealed,
            "shard_threshold": (
                prepared.plan.sharding.threshold if prepared.plan.sharding is not None else None
            ),
            "shard_count": (
                prepared.plan.sharding.shares if prepared.plan.sharding is not None else None
            ),
            "signing_key_mode": prepared.plan.signing_seed_mode.value,
            "signing_key_shard_threshold": (
                prepared.plan.signing_seed_sharding.threshold
                if prepared.plan.signing_seed_sharding is not None
                else None
            ),
            "signing_key_shard_count": (
                prepared.plan.signing_seed_sharding.shares
                if prepared.plan.signing_seed_sharding is not None
                else None
            ),
        },
    )
    return 0


__all__ = ["run_backup_api_command"]
