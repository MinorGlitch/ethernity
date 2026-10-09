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

"""Plan updates from authenticated document contents, independent of storage layout."""

from __future__ import annotations

from dataclasses import dataclass

from ethernity.config import load_app_config
from ethernity.core.validation import validate_manifest_file_tree
from ethernity.crypto.age_policy import recovery_kdf_budget
from ethernity.crypto.document_identity import normalize_doc_hash_hex
from ethernity.encoding.framing import Frame
from ethernity.extensions.chain import ValidatedChainState, replay_authenticated_chain
from ethernity.extensions.errors import ExtensionRecoveryError
from ethernity.extensions.recovery import (
    ChainRecoveryResult,
    imported_documents_from_recovery_frames,
    recover_chain_entries,
)
from ethernity.formats.extension_document import derive_chain_id
from ethernity.formats.extension_mode import UpdateMode, resolve_update_mode
from ethernity.formats.manifest_summary import manifest_summary_payload
from ethernity.workflows.add_files.errors import AddFilesIssue, AddFilesWorkflowError
from ethernity.workflows.add_files.request import AddFilesRequest
from ethernity.workflows.add_files.scope import load_selected_scope, summarize_scope_diff
from ethernity.workflows.recovery.models import RecoveryInspection
from ethernity.workflows.recovery.planning import RecoveryPlan, inspect_from_request
from ethernity.workflows.recovery.source_state import RecoverySourceFields
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.events import CommandError
from ethernity.workflows.shared.input_scope import InputScopeDiff, SelectedInputScope
from ethernity.workflows.shared.requests import RecoveryRequest


@dataclass(frozen=True)
class AddFilesInspection:
    input_label: str
    input_detail: str
    input_kind: str
    source_summary: dict[str, object] | None
    frame_counts: dict[str, int]
    root_doc_id: str
    root_doc_hash: str
    chain_id: str
    root_auth_status: str
    unlock: dict[str, object]
    available_extension_indices: tuple[int, ...]
    validated_head_index: int | None
    validated_head_doc_hash: str | None
    available_extensions: tuple[dict[str, object], ...]
    ancestry_valid: bool | None
    validated_head_auth_status: str | None
    validated_head_root_signing_key_verified: bool | None
    signing_key: dict[str, object]
    selected_scope: dict[str, object] | None
    diff_summary: dict[str, object] | None
    blocking_issues: tuple[AddFilesIssue, ...]


@dataclass(frozen=True)
class AppendParent:
    """Authenticated root and head selected for one Add Files publication."""

    root_doc_hash: bytes
    head_index: int
    head_doc_hash: bytes


@dataclass(frozen=True)
class AppendSigningKey:
    """Signing seed verified against the root backup's public key."""

    signing_seed: bytes


@dataclass(frozen=True)
class ResolvedAddFilesPlan:
    """File changes, selected parent, and root signing key for one update."""

    diff: InputScopeDiff
    parent: AppendParent
    signing_key: AppendSigningKey
    update_mode: UpdateMode = UpdateMode.CUMULATIVE


@dataclass(frozen=True)
class ResolvedAddFilesState:
    inspection: AddFilesInspection
    plan: ResolvedAddFilesPlan | None
    selected_input: SelectedInputScope | None
    validated_chain: ValidatedChainState | None
    chain_document_count: int
    chain_ciphertext_bytes: int
    chain_decoded_chunk_bytes: int
    resolved_passphrase: str | None
    source_frames: tuple[Frame, ...] = ()

    @property
    def blocking_issues(self) -> tuple[AddFilesIssue, ...]:
        return self.inspection.blocking_issues


def inspect_add_files(request: AddFilesRequest) -> AddFilesInspection:
    return resolve_add_files_state(request).inspection


def resolve_add_files_state(request: AddFilesRequest) -> ResolvedAddFilesState:
    """Capture one authenticated source version for inspection and later publication."""

    if not (
        request.scan_paths or request.frames or request.recovery_text_file or request.payloads_file
    ):
        raise AddFilesWorkflowError(
            code=issue_codes.INPUT_REQUIRED,
            message="Provide backup PDFs, images, recovery text, or QR payloads for Add Files.",
        )
    with recovery_kdf_budget():
        return _resolve_content_state(request)


