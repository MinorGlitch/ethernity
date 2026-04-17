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

"""Main-carrier validation helpers for extend execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pypdf import PdfReader

from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.encoding.framing import FrameType

from .models import (
    EXTENSION_MAIN_CARRIER_INVALID,
    PreparedExtensionPublishPlan,
    RenderedExtensionArtifacts,
)


def validate_staged_main_carriers(
    plan: PreparedExtensionPublishPlan,
    rendered: RenderedExtensionArtifacts,
    *,
    derive_public_key: Callable[[bytes], bytes],
    validate_single_main_carrier_fn: Callable[..., None],
) -> None:
    expected_sign_pub = derive_public_key(plan.prepared.signing_seed)
    validate_single_main_carrier_fn(
        path=plan.artifacts.qr_document_path,
        expected_ciphertext=plan.encrypted.ciphertext,
        expected_doc_id=plan.encrypted.doc_id,
        expected_doc_hash=plan.encrypted.doc_hash,
        expected_sign_pub=expected_sign_pub,
        require_auth=True,
        quiet=plan.prepared.args.quiet,
    )
    validate_single_main_carrier_fn(
        path=plan.artifacts.recovery_document_path,
        expected_ciphertext=plan.encrypted.ciphertext,
        expected_doc_id=plan.encrypted.doc_id,
        expected_doc_hash=plan.encrypted.doc_hash,
        expected_sign_pub=expected_sign_pub,
        expected_recovery_fallback_lines=rendered.expected_recovery_fallback_lines,
        require_auth=True,
        quiet=plan.prepared.args.quiet,
    )


def validate_single_main_carrier(
    *,
    path: Path,
    expected_ciphertext: bytes,
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    expected_sign_pub: bytes,
    expected_recovery_fallback_lines: tuple[str, ...] | None = None,
    require_auth: bool,
    quiet: bool,
    recovery_frames_from_scan: Callable[..., list[Any]],
    dedupe_frames: Callable[[list[Any]], list[Any]],
    split_main_and_auth_frames: Callable[[list[Any]], tuple[list[Any], list[Any]]],
    reassemble_payload: Callable[..., bytes],
    doc_id_and_hash_from_ciphertext: Callable[[bytes], tuple[bytes, bytes]],
    resolve_auth_payload: Callable[..., tuple[Any, str]],
    validate_fallback_recovery_document_fn: Callable[..., None],
    is_qr_absent_scan_error: Callable[[Exception], bool],
) -> None:
    allow_fallback_validation = expected_recovery_fallback_lines is not None
    try:
        frames = recovery_frames_from_scan([str(path)], quiet=quiet)
        deduped = dedupe_frames(frames)
        main_frames, auth_frames = split_main_and_auth_frames(deduped)
        ciphertext = reassemble_payload(
            main_frames,
            expected_frame_type=FrameType.MAIN_DOCUMENT,
        )
        doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        if doc_id != expected_doc_id or doc_hash != expected_doc_hash:
            raise ApiCommandError(
                code=EXTENSION_MAIN_CARRIER_INVALID,
                message=(
                    f"rendered MAIN carrier {path.name} does not match the planned "
                    "extension ciphertext"
                ),
            )
        auth_payload, _auth_status = resolve_auth_payload(
            auth_frames,
            doc_id=expected_doc_id,
            doc_hash=expected_doc_hash,
            allow_unsigned=False,
            require_auth=require_auth,
            quiet=quiet,
        )
    except ApiCommandError:
        raise
    except Exception as exc:
        if allow_fallback_validation and is_qr_absent_scan_error(exc):
            validate_fallback_recovery_document_fn(
                path=path,
                expected_ciphertext=expected_ciphertext,
                expected_doc_id=expected_doc_id,
                expected_doc_hash=expected_doc_hash,
                expected_sign_pub=expected_sign_pub,
                expected_recovery_fallback_lines=expected_recovery_fallback_lines,
                quiet=quiet,
            )
            return
        raise ApiCommandError(
            code=EXTENSION_MAIN_CARRIER_INVALID,
            message=f"rendered MAIN carrier {path.name} is invalid: {exc}",
        ) from exc

    if auth_payload is not None and auth_payload.sign_pub != expected_sign_pub:
        raise ApiCommandError(
            code=EXTENSION_MAIN_CARRIER_INVALID,
            message=(
                f"rendered extension AUTH in {path.name} does not match the "
                "root-derived signing authority"
            ),
        )
    if expected_recovery_fallback_lines is not None:
        validate_fallback_recovery_document_fn(
            path=path,
            expected_ciphertext=expected_ciphertext,
            expected_doc_id=expected_doc_id,
            expected_doc_hash=expected_doc_hash,
            expected_sign_pub=expected_sign_pub,
            expected_recovery_fallback_lines=expected_recovery_fallback_lines,
            quiet=quiet,
        )


def validate_staged_recovery_kit_index_document(
    plan: PreparedExtensionPublishPlan,
    *,
    pdf_reader_factory: Callable[[str], PdfReader],
    expected_component_ids_fn: Callable[[PreparedExtensionPublishPlan], tuple[str, ...]],
) -> None:
    path = plan.artifacts.recovery_kit_index_path
    if path is None:
        return
    try:
        reader = pdf_reader_factory(str(path))
    except Exception as exc:
        raise ApiCommandError(
            code=EXTENSION_MAIN_CARRIER_INVALID,
            message=f"rendered recovery_kit_index artifact is invalid: {exc}",
            details={"path": str(path)},
        ) from exc
    if len(reader.pages) <= 0:
        raise ApiCommandError(
            code=EXTENSION_MAIN_CARRIER_INVALID,
            message="rendered recovery_kit_index artifact must contain at least one page",
            details={"path": str(path)},
        )
    extracted_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    missing_component_ids = [
        component_id
        for component_id in expected_component_ids_fn(plan)
        if component_id not in extracted_text
    ]
    if missing_component_ids:
        raise ApiCommandError(
            code=EXTENSION_MAIN_CARRIER_INVALID,
            message=(
                "rendered recovery_kit_index artifact is missing expected inventory rows: "
                + ", ".join(missing_component_ids)
            ),
            details={"path": str(path)},
        )


def expected_recovery_kit_index_component_ids(
    plan: PreparedExtensionPublishPlan,
) -> tuple[str, ...]:
    component_ids = ["QR-DOC-01", "RECOVERY-DOC-01"]
    component_ids.extend(
        f"SHARD-{share_index:02d}"
        for share_index in range(1, plan.publish_policy.passphrase_shard_count + 1)
    )
    component_ids.extend(
        f"SIGNING-SHARD-{share_index:02d}"
        for share_index in range(1, plan.publish_policy.signing_key_shard_count + 1)
    )
    return tuple(component_ids)
