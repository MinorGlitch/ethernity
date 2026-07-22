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

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.sharding import KEY_TYPE_PASSPHRASE, decode_shard_payload
from ethernity.crypto.signing import AuthPayload, decode_auth_payload, verify_auth
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.frame_sets import (
    deduplicate_auth_frames,
    deduplicate_frame_slots,
    split_main_and_auth_frames,
)
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions.recovery import (
    DecodedExtensionLink,
    DecodedImportSession,
    ImportedRecoveryDocument,
    decode_imported_extension_link,
    select_root_import_session,
)
from ethernity.workflows.recovery.keys import (
    InsufficientShardError,
    passphrase_from_shard_frames,
    resolve_auth_payload,
    validated_shard_payloads_from_frames,
)
from ethernity.workflows.recovery.models import (
    PassphraseShardRootSelection,
    RecoveryInspection,
    RecoveryUnlockStatus,
)
from ethernity.workflows.shared import api_codes

RECOVERY_SCAN_LABEL = "Backup PDF or images"


@dataclass(frozen=True)
class RecoveryInspectionNotice:
    """Non-fatal warning discovered while inspecting recovery material."""

    code: str
    message: str
    details: dict[str, object]


RecoveryInspectionNoticeSink = Callable[[RecoveryInspectionNotice], None]


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
    quiet: bool,
    _notice_sink: RecoveryInspectionNoticeSink | None = None,
) -> RecoveryInspection:
    """Assemble best-effort recovery inspection state from decoded frames."""

    _ = quiet
    if not frames:
        hint = "Check the input path and try again."
        if input_label == RECOVERY_SCAN_LABEL:
            hint = "Check the scan path and image quality, then try again."
        raise ValueError(f"no backup data found. {hint}")

    deduped = deduplicate_frame_slots(frames)
    main_frames, auth_frames = split_main_and_auth_frames(deduped)
    if extra_auth_frames:
        auth_frames = deduplicate_auth_frames([*auth_frames, *extra_auth_frames])

    ciphertext = reassemble_payload(main_frames, expected_frame_type=FrameType.MAIN_DOCUMENT)
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    auth_payload, auth_status, auth_blocking_issues = _inspect_auth_payload(
        auth_frames,
        doc_id=doc_id,
        doc_hash=doc_hash,
        allow_unsigned=allow_unsigned,
        require_auth=not allow_unsigned,
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
        ciphertext=ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
        auth_payload=auth_payload,
        auth_status=auth_status,
        allow_unsigned=allow_unsigned,
        input_label=input_label,
        input_detail=input_detail,
        main_frames=tuple(main_frames),
        auth_frames=tuple(auth_frames),
        shard_frames=tuple(shard_frames),
        shard_fallback_files=tuple(shard_fallback_files),
        shard_payloads_file=tuple(shard_payloads_file),
        shard_scan=tuple(shard_scan),
        unlock=unlock,
        blocking_issues=tuple(blocking_issues),
    )