def _resolve_content_state(request: AddFilesRequest) -> ResolvedAddFilesState:
    try:
        selected_input = load_selected_scope(request)
        root = inspect_from_request(_recovery_request(request))
    except FileNotFoundError as exc:
        raise AddFilesWorkflowError(
            code=issue_codes.NOT_FOUND, message=str(exc), details={"path": exc.filename}
        ) from exc
    except CommandError as exc:
        raise AddFilesWorkflowError(
            code=exc.code, message=exc.message, details=dict(exc.details)
        ) from exc
    except ValueError as exc:
        raise AddFilesWorkflowError(code=issue_codes.INVALID_INPUT, message=str(exc)) from exc

    source_frames = (*root.source_frames, *root.source_extra_auth_frames)
    documents = (
        imported_documents_from_recovery_frames(list(source_frames)) if source_frames else ()
    )
    issues = [AddFilesIssue.from_mapping(issue) for issue in root.blocking_issues]
    chain: ValidatedChainState | None = None
    recovered: ChainRecoveryResult | None = None
    signing_seed: bytes | None = None
    diff: InputScopeDiff | None = None
    update_mode = resolve_update_mode(None, request.update_mode)
    if root.unlock.satisfied and root.unlock.resolved_passphrase and not issues:
        try:
            recovered = recover_chain_entries(_recovery_plan(root, request), debug=False)
            if recovered.manifest.sealed:
                issues.append(
                    AddFilesIssue(
                        code=issue_codes.SEALED_ROOT_CANNOT_ACCEPT_UPDATES,
                        message="Sealed roots cannot accept updates.",
                    )
                )
            else:
                chain, signing_seed = _append_chain_state(root, recovered, request)
                update_mode = resolve_update_mode(chain.update_mode, request.update_mode)
                if selected_input is not None:
                    diff = summarize_scope_diff(chain.files, selected_input)
                    issues.extend(_diff_issues(diff))
                    issues.extend(_file_tree_issues(chain, selected_input))
        except ExtensionRecoveryError as exc:
            issues.append(AddFilesIssue(code=exc.code, message=str(exc), details=dict(exc.details)))
        except ValueError as exc:
            issues.append(AddFilesIssue(code=issue_codes.CHAIN_INVALID, message=str(exc)))

    head_index = chain.head_index if chain is not None else None
    head_hash = chain.head_doc_hash.hex() if chain is not None else None
    issues.extend(_freshness_issues(request, head_hash))
    extensions: tuple[dict[str, object], ...] = tuple(
        {
            "index": link.document.header.index,
            "doc_id": link.doc_hash[:8].hex(),
            "doc_hash": link.doc_hash.hex(),
            "auth_status": link.auth_status,
            "root_signing_key_verified": link.root_signing_key_verified,
        }
        for link in (chain.links if chain is not None else ())
    )
    inspection = AddFilesInspection(
        input_label=root.input_label or "Backup documents",
        input_detail=root.input_detail or "Imported document content",
        input_kind="extended_root" if len(documents) > 1 else "standalone_root",
        source_summary=manifest_summary_payload(recovered.manifest)
        if recovered is not None
        else None,
        frame_counts={
            "main": len(root.main_frames),
            "auth": len(root.auth_frames),
            "shard": len(root.shard_frames),
        },
        root_doc_id=root.doc_id.hex(),
        root_doc_hash=root.doc_hash.hex(),
        chain_id=derive_chain_id(root.doc_hash).hex() if root.doc_hash else "",
        root_auth_status=root.auth_status,
        unlock={
            "mode": root.unlock.mode,
            "passphrase_provided": root.unlock.passphrase_provided,
            "validated_shard_count": root.unlock.validated_shard_count,
            "required_shard_threshold": root.unlock.required_shard_threshold,
            "shard_share_count": root.unlock.shard_share_count,
            "satisfied": recovered is not None,
        },
        available_extension_indices=tuple(
            link.document.header.index for link in (chain.links if chain is not None else ())
        ),
        validated_head_index=head_index,
        validated_head_doc_hash=head_hash,
        available_extensions=extensions,
        ancestry_valid=chain is not None,
        validated_head_auth_status=recovered.head.auth_status if recovered is not None else None,
        validated_head_root_signing_key_verified=chain is not None,
        signing_key={
            "available": signing_seed is not None,
            "satisfied": chain is not None and signing_seed is not None,
            "source": "embedded_seed" if signing_seed is not None else None,
        },
        selected_scope=selected_input.to_inspection_payload()
        if selected_input is not None
        else None,
        diff_summary=diff.to_payload() if diff is not None else None,
        blocking_issues=tuple(issues),
    )
    plan = None
    if chain is not None and diff is not None and signing_seed is not None:
        plan = ResolvedAddFilesPlan(
            diff=diff,
            parent=AppendParent(root.doc_hash, chain.head_index, chain.head_doc_hash),
            signing_key=AppendSigningKey(signing_seed),
            update_mode=update_mode,
        )
    return ResolvedAddFilesState(
        inspection=inspection,
        plan=plan,
        selected_input=selected_input,
        validated_chain=chain,
        chain_document_count=len(documents),
        chain_ciphertext_bytes=sum(len(document.ciphertext) for document in documents),
        chain_decoded_chunk_bytes=chain.decoded_chunk_bytes if chain is not None else 0,
        resolved_passphrase=root.unlock.resolved_passphrase,
        source_frames=tuple(source_frames),
    )


