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

"""Build validated recovery execution plans from CLI inputs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ethernity.cli.features.recover import inputs as recover_inputs
from ethernity.cli.features.recover.constants import RECOVERY_SCAN_LABEL
from ethernity.cli.features.recover.key_recovery import (
    InsufficientShardError,
    passphrase_from_shard_frames,
    resolve_auth_payload,
    resolve_recovery_keys,
    validated_shard_payloads_from_frames,
)
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.inspection import blocking_issue
from ethernity.cli.shared.log import warn
from ethernity.cli.shared.paths import expanduser_cli_path
from ethernity.cli.shared.types import RecoverArgs
from ethernity.config import load_app_config
from ethernity.crypto.document_identity import (
    doc_id_and_hash_from_ciphertext,
    normalize_doc_hash_hex,
)
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
    imported_documents_from_recovery_frames,
    select_root_import_document,
    select_root_import_session,
)
from ethernity.workflows.recovery.inspection import (
    RecoveryInspectionNotice,
    inspect_recovery_inputs as _inspect_recovery_inputs,
    select_root_import_document_from_passphrase_shards as _select_root_from_shards,
)
from ethernity.workflows.recovery.models import (
    PassphraseShardRootSelection,
    RecoveryInspection,
    RecoveryUnlockStatus,
)


@dataclass(frozen=True)
class RecoveryPlan:
    """Resolved recovery inputs, verification state, and output preferences."""

    ciphertext: bytes
    doc_id: bytes
    doc_hash: bytes
    passphrase: str
    auth_payload: AuthPayload | None
    auth_status: str
    allow_unsigned: bool
    output_path: str | None
    input_label: str | None
    input_detail: str | None
    main_frames: tuple[Frame, ...]
    auth_frames: tuple[Frame, ...]
    shard_frames: tuple[Frame, ...]
    shard_fallback_files: tuple[str, ...]
    shard_payloads_file: tuple[str, ...]
    shard_scan: tuple[str, ...]
    resource_intensive_compatibility_recovery: bool = False
    root_dir: str | None = None
    extension_index: int | None = None
    extension_doc_hash: str | None = None
    expected_head_doc_hash: str | None = None
    import_documents: tuple[ImportedRecoveryDocument, ...] = ()
    decoded_import_session: DecodedImportSession | None = None


def resolve_recover_config(args: RecoverArgs) -> object:
    """Load recovery-related config to validate config/paper inputs early."""

    config = load_app_config(args.config, paper_size=args.paper)
    return config


def validate_recover_args(args: RecoverArgs) -> None:
    """Validate mutually exclusive recovery input flags."""

    if args.fallback_file and args.payloads_file:
        raise ValueError("use either --fallback-file or --payloads-file, not both")
    if args.auth_fallback_file and args.auth_payloads_file:
        raise ValueError("use either --auth-fallback-file or --auth-payloads-file, not both")
    if args.extension_index is not None and args.extension_doc_hash is not None:
        raise ValueError("use either --extension-index or --extension-doc-hash, not both")
    if args.extension_doc_hash is not None:
        args.extension_doc_hash = normalize_doc_hash_hex(
            args.extension_doc_hash,
            option="--extension-doc-hash",
        )
    if args.expected_head_doc_hash is not None:
        args.expected_head_doc_hash = normalize_doc_hash_hex(
            args.expected_head_doc_hash,
            option="--expected-head-doc-hash",
        )


def inspect_from_args(args: RecoverArgs) -> RecoveryInspection:
    """Build a best-effort recovery inspection directly from CLI arguments."""

    validate_recover_args(args)
    resolve_recover_config(args)
    allow_unsigned = args.allow_unsigned
    quiet = args.quiet

    frames, input_label, input_detail, _root_dir = recover_inputs.load_recovery_frames(
        args,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
    )
    extra_auth_frames = recover_inputs.load_extra_auth_frames(
        args,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
    )
    shard_frames, shard_fallback_files, shard_payloads_file, shard_scan = (
        recover_inputs.load_shard_frames(
            args,
            quiet=quiet,
        )
    )
    source_frames = tuple(frames)
    source_extra_auth_frames = tuple(extra_auth_frames)
    import_documents = _import_documents_from_recovery_inputs(
        frames,
        extra_auth_frames,
        source_label=input_detail or input_label or "content import",
    )
    import_shard_unlock: RecoveryUnlockStatus | None = None
    if len(import_documents) > 1:
        if args.passphrase:
            try:
                root_document = select_root_import_document(
                    import_documents,
                    passphrase=args.passphrase,
                    debug=False,
                )
            except Exception as exc:
                return _inspect_unselected_import_documents(
                    import_documents=import_documents,
                    frames=frames,
                    extra_auth_frames=extra_auth_frames,
                    shard_frames=shard_frames,
                    allow_unsigned=allow_unsigned,
                    input_label=input_label,
                    input_detail=input_detail,
                    shard_fallback_files=shard_fallback_files,
                    shard_payloads_file=shard_payloads_file,
                    shard_scan=shard_scan,
                    unlock=_import_root_selection_passphrase_failure(
                        str(exc),
                        import_documents=import_documents,
                    ),
                )
        elif shard_frames:
            try:
                selection = select_root_import_document_from_passphrase_shards(
                    import_documents,
                    shard_frames=shard_frames,
                    allow_unsigned=allow_unsigned,
                    quiet=quiet,
                )
                root_document = selection.root_document
                import_shard_unlock = selection.unlock
            except Exception as exc:
                return _inspect_unselected_import_documents(
                    import_documents=import_documents,
                    frames=frames,
                    extra_auth_frames=extra_auth_frames,
                    shard_frames=shard_frames,
                    allow_unsigned=allow_unsigned,
                    input_label=input_label,
                    input_detail=input_detail,
                    shard_fallback_files=shard_fallback_files,
                    shard_payloads_file=shard_payloads_file,
                    shard_scan=shard_scan,
                    unlock=_import_root_selection_shard_failure(
                        str(exc),
                        import_documents=import_documents,
                    ),
                )
        else:
            return _inspect_unselected_import_documents(
                import_documents=import_documents,
                frames=frames,
                extra_auth_frames=extra_auth_frames,
                shard_frames=shard_frames,
                allow_unsigned=allow_unsigned,
                input_label=input_label,
                input_detail=input_detail,
                shard_fallback_files=shard_fallback_files,
                shard_payloads_file=shard_payloads_file,
                shard_scan=shard_scan,
                unlock=_import_root_selection_missing_unlock(import_documents=import_documents),
            )
        frames = [frame for frame in frames if frame.doc_id == root_document.doc_id]
        extra_auth_frames = [
            frame for frame in extra_auth_frames if frame.doc_id == root_document.doc_id
        ]
    if import_shard_unlock is not None:
        inspection = inspect_recovery_inputs(
            frames=frames,
            extra_auth_frames=extra_auth_frames,
            shard_frames=[],
            passphrase=import_shard_unlock.resolved_passphrase,
            allow_unsigned=allow_unsigned,
            input_label=input_label,
            input_detail=input_detail,
            shard_fallback_files=[],
            shard_payloads_file=[],
            shard_scan=[],
            quiet=quiet,
        )
        unlock = import_shard_unlock
        if not inspection.unlock.satisfied:
            unlock = replace(unlock, satisfied=False, resolved_passphrase=None)
        return replace(
            inspection,
            unlock=unlock,
            shard_frames=tuple(shard_frames),
            shard_fallback_files=tuple(shard_fallback_files),
            shard_payloads_file=tuple(shard_payloads_file),
            shard_scan=tuple(shard_scan),
            source_frames=source_frames,
            source_extra_auth_frames=source_extra_auth_frames,
        )
    inspection = inspect_recovery_inputs(
        frames=frames,
        extra_auth_frames=extra_auth_frames,
        shard_frames=shard_frames,
        passphrase=args.passphrase,
        allow_unsigned=allow_unsigned,
        input_label=input_label,
        input_detail=input_detail,
        shard_fallback_files=shard_fallback_files,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        quiet=quiet,
    )
    return replace(
        inspection,
        source_frames=source_frames,
        source_extra_auth_frames=source_extra_auth_frames,
    )


def plan_from_args(args: RecoverArgs) -> RecoveryPlan:
    """Build a full recovery plan directly from CLI arguments."""

    validate_recover_args(args)
    resolve_recover_config(args)
    allow_unsigned = args.allow_unsigned
    quiet = args.quiet

    frames, input_label, input_detail, _root_dir = recover_inputs.load_recovery_frames(
        args,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
    )
    extra_auth_frames = recover_inputs.load_extra_auth_frames(
        args,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
    )
    shard_frames, shard_fallback_files, shard_payloads_file, shard_scan = (
        recover_inputs.load_shard_frames(
            args,
            quiet=quiet,
        )
    )
    return build_recovery_plan(
        frames=frames,
        extra_auth_frames=extra_auth_frames,
        shard_frames=shard_frames,
        passphrase=args.passphrase,
        allow_unsigned=allow_unsigned,
        input_label=input_label,
        input_detail=input_detail,
        shard_fallback_files=shard_fallback_files,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        output_path=expanduser_cli_path(args.output),
        root_dir=None,
        extension_index=args.extension_index,
        extension_doc_hash=args.extension_doc_hash,
        expected_head_doc_hash=args.expected_head_doc_hash,
        args=args,
        quiet=quiet,
    )


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
) -> RecoveryInspection:
    """Compatibility adapter for workflow-owned recovery inspection."""

    return _inspect_recovery_inputs(
        frames=frames,
        extra_auth_frames=extra_auth_frames,
        shard_frames=shard_frames,
        passphrase=passphrase,
        allow_unsigned=allow_unsigned,
        input_label=input_label,
        input_detail=input_detail,
        shard_fallback_files=shard_fallback_files,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        quiet=quiet,
        _notice_sink=lambda notice: _warn_inspection_notice(notice, quiet=quiet),
    )


def _warn_inspection_notice(notice: RecoveryInspectionNotice, *, quiet: bool) -> None:
    warn(notice.message, quiet=quiet, code=notice.code, details=notice.details)


def build_recovery_plan(
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
    output_path: str | None,
    root_dir: str | None,
    extension_index: int | None,
    extension_doc_hash: str | None,
    expected_head_doc_hash: str | None,
    args: RecoverArgs | None,
    quiet: bool,
) -> RecoveryPlan:
    """Assemble a validated recovery plan from decoded frames and key inputs."""

    if not frames:
        hint = "Check the input path and try again."
        if input_label == RECOVERY_SCAN_LABEL:
            hint = "Check the scan path and image quality, then try again."
        raise ValueError(f"no backup data found. {hint}")

    import_documents = _import_documents_from_recovery_inputs(
        frames,
        extra_auth_frames,
        source_label=input_detail or input_label or "content import",
    )
    if len(import_documents) > 1:
        import_shard_unlock: RecoveryUnlockStatus | None = None
        import_passphrase: str | None = None
        decoded_import_session: DecodedImportSession | None = None
        if passphrase:
            import_passphrase = passphrase
            decoded_import_session = select_root_import_session(
                import_documents,
                passphrase=import_passphrase,
                debug=False,
            )
            root_document = decoded_import_session.root_document
        elif shard_frames:
            selection = select_root_import_document_from_passphrase_shards(
                import_documents,
                shard_frames=shard_frames,
                allow_unsigned=allow_unsigned,
                quiet=quiet,
            )
            root_document = selection.root_document
            import_shard_unlock = selection.unlock
            decoded_import_session = getattr(selection, "decoded_import_session", None)
        elif args is not None:
            import_passphrase = _resolve_recovery_passphrase_from_args(args)
            decoded_import_session = select_root_import_session(
                import_documents,
                passphrase=import_passphrase,
                debug=False,
            )
            root_document = decoded_import_session.root_document
        else:
            raise ValueError(
                "passphrase is required when recovery input contains multiple MAIN documents"
            )
        if import_shard_unlock is None:
            recursive_passphrase = import_passphrase or passphrase
        else:
            recursive_passphrase = import_shard_unlock.resolved_passphrase
        recursive_shard_frames = [] if import_shard_unlock is not None else shard_frames
        root_frames = [frame for frame in frames if frame.doc_id == root_document.doc_id]
        root_extra_auth_frames = [
            frame for frame in extra_auth_frames if frame.doc_id == root_document.doc_id
        ]
        root_plan = build_recovery_plan(
            frames=root_frames,
            extra_auth_frames=root_extra_auth_frames,
            shard_frames=recursive_shard_frames,
            passphrase=recursive_passphrase,
            allow_unsigned=allow_unsigned,
            input_label=input_label,
            input_detail=input_detail,
            shard_fallback_files=[] if import_shard_unlock is not None else shard_fallback_files,
            shard_payloads_file=[] if import_shard_unlock is not None else shard_payloads_file,
            shard_scan=[] if import_shard_unlock is not None else shard_scan,
            output_path=output_path,
            root_dir=root_dir,
            extension_index=extension_index,
            extension_doc_hash=extension_doc_hash,
            expected_head_doc_hash=expected_head_doc_hash,
            args=args,
            quiet=quiet,
        )
        if import_shard_unlock is None:
            return replace(
                root_plan,
                import_documents=import_documents,
                decoded_import_session=decoded_import_session,
            )
        return replace(
            root_plan,
            import_documents=import_documents,
            decoded_import_session=decoded_import_session,
            shard_frames=tuple(shard_frames),
            shard_fallback_files=tuple(shard_fallback_files),
            shard_payloads_file=tuple(shard_payloads_file),
            shard_scan=tuple(shard_scan),
        )

    deduped = deduplicate_frame_slots(frames)
    main_frames, auth_frames = split_main_and_auth_frames(deduped)
    if extra_auth_frames:
        auth_frames = deduplicate_auth_frames([*auth_frames, *extra_auth_frames])

    ciphertext = reassemble_payload(main_frames, expected_frame_type=FrameType.MAIN_DOCUMENT)
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)

    auth_payload, auth_status = resolve_auth_payload(
        auth_frames,
        doc_id=doc_id,
        doc_hash=doc_hash,
        allow_unsigned=allow_unsigned,
        require_auth=not allow_unsigned,
        quiet=quiet,
    )
    sign_pub = auth_payload.sign_pub if auth_payload else None
    resolved_passphrase = _resolve_passphrase(
        passphrase=passphrase,
        shard_frames=shard_frames,
        doc_id=doc_id,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        allow_unsigned=allow_unsigned,
        args=args,
    )

    return RecoveryPlan(
        ciphertext=ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
        passphrase=resolved_passphrase,
        auth_payload=auth_payload,
        auth_status=auth_status,
        allow_unsigned=allow_unsigned,
        output_path=output_path,
        input_label=input_label,
        input_detail=input_detail,
        main_frames=tuple(main_frames),
        auth_frames=tuple(auth_frames),
        shard_frames=tuple(shard_frames),
        shard_fallback_files=tuple(shard_fallback_files),
        shard_payloads_file=tuple(shard_payloads_file),
        shard_scan=tuple(shard_scan),
        resource_intensive_compatibility_recovery=(
            args.resource_intensive_compatibility_recovery if args is not None else False
        ),
        root_dir=root_dir,
        extension_index=extension_index,
        extension_doc_hash=extension_doc_hash,
        expected_head_doc_hash=expected_head_doc_hash,
        import_documents=import_documents,
    )


def _import_documents_from_recovery_inputs(
    frames: list[Frame],
    extra_auth_frames: list[Frame],
    *,
    source_label: str,
) -> tuple[ImportedRecoveryDocument, ...]:
    try:
        return imported_documents_from_recovery_frames(
            [*frames, *extra_auth_frames],
            source_label=source_label,
        )
    except ValueError as exc:
        if "AUTH frame(s) without matching MAIN" not in str(exc):
            raise
        import_documents = imported_documents_from_recovery_frames(
            frames,
            source_label=source_label,
        )
        if len(import_documents) > 1:
            raise
        return import_documents


def select_root_import_document_from_passphrase_shards(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    shard_frames: list[Frame],
    allow_unsigned: bool,
    quiet: bool,
) -> PassphraseShardRootSelection:
    """Compatibility adapter for workflow-owned imported-root selection."""

    return _select_root_from_shards(
        documents,
        shard_frames=shard_frames,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
        _notice_sink=lambda notice: _warn_inspection_notice(notice, quiet=quiet),
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


def _inspect_unselected_import_documents(
    *,
    import_documents: tuple[ImportedRecoveryDocument, ...],
    frames: list[Frame],
    extra_auth_frames: list[Frame],
    shard_frames: list[Frame],
    allow_unsigned: bool,
    input_label: str | None,
    input_detail: str | None,
    shard_fallback_files: list[str],
    shard_payloads_file: list[str],
    shard_scan: list[str],
    unlock: RecoveryUnlockStatus,
) -> RecoveryInspection:
    candidate = import_documents[0]
    deduped = deduplicate_frame_slots([*frames, *extra_auth_frames])
    main_frames, auth_frames = split_main_and_auth_frames(deduped)
    auth_status = _ambiguous_import_auth_status(auth_frames, allow_unsigned=allow_unsigned)
    blocking_issues = [
        *_ambiguous_import_auth_blockers(auth_frames, allow_unsigned=allow_unsigned),
        *unlock.blocking_issues,
    ]
    return RecoveryInspection(
        ciphertext=candidate.ciphertext,
        doc_id=candidate.doc_id,
        doc_hash=candidate.doc_hash,
        auth_payload=None,
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


def _ambiguous_import_auth_status(auth_frames: list[Frame], *, allow_unsigned: bool) -> str:
    if auth_frames:
        return "ignored"
    if allow_unsigned:
        return "skipped"
    return "missing"


def _ambiguous_import_auth_blockers(
    auth_frames: list[Frame],
    *,
    allow_unsigned: bool,
) -> tuple[dict[str, Any], ...]:
    if auth_frames or allow_unsigned:
        return ()
    return (
        blocking_issue(
            api_codes.AUTH_PAYLOAD_MISSING,
            "missing AUTH payload; provide AUTH input to check readiness",
        ),
    )


def _import_root_selection_missing_unlock(
    *,
    import_documents: tuple[ImportedRecoveryDocument, ...],
) -> RecoveryUnlockStatus:
    return RecoveryUnlockStatus(
        mode="missing",
        passphrase_provided=False,
        validated_shard_count=0,
        required_shard_threshold=None,
        satisfied=False,
        blocking_issues=(
            _import_root_selection_blocker(
                "PASSPHRASE_REQUIRED",
                "passphrase or passphrase shard inputs are required to select the root backup",
                import_documents=import_documents,
            ),
        ),
    )


def _import_root_selection_passphrase_failure(
    message: str,
    *,
    import_documents: tuple[ImportedRecoveryDocument, ...],
) -> RecoveryUnlockStatus:
    return RecoveryUnlockStatus(
        mode="passphrase",
        passphrase_provided=True,
        validated_shard_count=0,
        required_shard_threshold=None,
        satisfied=False,
        blocking_issues=(
            _import_root_selection_blocker(
                "UNLOCK_FAILED",
                f"provided passphrase could not select a root backup: {message}",
                import_documents=import_documents,
            ),
        ),
    )


def _import_root_selection_shard_failure(
    message: str,
    *,
    import_documents: tuple[ImportedRecoveryDocument, ...],
) -> RecoveryUnlockStatus:
    return RecoveryUnlockStatus(
        mode="shards",
        passphrase_provided=False,
        validated_shard_count=0,
        required_shard_threshold=None,
        satisfied=False,
        blocking_issues=(
            _import_root_selection_blocker(
                "PASSPHRASE_SHARDS_INVALID",
                f"passphrase shard inputs could not select a root backup: {message}",
                import_documents=import_documents,
            ),
        ),
    )


def _import_root_selection_blocker(
    code: str,
    message: str,
    *,
    import_documents: tuple[ImportedRecoveryDocument, ...],
) -> dict[str, Any]:
    return blocking_issue(
        code,
        message,
        details={
            "stage": "root_selection",
            "main_document_count": len(import_documents),
            "candidate_doc_ids": [document.doc_id.hex() for document in import_documents],
        },
    )


def _inspect_auth_payload(
    auth_frames: list[Frame],
    *,
    doc_id: bytes,
    doc_hash: bytes,
    allow_unsigned: bool,
    require_auth: bool,
    quiet: bool,
) -> tuple[AuthPayload | None, str, tuple[dict[str, Any], ...]]:
    if not auth_frames:
        if require_auth:
            return (
                None,
                "missing",
                (
                    blocking_issue(
                        api_codes.AUTH_PAYLOAD_MISSING,
                        "missing AUTH payload; provide AUTH input to check readiness",
                    ),
                ),
            )
        if allow_unsigned:
            warn(
                "no auth payload provided; skipping auth verification",
                quiet=quiet,
                code=api_codes.AUTH_PAYLOAD_MISSING,
            )
            return None, "skipped", ()
        return None, "missing", ()
    if len(auth_frames) > 1:
        return (
            None,
            "invalid",
            (blocking_issue("AUTH_PAYLOAD_MULTIPLE", "multiple auth payloads provided"),),
        )

    frame = auth_frames[0]
    if frame.doc_id != doc_id:
        if allow_unsigned:
            warn(
                "auth payload doc_id mismatch; verification skipped",
                quiet=quiet,
                code=api_codes.AUTH_PAYLOAD_INVALID,
                details={"reason": "doc_id_mismatch"},
            )
            return None, "ignored", ()
        return (
            None,
            "invalid",
            (
                blocking_issue(
                    "AUTH_PAYLOAD_DOC_ID_MISMATCH",
                    "auth payload doc_id does not match ciphertext",
                ),
            ),
        )
    if frame.total != 1 or frame.index != 0:
        return (
            None,
            "invalid",
            (
                blocking_issue(
                    "AUTH_PAYLOAD_FRAME_INVALID",
                    "auth payload must be a single-frame payload",
                ),
            ),
        )

    try:
        payload = decode_auth_payload(frame.data)
    except ValueError as exc:
        if allow_unsigned:
            warn(
                f"invalid auth payload; verification skipped: {exc}",
                quiet=quiet,
                code=api_codes.AUTH_PAYLOAD_INVALID,
                details={"reason": str(exc)},
            )
            return None, "invalid", ()
        return (
            None,
            "invalid",
            (
                blocking_issue(
                    api_codes.AUTH_PAYLOAD_INVALID,
                    f"invalid auth payload: {exc}",
                    details={"reason": str(exc)},
                ),
            ),
        )
    if payload.doc_hash != doc_hash:
        if allow_unsigned:
            warn(
                "auth doc_hash mismatch; verification skipped",
                quiet=quiet,
                code=api_codes.AUTH_DOC_HASH_MISMATCH,
            )
            return None, "ignored", ()
        return (
            None,
            "ignored",
            (
                blocking_issue(
                    api_codes.AUTH_DOC_HASH_MISMATCH,
                    "auth doc_hash does not match ciphertext",
                ),
            ),
        )
    if not verify_auth(doc_hash, sign_pub=payload.sign_pub, signature=payload.signature):
        if allow_unsigned:
            warn(
                "auth signature verification failed; verification skipped",
                quiet=quiet,
                code=api_codes.AUTH_SIGNATURE_INVALID,
            )
            return None, "ignored", ()
        return (
            None,
            "ignored",
            (
                blocking_issue(
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
                    blocking_issue(
                        "PASSPHRASE_SHARDS_UNDER_QUORUM",
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
                blocking_issues=(
                    blocking_issue(
                        "PASSPHRASE_SHARDS_INVALID",
                        str(exc),
                    ),
                ),
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
            blocking_issue(
                "PASSPHRASE_REQUIRED",
                "passphrase or passphrase shard inputs are required to decrypt this backup",
            ),
        ),
    )


def _resolve_passphrase(
    *,
    passphrase: str | None,
    shard_frames: list[Frame],
    doc_id: bytes,
    doc_hash: bytes,
    sign_pub: bytes | None,
    allow_unsigned: bool,
    args: RecoverArgs | None,
) -> str:
    """Resolve the recovery passphrase from direct input, shards, or arg-driven prompts."""

    if shard_frames and passphrase:
        raise ValueError("use either shard inputs or passphrase, not both")
    if shard_frames:
        recovered = passphrase_from_shard_frames(
            shard_frames,
            expected_doc_id=doc_id,
            expected_doc_hash=doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=allow_unsigned,
        )
        return recovered
    if passphrase:
        return passphrase
    if args is not None:
        return _resolve_recovery_passphrase_from_args(args)
    raise ValueError("passphrase is required for recovery")


def _resolve_recovery_passphrase_from_args(args: RecoverArgs) -> str:
    return resolve_recovery_keys(args)
