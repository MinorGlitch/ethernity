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

"""Adapter-neutral recovery inspection and imported-root selection."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ethernity.crypto.age_policy import RecoveryResourceLimitError
from ethernity.crypto.sharding import KEY_TYPE_PASSPHRASE, decode_shard_payload, recover_passphrase
from ethernity.crypto.signing import AuthPayload
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions.recovery import (
    DecodedExtensionLink,
    DecodedImportSession,
    ImportedRecoveryDocument,
    decode_imported_extension_link,
    select_root_import_session,
)
from ethernity.workflows.recovery.keys import (
    AuthValidationError,
    InsufficientShardError,
    RecoveryTrust,
    resolve_auth_payload,
)
from ethernity.workflows.recovery.models import (
    PassphraseShardRootSelection,
    RecoveryInspection,
    RecoveryUnlockStatus,
)
from ethernity.workflows.recovery.source_state import (
    assemble_recovery_document,
    require_recovery_frames,
)
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.inspection import blocking_issue
from ethernity.workflows.shared.notices import WorkflowNoticeSink


def inspect_recovery_inputs(
    *,
    frames: list[Frame],
    extra_auth_frames: list[Frame],
    shard_frames: list[Frame],
    passphrase: str | None,
    allow_unsigned: bool,
    input_label: str | None,
    input_detail: str | None,
    shard_fallback_files: list[str],
    shard_payloads_file: list[str],
    shard_scan: list[str],
    _notice_sink: WorkflowNoticeSink | None = None,
) -> RecoveryInspection:
    """Assemble best-effort recovery inspection state from decoded frames."""

    require_recovery_frames(frames, input_label)

    document = assemble_recovery_document(
        frames, extra_auth_frames, input_label=input_label, input_detail=input_detail
    )
    auth_frames = list(document.source.auth_frames)
    doc_id, doc_hash = document.doc_id, document.doc_hash
    auth_payload, auth_status, auth_blocking_issues = _inspect_auth_payload(
        auth_frames,
        **RecoveryTrust(doc_id, doc_hash, allow_unsigned=allow_unsigned).auth_options(
            require_auth=not allow_unsigned
        ),
        notice_sink=_notice_sink,
    )
    unlock = _inspect_unlock_status(
        passphrase=passphrase,
        shard_frames=shard_frames,
        doc_id=doc_id,
        doc_hash=doc_hash,
        sign_pub=auth_payload.sign_pub if auth_payload is not None else None,
        allow_unsigned=allow_unsigned,
    )
    if auth_blocking_issues and unlock.satisfied:
        unlock = replace(unlock, satisfied=False, resolved_passphrase=None)
    blocking_issues = [*auth_blocking_issues, *unlock.blocking_issues]
    return RecoveryInspection(
        ciphertext=document.ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
        auth_payload=auth_payload,
        auth_status=auth_status,
        allow_unsigned=allow_unsigned,
        unlock=unlock,
        blocking_issues=tuple(blocking_issues),
        source=document.source.with_shards(
            shard_frames, shard_fallback_files, shard_payloads_file, shard_scan
        ),
    )


def select_root_import_document_from_passphrase_shards(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    shard_frames: list[Frame],
    allow_unsigned: bool,
    _notice_sink: WorkflowNoticeSink | None = None,
) -> PassphraseShardRootSelection:
    """Select and authenticate an imported root using document-bound passphrase shards."""

    candidates = _select_import_documents_bound_to_passphrase_shards(
        documents,
        shard_frames=shard_frames,
    )
    last_unlock_failure: str | None = None
    for target_document, target_shard_frames in candidates:
        target_auth_payload, _target_auth_status = resolve_auth_payload(
            list(target_document.auth_frames),
            **RecoveryTrust(
                target_document.doc_id, target_document.doc_hash, allow_unsigned=allow_unsigned
            ).auth_options(require_auth=not allow_unsigned),
            _notice_sink=_notice_sink,
        )
        unlock = _inspect_unlock_status(
            passphrase=None,
            shard_frames=list(target_shard_frames),
            doc_id=target_document.doc_id,
            doc_hash=target_document.doc_hash,
            sign_pub=target_auth_payload.sign_pub if target_auth_payload is not None else None,
            allow_unsigned=allow_unsigned,
        )
        if not unlock.satisfied or unlock.resolved_passphrase is None:
            last_unlock_failure = _unlock_failure_message(unlock)
            continue
        decoded_import_session = select_root_import_session(
            documents,
            passphrase=unlock.resolved_passphrase,
            debug=False,
        )
        root_document = decoded_import_session.root_document
        root_auth_payload, _root_auth_status = resolve_auth_payload(
            list(root_document.auth_frames),
            **RecoveryTrust(
                root_document.doc_id, root_document.doc_hash, allow_unsigned=allow_unsigned
            ).auth_options(require_auth=not allow_unsigned),
            _notice_sink=_notice_sink,
        )
        _verify_shard_target_belongs_to_selected_root(
            target_document=target_document,
            root_document=root_document,
            passphrase=unlock.resolved_passphrase,
            root_auth_payload=root_auth_payload,
            decoded_import_session=decoded_import_session,
            allow_unsigned=allow_unsigned,
        )
        return PassphraseShardRootSelection(
            root_document=root_document,
            target_document=target_document,
            target_shard_frames=target_shard_frames,
            unlock=unlock,
            decoded_import_session=decoded_import_session,
        )
    raise ValueError(
        last_unlock_failure or "shard payloads do not match any imported recovery document"
    )


def _select_import_documents_bound_to_passphrase_shards(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    shard_frames: list[Frame],
) -> tuple[tuple[ImportedRecoveryDocument, tuple[Frame, ...]], ...]:
    shard_groups: dict[tuple[bytes, bytes], list[Frame]] = {}
    for frame in shard_frames:
        if frame.frame_type != FrameType.KEY_DOCUMENT:
            continue
        if frame.total != 1 or frame.index != 0:
            raise ValueError("shard payloads must be single-frame payloads")
        payload = decode_shard_payload(frame.data)
        if payload.key_type != KEY_TYPE_PASSPHRASE:
            continue
        shard_groups.setdefault((frame.doc_id, payload.doc_hash), []).append(frame)

    if not shard_groups:
        raise ValueError(
            "passphrase is required when recovery input contains multiple MAIN documents"
        )
    candidates: list[tuple[ImportedRecoveryDocument, tuple[Frame, ...]]] = []
    for document in documents:
        frames = shard_groups.get((document.doc_id, document.doc_hash))
        if frames:
            candidates.append((document, tuple(frames)))
    if not candidates:
        raise ValueError("shard payloads do not match any imported recovery document")
    return tuple(candidates)


def _verify_shard_target_belongs_to_selected_root(
    *,
    target_document: ImportedRecoveryDocument,
    root_document: ImportedRecoveryDocument,
    passphrase: str,
    root_auth_payload: AuthPayload | None,
    decoded_import_session: DecodedImportSession,
    allow_unsigned: bool,
) -> None:
    if (
        target_document.doc_id == root_document.doc_id
        and target_document.doc_hash == root_document.doc_hash
    ):
        return
    if root_auth_payload is None:
        if allow_unsigned:
            return
        raise ValueError("recovery-sheet target requires verified root AUTH")
    try:
        decoded = decode_imported_extension_link(
            target_document,
            passphrase=passphrase,
            expected_sign_pub=root_auth_payload.sign_pub,
            debug=False,
            decoded_import_session=decoded_import_session,
        )
    except RecoveryResourceLimitError:
        raise
    except ValueError as exc:
        raise ValueError(
            "shard payloads target a document that is not an authenticated extension "
            "for the selected root backup"
        ) from exc
    _ensure_decoded_shard_target_uses_selected_root(
        decoded,
        root_doc_hash=root_document.doc_hash,
    )


def _ensure_decoded_shard_target_uses_selected_root(
    decoded: DecodedExtensionLink,
    *,
    root_doc_hash: bytes,
) -> None:
    if decoded.link.document.header.root_doc_hash != root_doc_hash:
        raise ValueError("shard payloads target an extension for a different root backup")


def _unlock_failure_message(unlock: RecoveryUnlockStatus) -> str:
    if unlock.blocking_issues:
        return str(unlock.blocking_issues[0]["message"])
    return "passphrase shard inputs could not recover a passphrase"


def _inspect_auth_payload(
    auth_frames: list[Frame],
    *,
    doc_id: bytes,
    doc_hash: bytes,
    allow_unsigned: bool,
    require_auth: bool,
    notice_sink: WorkflowNoticeSink | None,
) -> tuple[AuthPayload | None, str, tuple[dict[str, Any], ...]]:
    try:
        payload, status = resolve_auth_payload(
            auth_frames,
            **RecoveryTrust(doc_id, doc_hash, allow_unsigned=allow_unsigned).auth_options(
                require_auth=require_auth
            ),
            _notice_sink=notice_sink,
        )
    except AuthValidationError as exc:
        return (
            None,
            exc.status,
            (blocking_issue(exc.issue_code, exc.inspection_message, details=exc.details),),
        )
    return payload, status, ()


def _inspect_unlock_status(
    *,
    passphrase: str | None,
    shard_frames: list[Frame],
    doc_id: bytes,
    doc_hash: bytes,
    sign_pub: bytes | None,
    allow_unsigned: bool,
) -> RecoveryUnlockStatus:
    if shard_frames and passphrase:
        raise ValueError("use either shard inputs or passphrase, not both")
    if shard_frames:
        try:
            shard_payloads = RecoveryTrust(
                doc_id, doc_hash, sign_pub, allow_unsigned
            ).validated_shards(
                shard_frames, key_type=KEY_TYPE_PASSPHRASE, secret_label="passphrase"
            )
        except InsufficientShardError as exc:
            return RecoveryUnlockStatus.unavailable(
                "shards",
                (
                    blocking_issue(
                        issue_codes.PASSPHRASE_SHARDS_UNDER_QUORUM,
                        f"need at least {exc.threshold} shard(s) to recover passphrase",
                        details={
                            "provided_count": exc.provided_count,
                            "required_threshold": exc.threshold,
                        },
                    ),
                ),
                provided_count=exc.provided_count,
                threshold=exc.threshold,
                share_count=exc.share_count,
            )
        except ValueError as exc:
            return RecoveryUnlockStatus.unavailable(
                "shards", (blocking_issue(issue_codes.PASSPHRASE_SHARDS_INVALID, str(exc)),)
            )
        return RecoveryUnlockStatus(
            mode="shards",
            passphrase_provided=False,
            validated_shard_count=len(shard_payloads),
            required_shard_threshold=shard_payloads[0].threshold if shard_payloads else None,
            satisfied=True,
            resolved_passphrase=recover_passphrase(shard_payloads, verify_signatures=False),
            shard_share_count=shard_payloads[0].share_count if shard_payloads else None,
        )
    if passphrase:
        return RecoveryUnlockStatus(
            mode="passphrase",
            passphrase_provided=True,
            validated_shard_count=0,
            required_shard_threshold=None,
            satisfied=True,
            resolved_passphrase=passphrase,
        )
    return RecoveryUnlockStatus.unavailable(
        "missing",
        (
            blocking_issue(
                issue_codes.PASSPHRASE_REQUIRED,
                "passphrase or passphrase shard inputs are required to decrypt this backup",
            ),
        ),
    )


__all__ = [
    "inspect_recovery_inputs",
    "select_root_import_document_from_passphrase_shards",
]
