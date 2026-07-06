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

from ethernity.cli.bootstrap.startup import ensure_playwright_browsers
from ethernity.cli.features.compact.service import run_compact
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.events import emit_artifact, emit_phase, emit_progress, emit_result
from ethernity.cli.shared.ndjson import SCHEMA_VERSION, ApiCommandError, emit_started
from ethernity.cli.shared.paths import display_parent_path
from ethernity.cli.shared.types import BackupResult, CompactArgs

_SHARD_LAYOUT_PATTERN = re.compile(
    r"^(?P<prefix>shard|signing-key-shard)-[0-9a-f]+-(?P<index>\d+)-of-(?P<count>\d+)\.pdf$"
)


def _artifact_details(path: str) -> dict[str, object]:
    path_obj = Path(path)
    details: dict[str, object] = {"filename": path_obj.name}
    if path_obj.exists():
        details["size"] = path_obj.stat().st_size
    return details


def _emit_compact_artifacts(result: BackupResult) -> None:
    emit_artifact(
        kind="qr_document",
        path=result.qr_path,
        details=_artifact_details(result.qr_path),
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


def _emit_layout_debug_artifacts(*, layout_debug_dir: str | None, result: BackupResult) -> None:
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
                kind="layout_debug_json",
                path=str(path),
                details=_artifact_details(str(path)),
            )


def run_compact_api_command(args: CompactArgs, *, debug: bool = False) -> int:
    if not args.root_dir and not args.scan:
        raise ApiCommandError(
            code=api_codes.INPUT_REQUIRED,
            message="--root-dir or --scan is required for `ethernity api compact`",
        )
    if args.root_dir and args.scan:
        raise ApiCommandError(
            code=api_codes.INVALID_INPUT,
            message="use either --root-dir or --scan for compact, not both",
        )
    if args.scan and args.expected_head_doc_hash is None and not args.allow_stale_head:
        raise ApiCommandError(
            code=api_codes.RECOVERY_HEAD_UNTRUSTED,
            message=(
                "scan-mode compact cannot prove the supplied recovery set is the latest chain "
                "state; provide --expected-head-doc-hash or pass --allow-stale-head to "
                "acknowledge this risk"
            ),
            details={
                "stage": "selection",
                "freshness_scope": "supplied_carriers_only",
                "required_acknowledgement": "--allow-stale-head",
            },
        )
    if not args.output_dir:
        raise ApiCommandError(
            code=api_codes.OUTPUT_REQUIRED,
            message="--output-dir is required for `ethernity api compact`",
        )

    emit_started(
        command="compact",
        schema_version=SCHEMA_VERSION,
        args={
            "config": args.config,
            "paper": args.paper,
            "design": args.design,
            "root_dir": args.root_dir,
            "scan": list(args.scan or []),
            "output_dir": args.output_dir,
            "shard_fallback_file": list(args.shard_fallback_file or []),
            "shard_payloads_file": list(args.shard_payloads_file or []),
            "shard_scan": list(args.shard_scan or []),
            "auth_fallback_file": args.auth_fallback_file,
            "auth_payloads_file": args.auth_payloads_file,
            "expected_head_doc_hash": args.expected_head_doc_hash,
            "allow_stale_head": args.allow_stale_head,
            "layout_debug_dir": args.layout_debug_dir,
            "qr_chunk_size": args.qr_chunk_size,
            "has_passphrase": args.passphrase is not None,
            "quiet": args.quiet,
            "debug": debug,
        },
    )

    emit_phase(phase="compact", label="Replaying source chain and preparing checkpoint")
    emit_progress(
        phase="compact",
        current=0,
        total=1,
        unit="step",
        details={
            "root_dir": args.root_dir,
            "scan": list(args.scan or []),
            "output_dir": args.output_dir,
        },
    )
    ensure_playwright_browsers(quiet=True)
    result = run_compact(args)
    emit_progress(
        phase="compact",
        current=1,
        total=1,
        unit="step",
        details={
            "root_dir": args.root_dir,
            "scan": list(args.scan or []),
            "output_dir": display_parent_path(result.qr_path),
        },
    )
    _emit_compact_artifacts(result)
    _emit_layout_debug_artifacts(layout_debug_dir=args.layout_debug_dir, result=result)
    emit_result(
        command="compact",
        doc_id=result.doc_id.hex(),
        root_dir=args.root_dir,
        source_scan=list(args.scan or []),
        output_dir=display_parent_path(result.qr_path),
        artifacts={
            "qr_document": result.qr_path,
            "recovery_document": result.recovery_path,
            "recovery_kit_index": result.kit_index_path,
            "shard_documents": list(result.shard_paths),
            "signing_key_shard_documents": list(result.signing_key_shard_paths),
        },
        expected_head_doc_hash=result.expected_head_doc_hash,
        validated_head_index=result.source_head_index,
        validated_head_doc_hash=result.source_head_doc_hash,
        freshness_scope=result.freshness_scope,
    )
    return 0


__all__ = ["run_compact_api_command"]