def select_root_import_document_from_passphrase_shards(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    shard_frames: list[Frame],
    allow_unsigned: bool,
    quiet: bool,
    _notice_sink: RecoveryInspectionNoticeSink | None = None,
) -> PassphraseShardRootSelection:
    """Select and authenticate an imported root using document-bound passphrase shards."""

    _ = quiet
    candidates = _select_import_documents_bound_to_passphrase_shards(
        documents,
        shard_frames=shard_frames,
    )
    last_unlock_failure: str | None = None
    for target_document, target_shard_frames in candidates:
        target_auth_payload, _target_auth_status = resolve_auth_payload(
            list(target_document.auth_frames),
            doc_id=target_document.doc_id,
            doc_hash=target_document.doc_hash,
            allow_unsigned=allow_unsigned,
            require_auth=not allow_unsigned,
            _notice_sink=lambda notice: _notice(
                _notice_sink,
                notice.code,
                notice.message,
                details=notice.details,
            ),
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
            doc_id=root_document.doc_id,
            doc_hash=root_document.doc_hash,
            allow_unsigned=allow_unsigned,
            require_auth=not allow_unsigned,
            _notice_sink=lambda notice: _notice(
                _notice_sink,
                notice.code,
                notice.message,
                details=notice.details,
            ),
        )
        _verify_shard_target_belongs_to_selected_root(
            target_document=target_document,
            root_document=root_document,
            passphrase=unlock.resolved_passphrase,
            root_auth_payload=root_auth_payload,
            decoded_import_session=decoded_import_session,
            allow_unsigned=allow_unsigned,
            quiet=quiet,
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
    quiet: bool,
) -> None:
    if (
        target_document.doc_id == root_document.doc_id
        and target_document.doc_hash == root_document.doc_hash
    ):
        return
    if root_auth_payload is None:
        if allow_unsigned:
            return
        raise ValueError("extension-local shard target requires verified root AUTH")
    try:
        decoded = decode_imported_extension_link(
            target_document,
            passphrase=passphrase,
            expected_sign_pub=root_auth_payload.sign_pub,
            quiet=quiet,
            debug=False,
            decoded_import_session=decoded_import_session,
        )
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
    notice_sink: RecoveryInspectionNoticeSink | None,
) -> tuple[AuthPayload | None, str, tuple[dict[str, Any], ...]]:
    if not auth_frames:
        if require_auth:
            return (
                None,
                "missing",
                (
                    _blocking_issue(
                        api_codes.AUTH_PAYLOAD_MISSING,
                        "missing AUTH payload; provide AUTH input to check readiness",
                    ),
                ),
            )
        if allow_unsigned:
            _notice(
                notice_sink,
                api_codes.AUTH_PAYLOAD_MISSING,
                "no auth payload provided; skipping auth verification",
            )
            return None, "skipped", ()
        return None, "missing", ()
    if len(auth_frames) > 1:
        return (
            None,
            "invalid",
            (_blocking_issue(api_codes.AUTH_PAYLOAD_MULTIPLE, "multiple auth payloads provided"),),
        )

    frame = auth_frames[0]
    if frame.doc_id != doc_id:
        if allow_unsigned:
            _notice(
                notice_sink,
                api_codes.AUTH_PAYLOAD_INVALID,
                "auth payload doc_id mismatch; verification skipped",
                details={"reason": "doc_id_mismatch"},
            )
            return None, "ignored", ()
        return (
            None,
            "invalid",
            (
                _blocking_issue(
                    api_codes.AUTH_PAYLOAD_DOC_ID_MISMATCH,
                    "auth payload doc_id does not match ciphertext",
                ),
            ),
        )
    if frame.total != 1 or frame.index != 0:
        return (
            None,
            "invalid",
            (
                _blocking_issue(
                    api_codes.AUTH_PAYLOAD_FRAME_INVALID,
                    "auth payload must be a single-frame payload",
                ),
            ),
        )

    try:
        payload = decode_auth_payload(frame.data)
    except ValueError as exc:
        if allow_unsigned:
            _notice(
                notice_sink,
                api_codes.AUTH_PAYLOAD_INVALID,
                f"invalid auth payload; verification skipped: {exc}",
                details={"reason": str(exc)},
            )
            return None, "invalid", ()
        return (
            None,
            "invalid",
            (
                _blocking_issue(
                    api_codes.AUTH_PAYLOAD_INVALID,
                    f"invalid auth payload: {exc}",
                    details={"reason": str(exc)},
                ),
            ),
        )
    if payload.doc_hash != doc_hash:
        if allow_unsigned:
            _notice(
                notice_sink,
                api_codes.AUTH_DOC_HASH_MISMATCH,
                "auth doc_hash mismatch; verification skipped",
            )
            return None, "ignored", ()
        return (
            None,
            "ignored",
            (
                _blocking_issue(
                    api_codes.AUTH_DOC_HASH_MISMATCH,
                    "auth doc_hash does not match ciphertext",
                ),
            ),
        )
    if not verify_auth(doc_hash, sign_pub=payload.sign_pub, signature=payload.signature):
        if allow_unsigned:
            _notice(
                notice_sink,
                api_codes.AUTH_SIGNATURE_INVALID,
                "auth signature verification failed; verification skipped",
            )
            return None, "ignored", ()
        return (
            None,
            "ignored",
            (
                _blocking_issue(
                    api_codes.AUTH_SIGNATURE_INVALID,
                    "invalid auth signature",
                ),
            ),
        )
    return payload, "verified", ()


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
            shard_payloads = validated_shard_payloads_from_frames(
                shard_frames,
                expected_doc_id=doc_id,
                expected_doc_hash=doc_hash,
                expected_sign_pub=sign_pub,
                allow_unsigned=allow_unsigned,
                key_type=KEY_TYPE_PASSPHRASE,
                secret_label="passphrase",
            )
        except InsufficientShardError as exc:
            return RecoveryUnlockStatus(
                mode="shards",
                passphrase_provided=False,
                validated_shard_count=exc.provided_count,
                required_shard_threshold=exc.threshold,
                satisfied=False,
                shard_share_count=exc.share_count,
                blocking_issues=(
                    _blocking_issue(
                        api_codes.PASSPHRASE_SHARDS_UNDER_QUORUM,
                        f"need at least {exc.threshold} shard(s) to recover passphrase",
                        details={
                            "provided_count": exc.provided_count,
                            "required_threshold": exc.threshold,
                        },
                    ),
                ),
            )
        except ValueError as exc:
            return RecoveryUnlockStatus(
                mode="shards",
                passphrase_provided=False,
                validated_shard_count=0,
                required_shard_threshold=None,
                satisfied=False,
                blocking_issues=(_blocking_issue(api_codes.PASSPHRASE_SHARDS_INVALID, str(exc)),),
            )
        recovered = passphrase_from_shard_frames(
            shard_frames,
            expected_doc_id=doc_id,
            expected_doc_hash=doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=allow_unsigned,
        )
        return RecoveryUnlockStatus(
            mode="shards",
            passphrase_provided=False,
            validated_shard_count=len(shard_payloads),
            required_shard_threshold=shard_payloads[0].threshold if shard_payloads else None,
            satisfied=True,
            resolved_passphrase=recovered,
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
    return RecoveryUnlockStatus(
        mode="missing",
        passphrase_provided=False,
        validated_shard_count=0,
        required_shard_threshold=None,
        satisfied=False,
        blocking_issues=(
            _blocking_issue(
                api_codes.PASSPHRASE_REQUIRED,
                "passphrase or passphrase shard inputs are required to decrypt this backup",
            ),
        ),
    )


def _blocking_issue(
    code: str,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    return {"code": code, "message": message, "details": dict(details or {})}


def _notice(
    sink: RecoveryInspectionNoticeSink | None,
    code: str,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> None:
    if sink is not None:
        sink(RecoveryInspectionNotice(code=code, message=message, details=dict(details or {})))


__all__ = [
    "RecoveryInspectionNotice",
    "RecoveryInspectionNoticeSink",
    "inspect_recovery_inputs",
    "select_root_import_document_from_passphrase_shards",
]
