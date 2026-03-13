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

from ...core.models import SigningSeedMode
from .. import api_codes
from ..core.types import BackupArgs, BackupResult
from ..events import active_event_sink, emit_artifact, emit_result
from ..ndjson import SCHEMA_VERSION, ApiCommandError, emit_started
from .backup_service import execute_prepared_backup, prepare_backup_run

_SHARD_LAYOUT_PATTERN = re.compile(
    r"^(?P<prefix>shard|signing-key-shard)-[0-9a-f]+-(?P<index>\d+)-of-(?P<count>\d+)\.pdf$"
)


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


def _emit_layout_debug_artifacts(
    *,
    layout_debug_dir: str | None,
    result: BackupResult,
) -> None:
    if layout_debug_dir is None or not layout_debug_dir.strip():
        return
    debug_dir = Path(layout_debug_dir).expanduser().resolve()
    candidates = [
        debug_dir / "qr_document.layout.json",
        debug_dir / "recovery_document.layout.json",
    ]
    if result.kit_index_path is not None:
        candidates.append(debug_dir / "recovery_kit_index.layout.json")
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
                kind="layout_debug_json", path=str(path), details=_artifact_details(str(path))
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
            "passphrase_generate": args.passphrase is None,
            "passphrase_generate_requested": args.passphrase_generate,
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
    effective_signing_key_mode = prepared.plan.signing_seed_mode.value
    if prepared.plan.sealed and prepared.plan.signing_seed_mode == SigningSeedMode.SHARDED:
        effective_signing_key_mode = SigningSeedMode.EMBEDDED.value
    elif result.signing_key_shard_paths:
        effective_signing_key_mode = SigningSeedMode.SHARDED.value
    effective_signing_key_shard_threshold = (
        prepared.plan.signing_seed_sharding.threshold
        if result.signing_key_shard_paths and prepared.plan.signing_seed_sharding is not None
        else None
    )
    effective_signing_key_shard_count = (
        prepared.plan.signing_seed_sharding.shares
        if result.signing_key_shard_paths and prepared.plan.signing_seed_sharding is not None
        else None
    )

    _emit_backup_artifacts(result)
    _emit_layout_debug_artifacts(layout_debug_dir=prepared.args.layout_debug_dir, result=result)
    emit_result(
        command="backup",
        doc_id=result.doc_id.hex(),
        output_dir=str(Path(result.qr_path).parent),
        input_origin=prepared.input_origin,
        input_roots=list(prepared.input_roots),
        input_count=len(prepared.input_files),
        generated_passphrase=(result.passphrase_used if args.passphrase is None else None),
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
            "signing_key_mode": effective_signing_key_mode,
            "signing_key_shard_threshold": effective_signing_key_shard_threshold,
            "signing_key_shard_count": effective_signing_key_shard_count,
        },
    )
    return 0


__all__ = ["run_backup_api_command"]