def _append_chain_state(
    root: RecoveryInspection, recovered: ChainRecoveryResult, request: AddFilesRequest
) -> tuple[ValidatedChainState, bytes]:
    signing_seed = recovered.manifest.signing_seed
    if signing_seed is None or root.auth_payload is None:
        raise ValueError("Authenticated root signing key is missing.")
    chain = recovered.validated_chain
    if chain is None:
        if recovered.root_payload is None:
            raise ValueError("Decoded root payload is missing.")
        chunking = load_app_config(
            request.config_path, paper_size=request.paper_size
        ).extension_chunking
        chain = replay_authenticated_chain(
            recovered.manifest,
            recovered.root_payload,
            root_doc_hash=root.doc_hash,
            root_auth_payload=root.auth_payload,
            expected_sign_pub=root.auth_payload.sign_pub,
            extensions=(),
            root_chunking=chunking,
        )
    return chain, signing_seed


def _recovery_request(request: AddFilesRequest) -> RecoveryRequest:
    return RecoveryRequest(
        config_path=request.config_path,
        paper_size=request.paper_size,
        recovery_text_file=request.recovery_text_file,
        payloads_file=request.payloads_file,
        scan_paths=request.scan_paths,
        frames=request.frames,
        passphrase=request.passphrase,
        shard_text_files=request.shard_fallback_files,
        shard_payload_files=request.shard_payload_files,
        shard_scan_paths=request.shard_scan_paths,
        shard_frames=request.shard_frames,
        auth_text_file=request.auth_text_file,
        auth_payloads_file=request.auth_payloads_file,
        auth_frames=request.auth_frames,
        quiet=request.quiet,
    )


def _recovery_plan(root: RecoveryInspection, request: AddFilesRequest) -> RecoveryPlan:
    if root.unlock.resolved_passphrase is None:
        raise ValueError("Backup passphrase is missing.")
    return RecoveryPlan(
        ciphertext=root.ciphertext,
        doc_id=root.doc_id,
        doc_hash=root.doc_hash,
        passphrase=root.unlock.resolved_passphrase,
        auth_payload=root.auth_payload,
        auth_status=root.auth_status,
        allow_unsigned=False,
        output_path=None,
        import_documents=imported_documents_from_recovery_frames(
            [*root.source_frames, *root.source_extra_auth_frames]
        ),
        decoded_import_session=root.decoded_import_session,
        expected_head_doc_hash=request.expected_head_doc_hash,
        source=RecoverySourceFields(
            input_label=root.input_label,
            input_detail=root.input_detail,
            main_frames=root.main_frames,
            auth_frames=root.auth_frames,
            shard_frames=root.shard_frames,
            shard_fallback_files=root.shard_fallback_files,
            shard_payloads_file=root.shard_payloads_file,
            shard_scan=root.shard_scan,
        ),
    )


def _freshness_issues(request: AddFilesRequest, head_hash: str | None) -> tuple[AddFilesIssue, ...]:
    if request.expected_head_doc_hash is not None:
        expected = normalize_doc_hash_hex(request.expected_head_doc_hash, option="--expected-head")
        if head_hash is not None and head_hash != expected:
            return (
                AddFilesIssue(
                    code=issue_codes.RECOVERY_HEAD_UNTRUSTED,
                    message="The supplied head does not match the expected head fingerprint.",
                    details={
                        "expected_head_doc_hash": expected,
                        "validated_head_doc_hash": head_hash,
                    },
                ),
            )
        return ()
    if request.allow_stale_head:
        return ()
    return (
        AddFilesIssue(
            code=issue_codes.RECOVERY_HEAD_UNTRUSTED,
            message=(
                "Provide --expected-head or acknowledge that this is only the "
                "latest supplied version with --allow-stale-head."
            ),
            details={"freshness_scope": "supplied_carriers_only"},
        ),
    )


def _file_tree_issues(
    chain: ValidatedChainState,
    selected: SelectedInputScope,
) -> tuple[AddFilesIssue, ...]:
    paths = (
        *(item.path for item in chain.files),
        *(item.relative_path for item in selected.input_files),
    )
    try:
        validate_manifest_file_tree(paths, label="Updated file paths")
    except ValueError as exc:
        return (
            AddFilesIssue(
                code=issue_codes.DELETE_NOT_SUPPORTED,
                message=(
                    f"{exc}. Updates cannot remove conflicting paths. "
                    "Create a new backup for this file layout."
                ),
                details={"stage": "file_tree"},
            ),
        )
    return ()


def _diff_issues(diff: InputScopeDiff) -> tuple[AddFilesIssue, ...]:
    issues: list[AddFilesIssue] = []
    if diff.ambiguous_path_aliases:
        issues.append(
            AddFilesIssue(
                code=issue_codes.INVALID_INPUT,
                message=(
                    "Selected paths resemble existing paths; provide --base-dir to disambiguate."
                ),
                details={
                    "path_aliases": [
                        {"selected_path": selected, "existing_path": existing}
                        for selected, existing in diff.ambiguous_path_aliases
                    ]
                },
            )
        )
    if diff.missing_paths:
        issues.append(
            AddFilesIssue(
                code=issue_codes.DELETE_NOT_SUPPORTED,
                message="Add Files cannot delete or rename paths. Create a new backup instead.",
                details={"missing_paths": list(diff.missing_paths)},
            )
        )
    return tuple(issues)
