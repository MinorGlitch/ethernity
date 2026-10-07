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

"""Inspect recovery inputs and build strict execution plans from workflow requests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ethernity.config import load_app_config
from ethernity.crypto.age_policy import RecoveryResourceLimitError
from ethernity.crypto.document_identity import normalize_doc_hash_hex
from ethernity.crypto.signing import AuthPayload
from ethernity.encoding.frame_sets import (
    deduplicate_frame_slots,
    split_main_and_auth_frames,
)
from ethernity.encoding.framing import Frame
from ethernity.extensions.recovery import (
    DecodedImportSession,
    ImportedRecoveryDocument,
)
from ethernity.workflows.recovery import inputs as recover_inputs, root_selection
from ethernity.workflows.recovery.inspection import (
    inspect_recovery_inputs as _inspect_recovery_inputs,
)
from ethernity.workflows.recovery.keys import (
    RecoveryTrust,
    passphrase_from_shard_frames,
    resolve_auth_payload as _resolve_auth_payload,
)
from ethernity.workflows.recovery.models import (
    RecoveryDocumentState,
    RecoveryInspection,
    RecoveryUnlockStatus,
)
from ethernity.workflows.recovery.source_state import (
    assemble_recovery_document,
    recovery_source_fields,
    require_recovery_frames,
)
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.events import emit_phase
from ethernity.workflows.shared.inspection import blocking_issue
from ethernity.workflows.shared.notices import WorkflowNotice, warn
from ethernity.workflows.shared.paths import expanduser_cli_path
from ethernity.workflows.shared.requests import RecoveryRequest


@dataclass(frozen=True)
class RecoveryPlan(RecoveryDocumentState):
    """Resolved recovery inputs, verification state, and output preferences."""

    passphrase: str
    output_path: str | None
    extension_index: int | None = None
    extension_doc_hash: str | None = None
    expected_head_doc_hash: str | None = None
    import_documents: tuple[ImportedRecoveryDocument, ...] = ()
    decoded_import_session: DecodedImportSession | None = None


def resolve_recover_config(args: RecoveryRequest) -> object:
    """Load recovery-related config to validate config/paper inputs early."""

    emit_phase(phase="configuration", label="Resolving recovery configuration")
    config = load_app_config(args.config_path, paper_size=args.paper_size)
    return config


def normalize_recovery_request(args: RecoveryRequest) -> RecoveryRequest:
    """Validate recovery inputs and normalize fingerprints without mutating the request."""

    if args.auth_text_file and args.auth_payloads_file:
        raise ValueError("use either --auth-fallback-file or --auth-payloads-file, not both")
    if args.extension_index is not None and args.extension_doc_hash is not None:
        raise ValueError("use either --extension-index or --extension-doc-hash, not both")
    extension_doc_hash = args.extension_doc_hash
    expected_head_doc_hash = args.expected_head_doc_hash
    if extension_doc_hash is not None:
        extension_doc_hash = normalize_doc_hash_hex(
            extension_doc_hash,
            option="--extension-doc-hash",
        )
    if expected_head_doc_hash is not None:
        expected_head_doc_hash = normalize_doc_hash_hex(
            expected_head_doc_hash,
            option="expected latest backup fingerprint",
        )
    if (extension_doc_hash, expected_head_doc_hash) == (
        args.extension_doc_hash,
        args.expected_head_doc_hash,
    ):
        return args
    return replace(
        args,
        extension_doc_hash=extension_doc_hash,
        expected_head_doc_hash=expected_head_doc_hash,
    )


def inspect_from_request(args: RecoveryRequest) -> RecoveryInspection:
    """Build a best-effort recovery inspection from the workflow request."""

    args = normalize_recovery_request(args)
    resolve_recover_config(args)
    allow_unsigned = args.allow_unsigned
    quiet = args.quiet

    frames, input_label, input_detail = recover_inputs.load_recovery_frames(
        args,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
        include_recovery_sheets=True,
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
    frames, shard_frames = recover_inputs.route_document_frames(
        frames, shard_frames, passphrase=args.passphrase
    )
    source_frames = tuple(frames)
    source_extra_auth_frames = tuple(extra_auth_frames)
    import_documents = root_selection.import_recovery_documents(
        frames,
        extra_auth_frames,
        source_label=input_detail or input_label or "content import",
    )
    try:
        selection = root_selection.select_recovery_root(
            import_documents,
            frames=frames,
            extra_auth_frames=extra_auth_frames,
            shard_frames=shard_frames,
            passphrase=args.passphrase,
            allow_unsigned=allow_unsigned,
            notice_sink=lambda notice: _warn_notice(notice, quiet=quiet),
        )
    except RecoveryResourceLimitError:
        raise
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
            unlock=_root_selection_failure(
                passphrase=args.passphrase,
                shard_frames=shard_frames,
                message=str(exc),
                import_documents=import_documents,
            ),
        )

    inspection = inspect_recovery_inputs(
        frames=list(selection.frames),
        extra_auth_frames=list(selection.extra_auth_frames),
        shard_frames=list(selection.shard_frames),
        passphrase=selection.passphrase,
        allow_unsigned=allow_unsigned,
        input_label=input_label,
        input_detail=input_detail,
        shard_fallback_files=shard_fallback_files,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        quiet=quiet,
    )
    unlock = selection.shard_unlock or inspection.unlock
    if not inspection.unlock.satisfied:
        unlock = replace(unlock, satisfied=False, resolved_passphrase=None)
    return replace(
        inspection,
        unlock=unlock,
        source_frames=source_frames,
        source_extra_auth_frames=source_extra_auth_frames,
        decoded_import_session=selection.decoded_import_session,
        source=inspection.source.with_shards(
            shard_frames, shard_fallback_files, shard_payloads_file, shard_scan
        ),
    )


def plan_from_request(args: RecoveryRequest) -> RecoveryPlan:
    """Build a full recovery plan from the workflow request."""

    args = normalize_recovery_request(args)
    resolve_recover_config(args)
    allow_unsigned = args.allow_unsigned
    quiet = args.quiet

    frames, input_label, input_detail = recover_inputs.load_recovery_frames(
        args,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
        include_recovery_sheets=True,
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
        output_path=expanduser_cli_path(args.output_path),
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
    """Inspect recovery inputs while forwarding workflow notices."""

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
        _notice_sink=lambda notice: _warn_notice(notice, quiet=quiet),
    )


def _warn_notice(notice: WorkflowNotice, *, quiet: bool) -> None:
    warn(notice.message, quiet=quiet, code=notice.code, details=notice.details)


def _resolve_auth_payload_with_notices(
    auth_frames: list[Frame],
    *,
    doc_id: bytes,
    doc_hash: bytes,
    allow_unsigned: bool,
    require_auth: bool,
    quiet: bool,
) -> tuple[AuthPayload | None, str]:
    return _resolve_auth_payload(
        auth_frames,
        **RecoveryTrust(doc_id, doc_hash, allow_unsigned=allow_unsigned).auth_options(
            require_auth=require_auth
        ),
        _notice_sink=lambda notice: _warn_notice(notice, quiet=quiet),
    )


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
    extension_index: int | None,
    extension_doc_hash: str | None,
    expected_head_doc_hash: str | None,
    args: RecoveryRequest | None,
    quiet: bool,
) -> RecoveryPlan:
    """Assemble a validated recovery plan from decoded frames and key inputs."""

    frames, shard_frames = recover_inputs.route_document_frames(
        frames, shard_frames, passphrase=passphrase
    )
    require_recovery_frames(frames, input_label)

    import_documents = root_selection.import_recovery_documents(
        frames,
        extra_auth_frames,
        source_label=input_detail or input_label or "content import",
    )
    selection = root_selection.select_recovery_root(
        import_documents,
        frames=frames,
        extra_auth_frames=extra_auth_frames,
        shard_frames=shard_frames,
        passphrase=passphrase,
        allow_unsigned=allow_unsigned,
        passphrase_fallback=(
            (lambda: _resolve_recovery_passphrase_from_args(args)) if args is not None else None
        ),
        notice_sink=lambda notice: _warn_notice(notice, quiet=quiet),
    )

    emit_phase(phase="source", label="Assembling backup documents")
    document = assemble_recovery_document(
        selection.frames,
        selection.extra_auth_frames,
        input_label=input_label,
        input_detail=input_detail,
    )
    auth_frames = list(document.source.auth_frames)
    doc_id, doc_hash = document.doc_id, document.doc_hash

    emit_phase(phase="authentication", label="Checking backup signature")
    auth_payload, auth_status = _resolve_auth_payload_with_notices(
        auth_frames,
        **RecoveryTrust(doc_id, doc_hash, allow_unsigned=allow_unsigned).auth_options(
            require_auth=not allow_unsigned
        ),
        quiet=quiet,
    )
    sign_pub = auth_payload.sign_pub if auth_payload else None
    emit_phase(phase="unlock", label="Resolving recovery passphrase")
    resolved_passphrase = _resolve_passphrase(
        passphrase=selection.passphrase,
        shard_frames=list(selection.shard_frames),
        doc_id=doc_id,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        allow_unsigned=allow_unsigned,
        args=args,
    )

    return RecoveryPlan(
        ciphertext=document.ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
        passphrase=resolved_passphrase,
        auth_payload=auth_payload,
        auth_status=auth_status,
        allow_unsigned=allow_unsigned,
        output_path=output_path,
        extension_index=extension_index,
        extension_doc_hash=extension_doc_hash,
        expected_head_doc_hash=expected_head_doc_hash,
        import_documents=import_documents,
        decoded_import_session=selection.decoded_import_session,
        source=document.source.with_shards(
            shard_frames, shard_fallback_files, shard_payloads_file, shard_scan
        ),
    )


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
        unlock=unlock,
        blocking_issues=tuple(blocking_issues),
        source_frames=tuple(frames),
        source_extra_auth_frames=tuple(extra_auth_frames),
        source=recovery_source_fields(
            input_label,
            input_detail,
            main_frames,
            auth_frames,
            shard_frames,
            shard_fallback_files,
            shard_payloads_file,
            shard_scan,
        ),
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
            issue_codes.AUTH_PAYLOAD_MISSING,
            "missing AUTH payload; provide AUTH input to check readiness",
        ),
    )


def _root_selection_failure(
    *,
    passphrase: str | None,
    shard_frames: list[Frame],
    message: str,
    import_documents: tuple[ImportedRecoveryDocument, ...],
) -> RecoveryUnlockStatus:
    if passphrase:
        mode = "passphrase"
        code = "UNLOCK_FAILED"
        detail = f"provided passphrase could not select a root backup: {message}"
    elif shard_frames:
        mode = "shards"
        code = issue_codes.PASSPHRASE_SHARDS_INVALID
        detail = f"passphrase shard inputs could not select a root backup: {message}"
    else:
        mode = "missing"
        code = issue_codes.PASSPHRASE_REQUIRED
        detail = "passphrase or passphrase shard inputs are required to select the root backup"
    return RecoveryUnlockStatus.unavailable(
        mode,
        (_import_root_selection_blocker(code, detail, import_documents=import_documents),),
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


def _resolve_passphrase(
    *,
    passphrase: str | None,
    shard_frames: list[Frame],
    doc_id: bytes,
    doc_hash: bytes,
    sign_pub: bytes | None,
    allow_unsigned: bool,
    args: RecoveryRequest | None,
) -> str:
    """Resolve the recovery passphrase from direct input, shards, or the workflow request."""

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


def _resolve_recovery_passphrase_from_args(args: RecoveryRequest) -> str:
    if args.passphrase:
        return args.passphrase
    raise ValueError("passphrase is required for recovery")
