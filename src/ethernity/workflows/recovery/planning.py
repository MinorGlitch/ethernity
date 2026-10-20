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

from ethernity.config import load_app_config
from ethernity.crypto.age_policy import RecoveryResourceLimitError
from ethernity.crypto.document_identity import normalize_doc_hash_hex
from ethernity.encoding.frame_sets import (
    deduplicate_frame_slots,
    split_main_and_auth_frames,
)
from ethernity.encoding.framing import Frame
from ethernity.extensions.recovery import (
    ImportedRecoveryDocument,
)
from ethernity.workflows.recovery import inputs as recover_inputs, root_selection
from ethernity.workflows.recovery.inspection import inspect_document
from ethernity.workflows.recovery.models import (
    RecoveryInspection,
    RecoveryUnlockStatus,
)
from ethernity.workflows.recovery.session import RecoverySession
from ethernity.workflows.recovery.source_state import (
    LoadedRecoveryInputs,
    LoadedRecoverySource,
    recovery_source_fields,
    require_recovery_frames,
)
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.events import emit_phase
from ethernity.workflows.shared.inspection import BlockingIssue, blocking_issue
from ethernity.workflows.shared.notices import WorkflowNotice, warn
from ethernity.workflows.shared.paths import expanduser_cli_path
from ethernity.workflows.shared.requests import RecoveryRequest


@dataclass(frozen=True)
class RecoveryPlan(RecoveryInspection):
    """Resolved recovery inputs, verification state, and output preferences."""

    output_path: str | None = None
    extension_index: int | None = None
    extension_doc_hash: str | None = None
    expected_head_doc_hash: str | None = None

    @property
    def import_documents(self) -> tuple[ImportedRecoveryDocument, ...]:
        return self.loaded_source.documents

    @property
    def passphrase(self) -> str:
        value = self.unlock.resolved_passphrase
        if value is None or not self.unlock.satisfied or self.blocking_issues:
            raise ValueError("Recovery plan is not ready to unlock the backup.")
        return value


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


def inspect_from_request(
    args: RecoveryRequest, *, session: RecoverySession | None = None
) -> RecoveryInspection:
    """Build a best-effort recovery inspection from the workflow request."""

    args = normalize_recovery_request(args)
    resolve_recover_config(args)
    session = session or RecoverySession()
    loaded = session.load(args)
    return inspect_loaded_recovery(loaded, args, session=session)


