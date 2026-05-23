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

from pypdf import PdfReader

from ethernity.cli.features.recover.key_recovery import resolve_auth_payload
from ethernity.cli.shared.crypto import doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.io.frames import (
    _dedupe_frames,
    _split_main_and_auth_frames,
    recovery_frames_from_scan,
)
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import Frame, FrameType
from ethernity.render.proofs import (
    RenderProofError,
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
    validate_text_in_pdf,
)
from ethernity.render.types import RenderFallbackProof

from .models import (
    EXTENSION_MAIN_CARRIER_INVALID,
    PreparedExtensionPublishPlan,
    RenderedExtensionArtifacts,
)


def validate_staged_main_carrier(
    plan: PreparedExtensionPublishPlan,
    rendered: RenderedExtensionArtifacts,
) -> None:
    expected_sign_pub = derive_public_key(plan.prepared.signing_seed)
    validate_single_main_carrier(
        path=plan.artifacts.qr_document_path,
        expected_doc_id=plan.encrypted.doc_id,
        expected_doc_hash=plan.encrypted.doc_hash,
        expected_sign_pub=expected_sign_pub,
        require_auth=True,
        quiet=plan.prepared.args.quiet,
    )
    validate_single_recovery_document_carrier(
        path=plan.artifacts.recovery_document_path,
        frames=rendered.recovery_document_fallback_frames,
        fallback_proof=rendered.recovery_document_fallback_proof,
        expected_doc_id=plan.encrypted.doc_id,
        expected_doc_hash=plan.encrypted.doc_hash,
        expected_sign_pub=expected_sign_pub,
        require_auth=True,
        quiet=plan.prepared.args.quiet,
    )


def validate_single_main_carrier(
    *,
    path: Path,
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    expected_sign_pub: bytes,
    require_auth: bool,
    quiet: bool,
) -> None:
    try:
        frames = recovery_frames_from_scan([str(path)], quiet=quiet)
        _validate_main_carrier_frames(
            path=path,
            frames=frames,
            expected_doc_id=expected_doc_id,
            expected_doc_hash=expected_doc_hash,
            expected_sign_pub=expected_sign_pub,
            require_auth=require_auth,
            quiet=quiet,
        )
    except ApiCommandError:
        raise
    except Exception as exc:
        raise ApiCommandError(
            code=EXTENSION_MAIN_CARRIER_INVALID,
            message=f"rendered MAIN carrier {path.name} is invalid: {exc}",
        ) from exc


def validate_single_recovery_document_carrier(
    *,
    path: Path,
    frames: tuple[Frame, ...],
    fallback_proof: RenderFallbackProof | None,
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    expected_sign_pub: bytes,
    require_auth: bool,
    quiet: bool,
) -> None:
    try:
        reader = _validate_recovery_document_pdf(path)
        _validate_recovery_document_fallback_proof(path, frames, fallback_proof)
        _validate_main_carrier_frames(
            path=path,
            frames=list(frames),
            expected_doc_id=expected_doc_id,
            expected_doc_hash=expected_doc_hash,
            expected_sign_pub=expected_sign_pub,
            require_auth=require_auth,
            quiet=quiet,
        )
        _validate_recovery_document_fallback_text(path, reader, fallback_proof)
    except ApiCommandError:
        raise
    except RenderProofError as exc:
        raise _render_proof_api_error(exc) from exc
    except Exception as exc:
        raise ApiCommandError(
            code=EXTENSION_MAIN_CARRIER_INVALID,
            message=f"rendered recovery document {path.name} is invalid: {exc}",
        ) from exc


def _validate_recovery_document_pdf(path: Path) -> PdfReader:
    return validate_pdf_has_pages(
        path,
        artifact_label=f"rendered recovery document {path.name}",
    )


def _validate_recovery_document_fallback_proof(
    path: Path,
    frames: tuple[Frame, ...],
    fallback_proof: RenderFallbackProof | None,
) -> None:
    try:
        validate_fallback_render_proof(
            artifact_label=f"rendered recovery document {path.name}",
            frames=frames,
            fallback_proof=fallback_proof,
        )
    except RenderProofError as exc:
        raise _render_proof_api_error(exc) from exc


def _validate_recovery_document_fallback_text(
    path: Path,
    reader: PdfReader,
    fallback_proof: RenderFallbackProof | None,
) -> None:
    try:
        validate_fallback_text_in_pdf(
            artifact_label=f"rendered recovery document {path.name}",
            reader=reader,
            fallback_proof=fallback_proof,
        )
    except RenderProofError as exc:
        raise _render_proof_api_error(exc) from exc


def _render_proof_api_error(exc: RenderProofError) -> ApiCommandError:
    return ApiCommandError(
        code=EXTENSION_MAIN_CARRIER_INVALID,
        message=str(exc),
        details=exc.details,
    )


def _validate_main_carrier_frames(
    *,
    path: Path,
    frames: list[Frame],
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    expected_sign_pub: bytes,
    require_auth: bool,
    quiet: bool,
) -> None:
    deduped = _dedupe_frames(list(frames))
    main_frames, auth_frames = _split_main_and_auth_frames(deduped)
    ciphertext = reassemble_payload(
        main_frames,
        expected_frame_type=FrameType.MAIN_DOCUMENT,
    )
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    if doc_id != expected_doc_id or doc_hash != expected_doc_hash:
        raise ApiCommandError(
            code=EXTENSION_MAIN_CARRIER_INVALID,
            message=(
                f"rendered MAIN carrier {path.name} does not match the planned extension ciphertext"
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
    if auth_payload is not None and auth_payload.sign_pub != expected_sign_pub:
        raise ApiCommandError(
            code=EXTENSION_MAIN_CARRIER_INVALID,
            message=(
                f"rendered extension AUTH in {path.name} does not match the "
                "root-derived signing authority"
            ),
        )


def validate_staged_recovery_kit_index_document(
    plan: PreparedExtensionPublishPlan,
) -> None:
    path = plan.artifacts.recovery_kit_index_path
    if path is None:
        return
    try:
        reader = validate_pdf_has_pages(
            path,
            artifact_label="rendered recovery_kit_index artifact",
        )
        validate_text_in_pdf(
            artifact_label="rendered recovery_kit_index artifact",
            reader=reader,
            expected_text=expected_recovery_kit_index_component_ids(plan),
            details_key="missing_component_ids",
            missing_message=(
                "rendered recovery_kit_index artifact is missing expected inventory rows"
            ),
        )
    except RenderProofError as exc:
        details = {"path": str(path), **exc.details}
        raise ApiCommandError(
            code=EXTENSION_MAIN_CARRIER_INVALID,
            message=str(exc),
            details=details,
        ) from exc


def expected_recovery_kit_index_component_ids(
    plan: PreparedExtensionPublishPlan,
) -> tuple[str, ...]:
    component_ids = [
        plan.encrypted.doc_id.hex(),
        f"Extension {plan.prepared.next_index:02d}",
        "ROOT-BACKUP",
        "QR-DOC-01",
        "RECOVERY-DOC-01",
    ]
    if plan.prepared.args.unlock_policy == "reuse-root":
        component_ids.append("ROOT-SHARDS")
    component_ids.extend(
        f"SHARD-{share_index:02d}"
        for share_index in range(1, plan.publish_policy.passphrase_shard_count + 1)
    )
    component_ids.extend(
        f"SIGNING-SHARD-{share_index:02d}"
        for share_index in range(1, plan.publish_policy.signing_key_shard_count + 1)
    )
    return tuple(component_ids)
