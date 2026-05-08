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

"""Shard-carrier validation helpers for extend execution."""

from __future__ import annotations

from pathlib import Path

from ethernity.cli.shared.io.frames import _shard_frames_from_scan
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.crypto import sharding as sharding_module
from ethernity.crypto.signing import verify_shard

from .models import (
    EXTENSION_SHARD_CARRIER_INVALID,
    PreparedExtensionPublishPlan,
    RenderedExtensionArtifacts,
)


def validate_staged_shard_carriers(
    plan: PreparedExtensionPublishPlan,
    rendered: RenderedExtensionArtifacts,
) -> None:
    for path, expected in zip(plan.artifacts.shard_paths, rendered.passphrase_shards, strict=True):
        validate_rendered_shard_carrier(
            path=path,
            expected_payload=expected,
            expected_doc_id=plan.encrypted.doc_id,
            expected_doc_hash=plan.encrypted.doc_hash,
            quiet=plan.prepared.args.quiet,
            secret_label="passphrase shard",
        )
    for path, expected in zip(
        plan.artifacts.signing_key_shard_paths,
        rendered.signing_key_shards,
        strict=True,
    ):
        validate_rendered_shard_carrier(
            path=path,
            expected_payload=expected,
            expected_doc_id=plan.encrypted.doc_id,
            expected_doc_hash=plan.encrypted.doc_hash,
            quiet=plan.prepared.args.quiet,
            secret_label="signing-key shard",
        )


def validate_rendered_shard_carrier(
    *,
    path: Path,
    expected_payload: sharding_module.ShardPayload,
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    quiet: bool,
    secret_label: str,
) -> None:
    frames = _shard_frames_from_scan([str(path)], quiet=quiet)
    if len(frames) != 1:
        raise ApiCommandError(
            code=EXTENSION_SHARD_CARRIER_INVALID,
            message=f"rendered {secret_label} PDF must contain exactly one shard payload",
            details={"path": str(path)},
        )

    frame = frames[0]
    if frame.doc_id != expected_doc_id:
        raise ApiCommandError(
            code=EXTENSION_SHARD_CARRIER_INVALID,
            message=f"rendered {secret_label} doc_id does not match the extension ciphertext",
            details={"path": str(path)},
        )
    if frame.total != 1 or frame.index != 0:
        raise ApiCommandError(
            code=EXTENSION_SHARD_CARRIER_INVALID,
            message=f"rendered {secret_label} must be encoded as a single-frame payload",
            details={"path": str(path)},
        )

    payload = sharding_module.decode_shard_payload(frame.data)
    if payload != expected_payload:
        raise ApiCommandError(
            code=EXTENSION_SHARD_CARRIER_INVALID,
            message=f"rendered {secret_label} payload does not match the planned shard output",
            details={"path": str(path)},
        )
    if payload.doc_hash != expected_doc_hash:
        raise ApiCommandError(
            code=EXTENSION_SHARD_CARRIER_INVALID,
            message=f"rendered {secret_label} doc_hash does not match the extension ciphertext",
            details={"path": str(path)},
        )
    if not verify_shard(
        payload.doc_hash,
        shard_version=payload.version,
        key_type=payload.key_type,
        threshold=payload.threshold,
        share_count=payload.share_count,
        share_index=payload.share_index,
        secret_len=payload.secret_len,
        share=payload.share,
        shard_set_id=payload.shard_set_id,
        sign_pub=payload.sign_pub,
        signature=payload.signature,
    ):
        raise ApiCommandError(
            code=EXTENSION_SHARD_CARRIER_INVALID,
            message=f"rendered {secret_label} signature verification failed",
            details={"path": str(path)},
        )