def inspect_loaded_recovery(
    loaded: LoadedRecoveryInputs,
    args: RecoveryRequest,
    *,
    strict: bool = False,
    session: RecoverySession | None = None,
) -> RecoveryInspection:
    """Select and authenticate decoded input once for inspection or execution."""
    session = session or RecoverySession()
    previous = session.prepared(loaded, args, strict=strict)
    if previous is not None:
        return previous
    allow_unsigned, quiet = args.allow_unsigned, args.quiet
    source = loaded.source
    input_label, input_detail = source.input_label, source.input_detail
    shard_fallback_files = list(loaded.shard_fallback_files)
    shard_payloads_file = list(loaded.shard_payload_files)
    shard_scan = list(loaded.shard_scan)
    frames, shard_frames = recover_inputs.route_document_frames(
        list(source.frames), list(loaded.shard_frames), passphrase=args.passphrase
    )
    extra_auth_frames = list(source.extra_auth_frames)
    require_recovery_frames(frames, input_label)
    import_documents = source.documents
    try:
        selection = root_selection.select_recovery_root(
            import_documents,
            shard_frames=shard_frames,
            passphrase=args.passphrase,
            allow_unsigned=allow_unsigned,
            notice_sink=lambda notice: _warn_notice(notice, quiet=quiet),
        )
    except RecoveryResourceLimitError:
        raise
    except Exception as exc:
        if strict:
            raise
        result = _inspect_unselected_import_documents(
            loaded_source=source,
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
        session.remember_preparation(loaded, args, result)
        return result

    root = (
        selection.decoded_import_session.root_document
        if selection.decoded_import_session is not None
        else source.documents[0]
    )
    inspection = inspect_document(
        source.assembled_root(root.doc_id),
        loaded_source=source,
        shard_frames=list(selection.shard_frames),
        passphrase=selection.passphrase,
        allow_unsigned=allow_unsigned,
        shard_fallback_files=shard_fallback_files,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        _notice_sink=lambda notice: _warn_notice(notice, quiet=quiet),
        strict=strict,
        authenticated=session.authenticated_document(
            source, root.doc_hash, allow_unsigned=allow_unsigned
        ),
    )
    unlock = selection.shard_unlock or inspection.unlock
    if not inspection.unlock.satisfied:
        unlock = replace(unlock, satisfied=False, resolved_passphrase=None)
    result = replace(
        inspection,
        unlock=unlock,
        decoded_import_session=selection.decoded_import_session,
        source=inspection.source.with_shards(
            shard_frames, shard_fallback_files, shard_payloads_file, shard_scan
        ),
    )
    session.remember_preparation(loaded, args, result)
    return result


def plan_from_request(
    args: RecoveryRequest, *, session: RecoverySession | None = None
) -> RecoveryPlan:
    """Build a full recovery plan from the workflow request."""
    args = normalize_recovery_request(args)
    resolve_recover_config(args)
    session = session or RecoverySession()
    loaded = session.load(args)
    return build_recovery_plan(loaded, args, session=session)


def _warn_notice(notice: WorkflowNotice, *, quiet: bool) -> None:
    warn(notice.message, quiet=quiet, code=notice.code, details=notice.details)


def build_recovery_plan(
    loaded: LoadedRecoveryInputs, args: RecoveryRequest, *, session: RecoverySession | None = None
) -> RecoveryPlan:
    inspection = inspect_loaded_recovery(loaded, args, strict=True, session=session)
    return plan_from_inspection(inspection, args)


def plan_from_inspection(inspection: RecoveryInspection, args: RecoveryRequest) -> RecoveryPlan:
    """Freeze verified preparation with the requested version and output choices."""
    if inspection.allow_unsigned != args.allow_unsigned:
        raise ValueError("Recovery authentication policy changed after preparation.")
    if inspection.blocking_issues or not inspection.unlock.satisfied:
        raise ValueError("Recovery inputs have not passed preparation.")
    if inspection.unlock.resolved_passphrase is None:
        raise ValueError("Recovery preparation is missing the passphrase.")
    return RecoveryPlan(
        ciphertext=inspection.ciphertext,
        doc_id=inspection.doc_id,
        doc_hash=inspection.doc_hash,
        auth_payload=inspection.auth_payload,
        auth_status=inspection.auth_status,
        allow_unsigned=inspection.allow_unsigned,
        unlock=inspection.unlock,
        blocking_issues=inspection.blocking_issues,
        output_path=expanduser_cli_path(args.output_path),
        extension_index=args.extension_index,
        extension_doc_hash=args.extension_doc_hash,
        expected_head_doc_hash=args.expected_head_doc_hash,
        loaded_source=inspection.loaded_source,
        decoded_import_session=inspection.decoded_import_session,
        source=inspection.source,
    )


def _inspect_unselected_import_documents(
    *,
    loaded_source: LoadedRecoverySource,
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
        loaded_source=loaded_source,
        ciphertext=candidate.ciphertext,
        doc_id=candidate.doc_id,
        doc_hash=candidate.doc_hash,
        auth_payload=None,
        auth_status=auth_status,
        allow_unsigned=allow_unsigned,
        unlock=unlock,
        blocking_issues=tuple(blocking_issues),
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
) -> tuple[BlockingIssue, ...]:
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
) -> BlockingIssue:
    return blocking_issue(
        code,
        message,
        details={
            "stage": "root_selection",
            "main_document_count": len(import_documents),
            "candidate_doc_ids": [document.doc_id.hex() for document in import_documents],
        },
    )
