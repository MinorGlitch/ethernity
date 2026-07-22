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

"""Read-only planning helpers for the extension workflow."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from ethernity.config.load import load_app_config
from ethernity.core.bounds import MAX_RECOVERY_DECODED_CHUNK_BYTES
from ethernity.core.paths import expand_user_paths
from ethernity.crypto import sharding as sharding_module
from ethernity.crypto.document_identity import normalize_doc_hash_hex
from ethernity.crypto.signing import AuthPayload, verify_shard
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.fallback_text import format_fallback_error
from ethernity.encoding.framing import Frame, FrameType, encode_frame
from ethernity.extensions.chain import (
    LogicalFileState,
    ValidatedChainState,
    _replay_authenticated_chain_state,
    extract_root_logical_state,
)
from ethernity.extensions.discovery import (
    DiscoveredExtensionMainCarrier,
    DiscoveredExtensionShardCarrier,
    require_backup_root_dir,
)
from ethernity.extensions.published import (
    available_extensions_from_recovery_chain,
    discovered_extension_indices as _domain_discovered_extension_indices,
    extension_chain_present,
    inspect_published_extension_chain,
    inspect_published_extension_inventory,
    root_head_root_authority_verified,
)
from ethernity.extensions.recovery import (
    DecodedImportSession,
    ImportedRecoveryDocument,
    RecoveryChainInspection,
    RecoveryExtensionInventory,
    RecoveryReplayFailure,
    decode_imported_extension_link,
    decode_imported_root_manifest,
    decode_root_manifest as _decode_root_manifest_shared,
    imported_document_from_recovery_frames,
    imported_documents_from_recovery_frames,
    resolve_root_manifest_authority,
    select_root_import_session,
)
from ethernity.extensions.resources import require_chain_resource_limits
from ethernity.formats import EnvelopeManifest
from ethernity.formats.envelope_summary import manifest_summary_payload
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
    derive_chain_id,
)
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC
from ethernity.qr.scan import looks_like_pdf
from ethernity.workflows.extension.errors import ExtensionIssue, ExtensionWorkflowError
from ethernity.workflows.extension.published_recovery_validation import (
    validate_published_recovery_document_carrier,
    validate_published_shard_fallback_carrier,
)
from ethernity.workflows.extension.request import ExtensionRequest
from ethernity.workflows.extension.scope import (
    SelectedExtendScope,
    empty_scope_inspection_payload,
    load_selected_scope,
    summarize_scope_diff,
)
from ethernity.workflows.recovery.frame_inputs import (
    NoQrFramesError,
    format_shard_input_error,
    frame_from_fallback,
    frames_from_payloads,
    recovery_frames_from_scan,
    shard_frames_from_scan,
)
from ethernity.workflows.recovery.inspection import (
    inspect_recovery_inputs,
    select_root_import_document_from_passphrase_shards,
)
from ethernity.workflows.recovery.models import (
    RecoveryInspection,
)
from ethernity.workflows.recovery.root_shard_policy import (
    root_level_key_frame_carriers_from_scan,
)
from ethernity.workflows.shared import api_codes
from ethernity.workflows.shared.input_scope import InputScopeDiff

_CANONICAL_ROOT_SHARD_RE = re.compile(
    r"^(?P<role>shard|signing-key-shard)-(?P<doc_id>[0-9a-f]{16})-"
    r"(?P<share_index>[1-9][0-9]*)-of-(?P<share_count>[1-9][0-9]*)\.pdf$"
)


@dataclass(frozen=True)
class _CanonicalRootShardName:
    path: Path
    role: str
    doc_id_hex: str
    share_index: int
    share_count: int


@dataclass(frozen=True)
class ExtendInspection:
    doc_id: str | None
    root_dir: str
    input_label: str
    input_detail: str
    input_kind: str
    source_summary: dict[str, object] | None
    frame_counts: dict[str, int]
    root_doc_id: str | None
    root_doc_hash: str | None
    chain_id: str | None
    auth_status: str
    unlock: dict[str, object]
    discovered_extension_dirs: tuple[int, ...]
    validated_head_index: int | None
    validated_head_doc_hash: str | None
    available_extensions: tuple[dict[str, object], ...]
    ancestry_valid: bool | None
    validated_head_auth_status: str | None
    validated_head_root_authority_verified: bool | None
    signing_authority: dict[str, object]
    selected_scope: dict[str, object] | None
    diff_summary: dict[str, object] | None
    blocking_issues: tuple[ExtensionIssue, ...]


@dataclass(frozen=True)
class ValidatedExtensionIdentity:
    """Authenticated identity of one extension in a validated chain prefix."""

    index: int
    doc_hash: bytes


@dataclass(frozen=True)
class ValidatedChainLineage:
    """Authenticated chain identity and head selected for an append."""

    root_doc_id: str
    root_doc_hash: bytes
    chain_id: bytes
    head_index: int
    head_doc_hash: bytes
    ancestry_valid: bool
    head_auth_status: str
    head_root_authority_verified: bool
    extensions: tuple[ValidatedExtensionIdentity, ...]


@dataclass(frozen=True)
class ValidatedAppendAuthority:
    """Root-authorized signing capability retained for extension execution."""

    signing_seed: bytes
    source: Literal["embedded_seed"]


@dataclass(frozen=True)
class ResolvedExtensionPlan:
    """Typed planning contract consumed by extension execution."""

    diff: InputScopeDiff
    lineage: ValidatedChainLineage
    authority: ValidatedAppendAuthority
    issues: tuple[ExtensionIssue, ...]


@dataclass(frozen=True)
class ResolvedExtendState:
    inspection: ExtendInspection
    plan: ResolvedExtensionPlan | None
    diff: InputScopeDiff | None
    lineage: ValidatedChainLineage | None
    authority: ValidatedAppendAuthority | None
    issues: tuple[ExtensionIssue, ...]
    loaded_scope: SelectedExtendScope | None
    current_state: tuple[LogicalFileState, ...] | None
    validated_chain_state: ValidatedChainState | None
    chain_document_count: int
    chain_ciphertext_bytes: int
    chain_decoded_chunk_bytes: int
    resolved_passphrase: str | None
    root_doc_hash: bytes | None
    parent_doc_hash: bytes | None
    next_index: int | None
    signing_seed: bytes | None
    chunking: ExtensionChunkingProfile | None
    root_passphrase_shard_threshold: int | None = None
    root_passphrase_shard_count: int = 0
    unlock_passphrase_shard_threshold: int | None = None
    unlock_passphrase_shard_count: int = 0


@dataclass(frozen=True)
class _RootRecoveryInspection:
    inspection: RecoveryInspection
    shard_unlock_target: Literal["none", "root", "extension"]
    import_documents: tuple[ImportedRecoveryDocument, ...] = ()
    decoded_import_session: DecodedImportSession | None = None


def inspect_from_args(args: ExtensionRequest) -> ExtendInspection:
    return resolve_extend_state(args).inspection


def require_extend_root_dir(
    args: ExtensionRequest,
    *,
    command_name: str,
) -> str:
    if not args.publish_root:
        raise ExtensionWorkflowError(
            code="INPUT_REQUIRED",
            message=f"--root-dir is required for `{command_name}`",
        )
    return args.publish_root


def _resolve_scanned_publish_root_dir(root_dir: str | Path) -> Path:
    path = Path(root_dir).expanduser()
    if path.is_symlink():
        raise ValueError("extension publish root must not be a symlink")
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"extension publish root must be a directory: {root_dir}")
        return path

    parent = path.parent
    if parent.is_symlink():
        raise ValueError("extension publish root parent must not be a symlink")
    if not parent.exists():
        raise ValueError(f"extension publish root parent not found: {parent}")
    if not parent.is_dir():
        raise ValueError(f"extension publish root parent must be a directory: {parent}")
    if not os.access(parent, os.W_OK | os.X_OK):
        raise ValueError(f"extension publish root parent is not writable: {parent}")
    return path


def resolve_extend_state(args: ExtensionRequest) -> ResolvedExtendState:
    """Inspect extension state from supplied carriers and a writable publish root."""

    root_dir_arg = require_extend_root_dir(args, command_name="extension task")
    try:
        root_dir = (
            _resolve_scanned_publish_root_dir(root_dir_arg)
            if _uses_scanned_chain_source(args)
            else require_backup_root_dir(root_dir_arg)
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("root backup directory not found:"):
            raise ExtensionWorkflowError(
                code="NOT_FOUND",
                message=message,
                details={"path": root_dir_arg},
            ) from exc
        raise ExtensionWorkflowError(
            code="INVALID_INPUT",
            message=message,
            details={"path": root_dir_arg},
        ) from exc

    blocking_issues: list[ExtensionIssue] = []
    discovered_extension_dirs: tuple[int, ...] = ()
    available_extensions: tuple[dict[str, object], ...] = ()
    new_chain_chunking = _default_chunking_profile(args)
    input_kind = "standalone_root"
    extension_inventory: RecoveryExtensionInventory | None = None
    if _uses_scanned_chain_source(args):
        input_kind = "scanned_chain"
    else:
        try:
            extension_inventory = _inspect_published_extension_inventory(
                root_dir,
                quiet=args.quiet,
            )
            discovered_extension_dirs = _discovered_extension_indices(extension_inventory)
            if discovered_extension_dirs:
                input_kind = "extended_root"
            if extension_inventory.failure is not None:
                blocking_issues.append(
                    ExtensionIssue(
                        code="EXTENSION_LAYOUT_INVALID",
                        message=extension_inventory.failure.message,
                        details={"root_dir": str(root_dir)},
                    )
                )
        except ValueError as exc:
            blocking_issues.append(
                ExtensionIssue(
                    code="EXTENSION_LAYOUT_INVALID",
                    message=str(exc),
                    details={"root_dir": str(root_dir)},
                )
            )

    loaded_scope = None
    selected_scope = None
    if args.input_paths or args.input_directories:
        try:
            loaded_scope = load_selected_scope(args)
        except FileNotFoundError as exc:
            raise ExtensionWorkflowError(
                code="NOT_FOUND",
                message=str(exc),
                details={"path": exc.filename},
            ) from exc
        except ValueError as exc:
            raise ExtensionWorkflowError(
                code="INVALID_INPUT",
                message=str(exc),
            ) from exc
        if loaded_scope is not None:
            selected_scope = loaded_scope.to_inspection_payload()
    elif args.base_directory:
        selected_scope = empty_scope_inspection_payload(base_dir_arg=args.base_directory)

    root_recovery = _inspect_root_recovery(
        root_dir,
        args,
        extension_inventory=extension_inventory,
    )

    return _resolve_extend_state_after_root_inspection(
        args=args,
        root_dir=root_dir,
        root_recovery=root_recovery,
        blocking_issues=blocking_issues,
        loaded_scope=loaded_scope,
        selected_scope=selected_scope,
        discovered_extension_dirs=discovered_extension_dirs,
        available_extensions=available_extensions,
        input_kind=input_kind,
        extension_inventory=extension_inventory,
        new_chain_chunking=new_chain_chunking,
    )


def _resolve_extend_state_after_root_inspection(
    *,
    args: ExtensionRequest,
    root_dir: Path,
    root_recovery: _RootRecoveryInspection,
    blocking_issues: list[ExtensionIssue],
    loaded_scope: SelectedExtendScope | None,
    selected_scope: dict[str, object] | None,
    discovered_extension_dirs: tuple[int, ...],
    available_extensions: tuple[dict[str, object], ...],
    input_kind: str,
    extension_inventory: RecoveryExtensionInventory | None,
    new_chain_chunking: ExtensionChunkingProfile,
) -> ResolvedExtendState:
    root_inspection = root_recovery.inspection
    doc_id_hex = root_inspection.doc_id.hex()
    doc_hash_hex = root_inspection.doc_hash.hex()
    chain_id_hex = derive_chain_id(root_inspection.doc_hash).hex()
    blocking_issues.extend(
        ExtensionIssue.from_mapping(item) for item in root_inspection.blocking_issues
    )
    source_summary: dict[str, object] | None = None
    validated_head_index: int | None = None
    validated_head_doc_hash: str | None = None
    ancestry_valid: bool | None = None
    validated_head_auth_status: str | None = None
    validated_head_root_authority_verified: bool | None = None
    signing_authority: dict[str, object] = {
        "available": False,
        "satisfied": False,
        "source": None,
    }
    diff: InputScopeDiff | None = None
    signing_authority_source: Literal["embedded_seed"] | None = None
    root_doc_hash_bytes: bytes | None = root_inspection.doc_hash
    parent_doc_hash: bytes | None = None
    next_index: int | None = None
    signing_seed: bytes | None = None
    chunking: ExtensionChunkingProfile | None = None
    unlock_passphrase_shard_threshold = (
        root_inspection.unlock.required_shard_threshold
        if root_inspection.unlock.mode == "shards"
        else None
    )
    unlock_passphrase_shard_count = (
        root_inspection.unlock.shard_share_count
        if root_inspection.unlock.mode == "shards"
        and root_inspection.unlock.shard_share_count is not None
        else 0
    )
    root_passphrase_shard_threshold = (
        unlock_passphrase_shard_threshold if root_recovery.shard_unlock_target == "root" else None
    )
    root_passphrase_shard_count = (
        unlock_passphrase_shard_count if root_recovery.shard_unlock_target == "root" else 0
    )

    current_state: tuple[LogicalFileState, ...] | None = None
    validated_chain_state: ValidatedChainState | None = None
    chain_document_count = 1
    chain_ciphertext_bytes = len(root_inspection.ciphertext)
    chain_decoded_chunk_bytes = 0
    validated_extensions: tuple[ValidatedExtensionIdentity, ...] = ()
    root_decrypt_succeeded = False
    if root_inspection.unlock.satisfied and root_inspection.unlock.resolved_passphrase is not None:
        try:
            if root_recovery.decoded_import_session is None:
                manifest, payload = _decode_root_manifest(
                    root_inspection.ciphertext,
                    passphrase=root_inspection.unlock.resolved_passphrase,
                )
            else:
                manifest, payload = decode_imported_root_manifest(
                    root_recovery.decoded_import_session.root_document,
                    decoded_import_session=root_recovery.decoded_import_session,
                )
        except ValueError as exc:
            blocking_issues.append(
                ExtensionIssue(
                    "UNLOCK_FAILED",
                    str(exc),
                    details={"stage": "decrypt"},
                )
            )
        else:
            root_decrypt_succeeded = True
            try:
                source_summary = manifest_summary_payload(manifest)
                current_state = extract_root_logical_state(manifest, payload)
                if manifest.sealed:
                    blocking_issues.append(
                        ExtensionIssue(
                            "SEALED_ROOT_NOT_EXTENDABLE",
                            "sealed roots are terminal in v1 and cannot be extended",
                        )
                    )
                else:
                    authority = resolve_root_manifest_authority(
                        manifest, root_inspection.auth_payload
                    )
                    embedded_signing_seed = manifest.signing_seed
                    if embedded_signing_seed is None:
                        raise ValueError("root backup manifest is missing an embedded signing seed")
                    if authority.mismatch:
                        blocking_issues.append(
                            ExtensionIssue(
                                "ROOT_AUTHORITY_MISMATCH",
                                (
                                    "embedded signing seed does not match the verified "
                                    "root AUTH authority"
                                ),
                            )
                        )
                        signing_authority = {
                            "available": True,
                            "satisfied": False,
                            "source": None,
                        }
                    else:
                        signing_seed = embedded_signing_seed
                        signing_authority_source = "embedded_seed"
                        signing_authority = {
                            "available": True,
                            "satisfied": True,
                            "source": "embedded_seed",
                        }
                        chain_inventory = extension_inventory
                        if root_recovery.import_documents:
                            chain_inventory = _scan_extension_inventory_from_imported_documents(
                                root_recovery.import_documents,
                                root_doc_hash=root_inspection.doc_hash,
                                root_doc_id=root_inspection.doc_id,
                                passphrase=root_inspection.unlock.resolved_passphrase,
                                expected_sign_pub=authority.embedded_sign_pub,
                                quiet=args.quiet,
                                decoded_import_session=root_recovery.decoded_import_session,
                            )
                            discovered_extension_dirs = _discovered_extension_indices(
                                chain_inventory
                            )
                            if chain_inventory.failure is not None:
                                blocking_issues.append(
                                    ExtensionIssue(
                                        api_codes.RECOVERY_HEAD_UNTRUSTED,
                                        (
                                            "scanned extension chain could not be trusted: "
                                            f"{chain_inventory.failure.message}"
                                        ),
                                        details={
                                            "stage": chain_inventory.failure.stage,
                                            "failure_head_index": (
                                                chain_inventory.failure.head_index
                                            ),
                                            "failure_head_doc_hash": (
                                                chain_inventory.failure.head_doc_hash
                                            ),
                                            "failure_head_source": (
                                                chain_inventory.failure.head_dir_name
                                            ),
                                        },
                                    )
                                )
                        if (
                            chain_inventory is not None
                            and extension_chain_present(chain_inventory)
                            and not manifest.sealed
                        ):
                            chain_document_count = 1 + len(chain_inventory.extensions)
                            chain_ciphertext_bytes = len(root_inspection.ciphertext) + sum(
                                len(document.ciphertext) for document in chain_inventory.extensions
                            )
                            (
                                current_state,
                                validated_head_index,
                                validated_head_doc_hash,
                                ancestry_valid,
                                parent_doc_hash,
                                next_index,
                                chunking,
                                validated_chain_state,
                                chain_decoded_chunk_bytes,
                                available_extensions,
                                validated_head_auth_status,
                                validated_head_root_authority_verified,
                                discovered_extension_dirs,
                                input_kind,
                                validated_extensions,
                            ) = _reconstruct_extension_state(
                                manifest=manifest,
                                payload=payload,
                                root_doc_hash=root_inspection.doc_hash,
                                passphrase=root_inspection.unlock.resolved_passphrase,
                                expected_sign_pub=authority.embedded_sign_pub,
                                root_auth_status=root_inspection.auth_status,
                                root_auth_payload=root_inspection.auth_payload,
                                blocking_issues=blocking_issues,
                                inventory=chain_inventory,
                                new_chain_chunking=new_chain_chunking,
                                source_input_kind=input_kind,
                                quiet=args.quiet,
                            )
                        else:
                            validated_head_index = 0
                            validated_head_doc_hash = root_inspection.doc_hash.hex()
                            ancestry_valid = True
                            validated_head_auth_status = root_inspection.auth_status
                            validated_head_root_authority_verified = (
                                root_head_root_authority_verified(
                                    root_auth_status=root_inspection.auth_status,
                                    expected_sign_pub=authority.embedded_sign_pub,
                                )
                            )
                            parent_doc_hash = root_inspection.doc_hash
                            next_index = 1
                            chunking = new_chain_chunking
                            if root_inspection.auth_payload is None:
                                raise ValueError("verified root backup is missing its AUTH payload")
                            if authority.embedded_sign_pub is None:
                                raise ValueError(
                                    "root backup manifest is missing signing authority"
                                )
                            validated_chain_state = _replay_authenticated_chain_state(
                                manifest,
                                payload,
                                root_doc_hash=root_inspection.doc_hash,
                                root_auth_payload=root_inspection.auth_payload,
                                expected_sign_pub=authority.embedded_sign_pub,
                                extensions=(),
                                root_chunking=chunking,
                            )

                if current_state is not None and loaded_scope is not None:
                    diff = summarize_scope_diff(current_state, loaded_scope)
                    if diff.ambiguous_path_aliases:
                        blocking_issues.append(
                            ExtensionIssue(
                                api_codes.INVALID_INPUT,
                                (
                                    "selected input paths would create new logical paths that "
                                    "look like existing backed paths; provide --base-dir to "
                                    "disambiguate"
                                ),
                                details={
                                    "path_aliases": [
                                        {
                                            "selected_path": selected_path,
                                            "existing_path": existing_path,
                                        }
                                        for selected_path, existing_path in (
                                            diff.ambiguous_path_aliases
                                        )
                                    ]
                                },
                            )
                        )
                    if diff.missing_paths:
                        blocking_issues.append(
                            ExtensionIssue(
                                "DELETE_NOT_SUPPORTED",
                                (
                                    "selected scope omits previously backed paths; Add Files "
                                    "cannot delete or rename paths. Create a New Backup from the "
                                    "desired files and retire the superseded carriers"
                                ),
                                details={"missing_paths": list(diff.missing_paths)},
                            )
                        )
            except ValueError as exc:
                blocking_issues.append(
                    ExtensionIssue(
                        api_codes.CHAIN_INVALID,
                        str(exc),
                        details={"stage": "chain"},
                    )
                )

    blocking_issues = [
        *_selection_guard_issues(
            args,
            validated_head_index=validated_head_index,
            validated_head_doc_hash=validated_head_doc_hash,
        ),
        *blocking_issues,
    ]
    issues = tuple(blocking_issues)
    inspection = ExtendInspection(
        doc_id=doc_id_hex,
        root_dir=str(root_dir),
        input_label=root_inspection.input_label or "Backup root directory",
        input_detail=root_inspection.input_detail or str(root_dir.resolve()),
        input_kind=input_kind,
        source_summary=source_summary,
        frame_counts={
            "main": len(root_inspection.main_frames),
            "auth": len(root_inspection.auth_frames),
            "shard": len(root_inspection.shard_frames),
        },
        root_doc_id=doc_id_hex,
        root_doc_hash=doc_hash_hex,
        chain_id=chain_id_hex,
        auth_status=root_inspection.auth_status,
        unlock={
            "mode": root_inspection.unlock.mode,
            "passphrase_provided": root_inspection.unlock.passphrase_provided,
            "validated_shard_count": root_inspection.unlock.validated_shard_count,
            "required_shard_threshold": root_inspection.unlock.required_shard_threshold,
            "shard_share_count": root_inspection.unlock.shard_share_count,
            "satisfied": root_inspection.unlock.satisfied and root_decrypt_succeeded,
        },
        discovered_extension_dirs=discovered_extension_dirs,
        validated_head_index=validated_head_index,
        validated_head_doc_hash=validated_head_doc_hash,
        available_extensions=available_extensions,
        ancestry_valid=ancestry_valid,
        validated_head_auth_status=validated_head_auth_status,
        validated_head_root_authority_verified=validated_head_root_authority_verified,
        signing_authority=signing_authority,
        selected_scope=selected_scope,
        diff_summary=diff.to_payload() if diff is not None else None,
        blocking_issues=issues,
    )
    lineage = _validated_chain_lineage(
        root_doc_id=doc_id_hex,
        root_doc_hash=root_doc_hash_bytes,
        chain_id_hex=chain_id_hex,
        validated_head_index=validated_head_index,
        validated_head_doc_hash=validated_head_doc_hash,
        ancestry_valid=ancestry_valid,
        validated_head_auth_status=validated_head_auth_status,
        validated_head_root_authority_verified=validated_head_root_authority_verified,
        extensions=validated_extensions,
    )
    authority = (
        ValidatedAppendAuthority(signing_seed=signing_seed, source=signing_authority_source)
        if signing_seed is not None and signing_authority_source is not None
        else None
    )
    plan = (
        ResolvedExtensionPlan(
            diff=diff,
            lineage=lineage,
            authority=authority,
            issues=issues,
        )
        if diff is not None and lineage is not None and authority is not None
        else None
    )
    return ResolvedExtendState(
        inspection=inspection,
        plan=plan,
        diff=diff,
        lineage=lineage,
        authority=authority,
        issues=issues,
        loaded_scope=loaded_scope,
        current_state=current_state,
        validated_chain_state=validated_chain_state,
        chain_document_count=chain_document_count,
        chain_ciphertext_bytes=chain_ciphertext_bytes,
        chain_decoded_chunk_bytes=chain_decoded_chunk_bytes,
        resolved_passphrase=root_inspection.unlock.resolved_passphrase,
        root_doc_hash=root_doc_hash_bytes,
        parent_doc_hash=parent_doc_hash,
        next_index=next_index,
        signing_seed=signing_seed,
        chunking=chunking,
        root_passphrase_shard_threshold=root_passphrase_shard_threshold,
        root_passphrase_shard_count=root_passphrase_shard_count,
        unlock_passphrase_shard_threshold=unlock_passphrase_shard_threshold,
        unlock_passphrase_shard_count=unlock_passphrase_shard_count,
    )


def _validated_chain_lineage(
    *,
    root_doc_id: str,
    root_doc_hash: bytes | None,
    chain_id_hex: str,
    validated_head_index: int | None,
    validated_head_doc_hash: str | None,
    ancestry_valid: bool | None,
    validated_head_auth_status: str | None,
    validated_head_root_authority_verified: bool | None,
    extensions: tuple[ValidatedExtensionIdentity, ...],
) -> ValidatedChainLineage | None:
    if (
        root_doc_hash is None
        or validated_head_index is None
        or validated_head_doc_hash is None
        or ancestry_valid is not True
        or validated_head_auth_status is None
        or validated_head_root_authority_verified is not True
    ):
        return None
    return ValidatedChainLineage(
        root_doc_id=root_doc_id,
        root_doc_hash=root_doc_hash,
        chain_id=bytes.fromhex(chain_id_hex),
        head_index=validated_head_index,
        head_doc_hash=bytes.fromhex(validated_head_doc_hash),
        ancestry_valid=True,
        head_auth_status=validated_head_auth_status,
        head_root_authority_verified=True,
        extensions=extensions,
    )


def _selection_guard_issues(
    args: ExtensionRequest,
    *,
    validated_head_index: int | None,
    validated_head_doc_hash: str | None,
) -> tuple[ExtensionIssue, ...]:
    expected_issue = _expected_head_issue(
        args,
        validated_head_index=validated_head_index,
        validated_head_doc_hash=validated_head_doc_hash,
    )
    freshness_issue = _scan_freshness_issue(
        args,
        validated_head_index=validated_head_index,
        validated_head_doc_hash=validated_head_doc_hash,
    )
    return tuple(issue for issue in (expected_issue, freshness_issue) if issue is not None)


def _expected_head_issue(
    args: ExtensionRequest,
    *,
    validated_head_index: int | None,
    validated_head_doc_hash: str | None,
) -> ExtensionIssue | None:
    if args.expected_head_doc_hash is None:
        return None
    expected_head_doc_hash = normalize_doc_hash_hex(
        args.expected_head_doc_hash,
        option="--expected-head-doc-hash",
    )
    if validated_head_doc_hash is None or validated_head_doc_hash == expected_head_doc_hash:
        return None
    return ExtensionIssue(
        api_codes.RECOVERY_HEAD_UNTRUSTED,
        (
            "validated extension head doc_hash does not match expected head "
            f"{expected_head_doc_hash}; latest supplied head is "
            f"{validated_head_doc_hash}"
        ),
        details={
            "stage": "selection",
            "expected_head_doc_hash": expected_head_doc_hash,
            "validated_head_index": validated_head_index,
            "validated_head_doc_hash": validated_head_doc_hash,
            "freshness_scope": "supplied_carriers_only",
        },
    )


def _scan_freshness_issue(
    args: ExtensionRequest,
    *,
    validated_head_index: int | None,
    validated_head_doc_hash: str | None,
) -> ExtensionIssue | None:
    if not _uses_scanned_chain_source(args):
        return None
    if args.expected_head_doc_hash is not None or args.allow_stale_head:
        return None
    return ExtensionIssue(
        api_codes.RECOVERY_HEAD_UNTRUSTED,
        (
            "scan-mode extend cannot prove the supplied recovery set is the latest chain state; "
            "provide --expected-head-doc-hash or pass --allow-stale-head to acknowledge this risk"
        ),
        details={
            "stage": "selection",
            "validated_head_index": validated_head_index,
            "validated_head_doc_hash": validated_head_doc_hash,
            "freshness_scope": "supplied_carriers_only",
            "required_acknowledgement": "--allow-stale-head",
        },
    )


def _inspect_root_recovery(
    root_dir: Path,
    args: ExtensionRequest,
    *,
    extension_inventory: RecoveryExtensionInventory | None,
) -> _RootRecoveryInspection:
    if _uses_scanned_chain_source(args):
        return _inspect_scanned_chain_recovery(args)

    scan_paths = _published_root_scan_paths(root_dir)
    if not scan_paths:
        raise ExtensionWorkflowError(
            code=api_codes.NOT_FOUND,
            message="root backup documents not found in the writable backup directory",
            details={"root_dir": str(root_dir)},
        )
    frames = _recovery_frames_from_published_root_scan_paths(scan_paths, quiet=args.quiet)
    _require_published_append_resource_admission(frames, extension_inventory)
    shard_frames, shard_fallback_files, shard_payloads_file, shard_scan = (
        _shard_frames_from_extend_args(args, quiet=args.quiet)
    )
    root_inspection = inspect_recovery_inputs(
        frames=frames,
        extra_auth_frames=[],
        shard_frames=shard_frames,
        passphrase=args.passphrase,
        allow_unsigned=False,
        input_label="Backup root directory",
        input_detail=str(root_dir.resolve()),
        shard_fallback_files=shard_fallback_files,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        quiet=args.quiet,
    )
    _audit_published_root_fallback_carriers(root_dir, root_inspection, quiet=args.quiet)
    if (
        args.passphrase
        or root_inspection.unlock.satisfied
        or not shard_frames
        or extension_inventory is None
        or not extension_inventory.extensions
    ):
        shard_target: Literal["none", "root"] = (
            "root" if root_inspection.unlock.mode == "shards" else "none"
        )
        return _RootRecoveryInspection(root_inspection, shard_target)
    extension_inspection, decoded_import_session = _inspect_root_recovery_with_extension_shards(
        root_inspection,
        frames=frames,
        shard_frames=shard_frames,
        shard_fallback_files=shard_fallback_files,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        extension_inventory=extension_inventory,
        input_detail=str(root_dir.resolve()),
        quiet=args.quiet,
    )
    return _RootRecoveryInspection(
        extension_inspection,
        "extension",
        decoded_import_session=decoded_import_session,
    )


def _require_published_append_resource_admission(
    root_frames: list[Frame],
    extension_inventory: RecoveryExtensionInventory | None,
) -> None:
    root_ciphertext = reassemble_payload(
        [frame for frame in root_frames if frame.frame_type == FrameType.MAIN_DOCUMENT],
        expected_frame_type=FrameType.MAIN_DOCUMENT,
    )
    extensions = () if extension_inventory is None else extension_inventory.extensions
    chain_ciphertext_bytes = len(root_ciphertext) + sum(
        len(document.ciphertext) for document in extensions
    )
    require_chain_resource_limits(
        document_count=2 + len(extensions),
        total_ciphertext_bytes=chain_ciphertext_bytes + 1,
        operation="extension append",
    )


def _uses_scanned_chain_source(args: ExtensionRequest) -> bool:
    return bool(args.scan_paths)


def _inspect_scanned_chain_recovery(args: ExtensionRequest) -> _RootRecoveryInspection:
    scan_paths = expand_user_paths(list(args.scan_paths or []))
    if not scan_paths:
        raise ExtensionWorkflowError(
            code=api_codes.INPUT_REQUIRED,
            message="--scan is required when extending from scanned backup documents",
        )
    frames = list(recovery_frames_from_scan(scan_paths).frames)
    shard_frames, shard_fallback_files, shard_payloads_file, shard_scan = (
        _shard_frames_from_extend_args(args, quiet=args.quiet)
    )
    import_documents = imported_documents_from_recovery_frames(
        frames,
        source_label="extend scan",
    )
    if len(import_documents) <= 1:
        root_inspection = inspect_recovery_inputs(
            frames=frames,
            extra_auth_frames=[],
            shard_frames=shard_frames,
            passphrase=args.passphrase,
            allow_unsigned=False,
            input_label="Scanned backup documents",
            input_detail=", ".join(scan_paths),
            shard_fallback_files=shard_fallback_files,
            shard_payloads_file=shard_payloads_file,
            shard_scan=shard_scan,
            quiet=args.quiet,
        )
        shard_target: Literal["none", "root"] = (
            "root" if root_inspection.unlock.mode == "shards" else "none"
        )
        return _RootRecoveryInspection(root_inspection, shard_target, import_documents)

    if args.passphrase:
        try:
            normalized_passphrase = _normalize_scan_selection_passphrase(args.passphrase)
        except ValueError as exc:
            raise ExtensionWorkflowError(
                code=api_codes.INVALID_INPUT,
                message=str(exc),
                details={"stage": "scan_root_selection"},
            ) from exc
        try:
            decoded_import_session = select_root_import_session(
                import_documents,
                passphrase=normalized_passphrase,
                debug=False,
            )
            root_document = decoded_import_session.root_document
        except ValueError as exc:
            raise ExtensionWorkflowError(
                code=api_codes.INVALID_INPUT,
                message=str(exc),
                details={"stage": "scan_root_selection"},
            ) from exc
        root_inspection = _inspect_selected_scan_root_document(
            frames,
            root_document=root_document,
            passphrase=normalized_passphrase,
            shard_frames=shard_frames,
            shard_fallback_files=shard_fallback_files,
            shard_payloads_file=shard_payloads_file,
            shard_scan=shard_scan,
            input_detail=", ".join(scan_paths),
            quiet=args.quiet,
        )
        return _RootRecoveryInspection(
            root_inspection,
            "none",
            import_documents,
            decoded_import_session,
        )

    if shard_frames:
        try:
            selection = select_root_import_document_from_passphrase_shards(
                import_documents,
                shard_frames=shard_frames,
                allow_unsigned=False,
                quiet=args.quiet,
            )
        except ValueError as exc:
            raise ExtensionWorkflowError(
                code=api_codes.PASSPHRASE_SHARDS_INVALID,
                message=str(exc),
                details={"stage": "scan_root_selection"},
            ) from exc
        if selection.unlock.resolved_passphrase is None:
            raise ExtensionWorkflowError(
                code=api_codes.PASSPHRASE_SHARDS_INVALID,
                message="scanned shard inputs did not recover a passphrase",
                details={"stage": "scan_root_selection"},
            )
        root_inspection = _inspect_selected_scan_root_document(
            frames,
            root_document=selection.root_document,
            passphrase=selection.unlock.resolved_passphrase,
            shard_frames=[],
            shard_fallback_files=[],
            shard_payloads_file=[],
            shard_scan=[],
            input_detail=", ".join(scan_paths),
            quiet=args.quiet,
        )
        root_inspection = replace(
            root_inspection,
            unlock=selection.unlock,
            shard_frames=tuple(shard_frames),
            shard_fallback_files=tuple(shard_fallback_files),
            shard_payloads_file=tuple(shard_payloads_file),
            shard_scan=tuple(shard_scan),
        )
        selected_shard_target: Literal["root", "extension"] = (
            "root"
            if selection.target_document.doc_hash == selection.root_document.doc_hash
            else "extension"
        )
        return _RootRecoveryInspection(
            root_inspection,
            selected_shard_target,
            import_documents,
            getattr(selection, "decoded_import_session", None),
        )

    raise ExtensionWorkflowError(
        code=api_codes.PASSPHRASE_REQUIRED,
        message=(
            "passphrase or passphrase shards are required when --scan contains multiple "
            "MAIN documents"
        ),
        details={"stage": "scan_root_selection", "main_document_count": len(import_documents)},
    )


def _normalize_scan_selection_passphrase(passphrase: str) -> str:
    return passphrase


def _inspect_selected_scan_root_document(
    frames: list[Frame],
    *,
    root_document: ImportedRecoveryDocument,
    passphrase: str,
    shard_frames: list[Frame],
    shard_fallback_files: list[str],
    shard_payloads_file: list[str],
    shard_scan: list[str],
    input_detail: str,
    quiet: bool,
) -> RecoveryInspection:
    root_frames = [frame for frame in frames if frame.doc_id == root_document.doc_id]
    return inspect_recovery_inputs(
        frames=root_frames,
        extra_auth_frames=[],
        shard_frames=shard_frames,
        passphrase=passphrase,
        allow_unsigned=False,
        input_label="Scanned backup documents",
        input_detail=input_detail,
        shard_fallback_files=shard_fallback_files,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        quiet=quiet,
    )


def _scan_extension_inventory_from_imported_documents(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    root_doc_hash: bytes,
    root_doc_id: bytes,
    passphrase: str | None,
    expected_sign_pub: bytes | None,
    quiet: bool,
    decoded_import_session: DecodedImportSession | None = None,
) -> RecoveryExtensionInventory:
    if passphrase is None:
        raise ValueError("scanned extension replay requires a resolved passphrase")
    if expected_sign_pub is None:
        raise ValueError("scanned extension replay requires an unsealed root signing authority")

    extensions: list[ImportedRecoveryDocument] = []
    seen_indexes: set[int] = set()
    remaining_inline_chunk_bytes = MAX_RECOVERY_DECODED_CHUNK_BYTES
    for document in documents:
        if document.doc_hash == root_doc_hash:
            continue
        if document.doc_id == root_doc_id:
            failure = RecoveryReplayFailure(
                stage="selection",
                message=(
                    "scanned content contains a document whose doc_id collides with the "
                    "selected root backup"
                ),
                head_doc_hash=document.doc_hash.hex(),
                head_dir_name=document.source_label,
            )
            return RecoveryExtensionInventory(extensions=tuple(extensions), failure=failure)
        try:
            decoded = decode_imported_extension_link(
                document,
                passphrase=passphrase,
                expected_sign_pub=expected_sign_pub,
                quiet=quiet,
                debug=False,
                max_inline_chunk_bytes=remaining_inline_chunk_bytes,
                decoded_import_session=decoded_import_session,
            )
        except (ExtensionWorkflowError, ValueError) as exc:
            failure = RecoveryReplayFailure(
                stage="scan",
                message=str(exc),
                head_doc_hash=document.doc_hash.hex(),
                head_dir_name=document.source_label,
            )
            return RecoveryExtensionInventory(extensions=tuple(extensions), failure=failure)
        remaining_inline_chunk_bytes -= decoded.link.document.inline_chunk_raw_bytes
        index = decoded.link.document.header.index
        if index in seen_indexes:
            failure = RecoveryReplayFailure(
                stage="selection",
                message=f"scanned content contains multiple extensions for index {index}",
                head_index=index,
                head_doc_hash=document.doc_hash.hex(),
                head_dir_name=document.source_label,
            )
            return RecoveryExtensionInventory(extensions=tuple(extensions), failure=failure)
        seen_indexes.add(index)
        extensions.append(
            replace(
                document,
                extension_index=index,
                extension_dir_name=f"scan-{index:02d}",
            )
        )

    extensions = sorted(extensions, key=lambda item: item.index)
    latest = extensions[-1] if extensions else None
    return RecoveryExtensionInventory(
        extensions=tuple(extensions),
        latest_head_index=None if latest is None else latest.index,
        latest_head_doc_hash=None if latest is None else latest.doc_hash.hex(),
        latest_head_dir_name=None if latest is None else latest.dir_name,
    )


def _inspect_root_recovery_with_extension_shards(
    root_inspection: RecoveryInspection,
    *,
    frames: list[Frame],
    shard_frames: list[Frame],
    shard_fallback_files: list[str],
    shard_payloads_file: list[str],
    shard_scan: list[str],
    extension_inventory: RecoveryExtensionInventory,
    input_detail: str,
    quiet: bool,
) -> tuple[RecoveryInspection, DecodedImportSession | None]:
    root_document = ImportedRecoveryDocument.from_ciphertext(
        ciphertext=root_inspection.ciphertext,
        auth_frames=root_inspection.auth_frames,
        source_label="published root",
    )
    documents = (root_document, *extension_inventory.extensions)
    try:
        selection = select_root_import_document_from_passphrase_shards(
            documents,
            shard_frames=shard_frames,
            allow_unsigned=False,
            quiet=quiet,
        )
    except ValueError as exc:
        return (
            _extension_shard_unlock_failure_inspection(
                root_inspection,
                shard_frames=shard_frames,
                shard_fallback_files=shard_fallback_files,
                shard_payloads_file=shard_payloads_file,
                shard_scan=shard_scan,
                message=str(exc),
                details={"stage": "extension_shard_unlock"},
            ),
            None,
        )
    if (
        selection.root_document.doc_id != root_inspection.doc_id
        or selection.root_document.doc_hash != root_inspection.doc_hash
    ):
        return (
            _extension_shard_unlock_failure_inspection(
                root_inspection,
                shard_frames=shard_frames,
                shard_fallback_files=shard_fallback_files,
                shard_payloads_file=shard_payloads_file,
                shard_scan=shard_scan,
                message="extension passphrase shard inputs resolved a different root document",
                details={
                    "stage": "extension_shard_unlock",
                    "expected_root_doc_id": root_inspection.doc_id.hex(),
                    "expected_root_doc_hash": root_inspection.doc_hash.hex(),
                    "selected_root_doc_id": selection.root_document.doc_id.hex(),
                    "selected_root_doc_hash": selection.root_document.doc_hash.hex(),
                },
            ),
            None,
        )
    if selection.unlock.resolved_passphrase is None:
        return (
            _extension_shard_unlock_failure_inspection(
                root_inspection,
                shard_frames=shard_frames,
                shard_fallback_files=shard_fallback_files,
                shard_payloads_file=shard_payloads_file,
                shard_scan=shard_scan,
                message="extension passphrase shard inputs did not recover a passphrase",
                details={"stage": "extension_shard_unlock"},
            ),
            None,
        )

    unlocked = inspect_recovery_inputs(
        frames=frames,
        extra_auth_frames=[],
        shard_frames=[],
        passphrase=selection.unlock.resolved_passphrase,
        allow_unsigned=False,
        input_label="Backup root directory",
        input_detail=input_detail,
        shard_fallback_files=[],
        shard_payloads_file=[],
        shard_scan=[],
        quiet=quiet,
    )
    return (
        replace(
            unlocked,
            unlock=selection.unlock,
            shard_frames=tuple(shard_frames),
            shard_fallback_files=tuple(shard_fallback_files),
            shard_payloads_file=tuple(shard_payloads_file),
            shard_scan=tuple(shard_scan),
        ),
        getattr(selection, "decoded_import_session", None),
    )


def _extension_shard_unlock_failure_inspection(
    root_inspection: RecoveryInspection,
    *,
    shard_frames: list[Frame],
    shard_fallback_files: list[str],
    shard_payloads_file: list[str],
    shard_scan: list[str],
    message: str,
    details: dict[str, object],
) -> RecoveryInspection:
    issue = ExtensionIssue(
        api_codes.PASSPHRASE_SHARDS_INVALID,
        f"extension passphrase shard inputs could not unlock the published root chain: {message}",
        details=details,
    )
    return replace(
        root_inspection,
        shard_frames=tuple(shard_frames),
        shard_fallback_files=tuple(shard_fallback_files),
        shard_payloads_file=tuple(shard_payloads_file),
        shard_scan=tuple(shard_scan),
        blocking_issues=(*root_inspection.blocking_issues, issue.to_dict()),
    )


def _shard_frames_from_extend_args(
    args: ExtensionRequest,
    *,
    quiet: bool,
) -> tuple[list[Frame], list[str], list[str], list[str]]:
    shard_fallback_files = expand_user_paths(list(args.shard_fallback_files or []))
    shard_payloads_file = expand_user_paths(list(args.shard_payload_files or []))
    shard_scan = expand_user_paths(list(args.shard_scan_paths or []))
    shard_frames: list[Frame] = list(args.shard_frames or [])
    for path in shard_fallback_files:
        try:
            shard_frames.append(frame_from_fallback(path))
        except ValueError as exc:
            raise ValueError(format_fallback_error(exc, context="Shard recovery text")) from exc
    for path in shard_payloads_file:
        try:
            shard_frames.extend(frames_from_payloads(path, label="shard QR payloads"))
        except ValueError as exc:
            raise ValueError(format_shard_input_error(exc)) from exc
    if shard_scan:
        try:
            shard_frames.extend(shard_frames_from_scan(shard_scan).frames)
        except ValueError as exc:
            raise ValueError(format_shard_input_error(exc)) from exc
    if (
        args.shard_frames or shard_fallback_files or shard_payloads_file or shard_scan
    ) and not shard_frames:
        raise ValueError("no shard payloads found; check shard inputs and try again")
    return shard_frames, shard_fallback_files, shard_payloads_file, shard_scan


def _decode_root_manifest(ciphertext: bytes, *, passphrase: str) -> tuple[EnvelopeManifest, bytes]:
    return _decode_root_manifest_shared(ciphertext=ciphertext, passphrase=passphrase, debug=False)


def _discovered_extension_indices(inventory: RecoveryExtensionInventory) -> tuple[int, ...]:
    return _domain_discovered_extension_indices(inventory)


def _published_root_scan_paths(root_dir: Path) -> list[str]:
    paths: list[str] = []
    for name in ("qr_document.pdf", "recovery_document.pdf"):
        candidate = root_dir / name
        if candidate.is_symlink():
            raise ExtensionWorkflowError(
                code=api_codes.INVALID_INPUT,
                message=f"root backup MAIN carrier must not be a symlink: {name}",
                details={"root_dir": str(root_dir)},
            )
        if candidate.is_file():
            paths.append(str(candidate))
    return paths


def _audit_published_root_fallback_carriers(
    root_dir: Path,
    inspection: RecoveryInspection,
    *,
    quiet: bool,
) -> None:
    """Audit published root fallback text against authenticated machine-readable frames."""

    auth_payload = inspection.auth_payload
    if inspection.auth_status != "verified" or auth_payload is None:
        return
    document = ImportedRecoveryDocument.from_ciphertext(
        ciphertext=inspection.ciphertext,
        auth_frames=inspection.auth_frames,
        source_label="published root QR document",
    )
    recovery_path = root_dir / "recovery_document.pdf"
    if recovery_path.is_symlink() or not recovery_path.is_file():
        raise ValueError("published backup root is missing required recovery_document.pdf")
    validate_published_recovery_document_carrier(
        path=recovery_path,
        document=document,
    )

    canonical_names = _canonical_root_shard_names(root_dir)
    carrier_frames_by_path = dict(
        root_level_key_frame_carriers_from_scan(
            root_dir,
            quiet=quiet,
        )
    )
    audited_paths: set[Path] = set()
    canonical_payloads_by_role: dict[str, list[sharding_module.ShardPayload]] = {}
    for name in canonical_names:
        carrier_frames = carrier_frames_by_path.get(name.path)
        if carrier_frames is None:
            raise ValueError(f"canonical root shard carrier contains no KEY frame: {name.path}")
        validated = _validated_matching_root_shard(
            path=name.path,
            carrier_frames=carrier_frames,
            inspection=inspection,
            expected_sign_pub=auth_payload.sign_pub,
            require_single_key_frame=True,
        )
        if validated is None:
            raise ValueError(f"canonical root shard carrier is not bound to the root: {name.path}")
        frame, payload = validated
        expected_key_type = (
            sharding_module.KEY_TYPE_PASSPHRASE
            if name.role == "shard"
            else sharding_module.KEY_TYPE_SIGNING_SEED
        )
        if name.doc_id_hex != inspection.doc_id.hex():
            raise ValueError(
                f"canonical root shard filename doc_id does not match root: {name.path}"
            )
        if payload.key_type != expected_key_type:
            raise ValueError(
                f"canonical root shard filename role does not match payload: {name.path}"
            )
        if payload.share_index != name.share_index or payload.share_count != name.share_count:
            raise ValueError(
                f"canonical root shard filename share metadata is invalid: {name.path}"
            )
        if not looks_like_pdf(name.path):
            raise ValueError(f"canonical root shard carrier is not a valid PDF: {name.path}")
        validate_published_shard_fallback_carrier(path=name.path, frames=(frame,))
        audited_paths.add(name.path)
        canonical_payloads_by_role.setdefault(name.role, []).append(payload)
    _validate_canonical_root_shard_sets(canonical_names, canonical_payloads_by_role)

    for path, carrier_frames in carrier_frames_by_path.items():
        if path in audited_paths or not looks_like_pdf(path):
            continue
        validated = _validated_matching_root_shard(
            path=path,
            carrier_frames=carrier_frames,
            inspection=inspection,
            expected_sign_pub=auth_payload.sign_pub,
        )
        if validated is None:
            continue
        frame, _payload = validated
        validate_published_shard_fallback_carrier(path=path, frames=(frame,))


def _canonical_root_shard_names(root_dir: Path) -> tuple[_CanonicalRootShardName, ...]:
    names: list[_CanonicalRootShardName] = []
    for path in sorted(root_dir.iterdir()):
        match = _CANONICAL_ROOT_SHARD_RE.fullmatch(path.name)
        if match is None:
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"canonical root shard carrier must be a regular file: {path}")
        names.append(
            _CanonicalRootShardName(
                path=path,
                role=match.group("role"),
                doc_id_hex=match.group("doc_id"),
                share_index=int(match.group("share_index")),
                share_count=int(match.group("share_count")),
            )
        )
    return tuple(names)


def _validated_matching_root_shard(
    *,
    path: Path,
    carrier_frames: tuple[Frame, ...],
    inspection: RecoveryInspection,
    expected_sign_pub: bytes,
    require_single_key_frame: bool = False,
) -> tuple[Frame, sharding_module.ShardPayload] | None:
    distinct_key_frames = {
        encode_frame(frame): frame
        for frame in carrier_frames
        if frame.frame_type == FrameType.KEY_DOCUMENT
    }
    if require_single_key_frame and len(distinct_key_frames) != 1:
        raise ValueError(
            f"canonical root shard carrier must contain exactly one distinct KEY frame: {path}"
        )
    matching_frames: dict[bytes, tuple[Frame, sharding_module.ShardPayload]] = {}
    for frame in distinct_key_frames.values():
        try:
            payload = sharding_module.decode_shard_payload(frame.data)
        except ValueError:
            continue
        if frame.doc_id != inspection.doc_id or payload.doc_hash != inspection.doc_hash:
            continue
        matching_frames.setdefault(encode_frame(frame), (frame, payload))
    if not matching_frames:
        return None
    if len(matching_frames) != 1:
        raise ValueError(f"published root shard carrier contains multiple root payloads: {path}")
    frame, payload = next(iter(matching_frames.values()))
    if payload.sign_pub != expected_sign_pub:
        raise ValueError(f"published root shard signing authority does not match root: {path}")
    if payload.key_type not in {
        sharding_module.KEY_TYPE_PASSPHRASE,
        sharding_module.KEY_TYPE_SIGNING_SEED,
    }:
        raise ValueError(f"published root shard has unsupported key type: {path}")
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
        raise ValueError(f"published root shard signature verification failed: {path}")
    return frame, payload


def _validate_canonical_root_shard_sets(
    names: tuple[_CanonicalRootShardName, ...],
    payloads_by_role: dict[str, list[sharding_module.ShardPayload]],
) -> None:
    for role, payloads in payloads_by_role.items():
        role_names = [name for name in names if name.role == role]
        share_counts = {name.share_count for name in role_names}
        if len(share_counts) != 1:
            raise ValueError(f"canonical root {role} filenames disagree on share count")
        share_count = next(iter(share_counts))
        actual_indexes = sorted(name.share_index for name in role_names)
        if actual_indexes != list(range(1, share_count + 1)):
            raise ValueError(
                f"canonical root {role} set must contain shares 1 through {share_count}"
            )
        try:
            sharding_module.validate_shard_set_consistency(payloads)
        except ValueError as exc:
            raise ValueError(f"canonical root {role} shard set is inconsistent: {exc}") from exc


def _recovery_frames_from_published_root_scan_paths(
    scan_paths: list[str],
    *,
    quiet: bool,
) -> list[Frame]:
    frames: list[Frame] = []
    for path in scan_paths:
        try:
            frames.extend(recovery_frames_from_scan([path]).frames)
        except NoQrFramesError:
            continue
    if not frames:
        raise ValueError("published root scan found no QR frames")
    return frames


def _inspect_published_extension_inventory(
    root_dir: Path,
    *,
    quiet: bool,
) -> RecoveryExtensionInventory:
    def validate_recovery_document(
        carrier: DiscoveredExtensionMainCarrier,
        document: ImportedRecoveryDocument,
        _sign_pub: bytes,
    ) -> None:
        validate_published_recovery_document_carrier(path=carrier.path, document=document)

    return inspect_published_extension_inventory(
        root_dir,
        read_carrier_document=lambda carrier: _read_published_extension_carrier_document(
            carrier,
            quiet=quiet,
        ),
        read_shard_frames=lambda carrier: _read_published_extension_shard_frames(
            carrier,
            quiet=quiet,
        ),
        validate_recovery_document_carrier=validate_recovery_document,
    )


def _read_published_extension_shard_frames(
    carrier: DiscoveredExtensionShardCarrier,
    *,
    quiet: bool,
) -> list[Frame]:
    frames = list(shard_frames_from_scan([str(carrier.path)]).frames)
    validate_published_shard_fallback_carrier(path=carrier.path, frames=frames)
    return frames


def _read_published_extension_carrier_document(
    carrier: DiscoveredExtensionMainCarrier,
    *,
    quiet: bool,
) -> ImportedRecoveryDocument:
    ciphertext, auth_frames = scan_extension_carriers([str(carrier.path)], quiet=quiet)
    return ImportedRecoveryDocument.from_ciphertext(
        ciphertext=ciphertext,
        auth_frames=tuple(auth_frames),
        source_label=str(carrier.path),
    )


def scan_extension_carriers(paths: list[str], *, quiet: bool) -> tuple[bytes, list[Frame]]:
    if not paths:
        raise ValueError("no extension MAIN carriers were provided")
    frames = list(recovery_frames_from_scan(paths).frames)
    document = imported_document_from_recovery_frames(
        frames,
        source_label="extension carrier",
    )
    return document.ciphertext, list(document.auth_frames)


def _inspect_published_extension_chain(
    *,
    manifest: EnvelopeManifest,
    payload: bytes,
    root_doc_hash: bytes,
    passphrase: str,
    expected_sign_pub: bytes | None,
    root_auth_status: str | None,
    quiet: bool,
    debug: bool,
    inventory: RecoveryExtensionInventory,
) -> RecoveryChainInspection:
    return inspect_published_extension_chain(
        manifest=manifest,
        payload=payload,
        root_doc_hash=root_doc_hash,
        passphrase=passphrase,
        expected_sign_pub=expected_sign_pub,
        root_auth_status=root_auth_status,
        quiet=quiet,
        debug=debug,
        inventory=inventory,
    )


def _available_extensions_from_recovery_chain(
    chain_inspection: RecoveryChainInspection,
) -> tuple[dict[str, object], ...]:
    return available_extensions_from_recovery_chain(chain_inspection)


def _reconstruct_extension_state(
    *,
    manifest: EnvelopeManifest,
    payload: bytes,
    root_doc_hash: bytes,
    passphrase: str,
    expected_sign_pub: bytes | None,
    root_auth_status: str | None,
    root_auth_payload: AuthPayload | None,
    blocking_issues: list[ExtensionIssue],
    inventory: RecoveryExtensionInventory,
    new_chain_chunking: ExtensionChunkingProfile,
    source_input_kind: str,
    quiet: bool,
) -> tuple[
    tuple[LogicalFileState, ...] | None,
    int | None,
    str | None,
    bool | None,
    bytes | None,
    int | None,
    ExtensionChunkingProfile | None,
    ValidatedChainState | None,
    int,
    tuple[dict[str, object], ...],
    str | None,
    bool | None,
    tuple[int, ...],
    str,
    tuple[ValidatedExtensionIdentity, ...],
]:
    if expected_sign_pub is None:
        raise ValueError("root backup manifest is missing an embedded signing seed")
    if root_auth_payload is None:
        raise ValueError("authenticated chain replay requires a root AUTH payload")

    root_state = extract_root_logical_state(manifest, payload)
    chain_inspection = _inspect_published_extension_chain(
        manifest=manifest,
        payload=payload,
        root_doc_hash=root_doc_hash,
        passphrase=passphrase,
        expected_sign_pub=expected_sign_pub,
        root_auth_status=root_auth_status,
        quiet=quiet,
        debug=False,
        inventory=inventory,
    )
    discovered_extension_dirs = tuple(item.index for item in chain_inspection.inventory.extensions)
    if source_input_kind == "scanned_chain":
        input_kind = "scanned_chain"
    else:
        input_kind = "extended_root" if discovered_extension_dirs else "standalone_root"
    available_extensions = _available_extensions_from_recovery_chain(chain_inspection)
    validated_extensions = tuple(
        ValidatedExtensionIdentity(
            index=item.link.document.header.index,
            doc_hash=item.link.doc_hash,
        )
        for item in chain_inspection.links
    )

    if chain_inspection.refusal is not None:
        validated_head_auth_status = chain_inspection.validated_head_auth_status
        validated_head_root_authority_verified = (
            chain_inspection.validated_head_root_authority_verified
        )
        refusal_details = dict(chain_inspection.refusal.details)
        if chain_inspection.validated_head_index == 0:
            validated_head_auth_status = root_auth_status
            validated_head_root_authority_verified = root_head_root_authority_verified(
                root_auth_status=root_auth_status,
                expected_sign_pub=expected_sign_pub,
            )
            refusal_details["validated_head_auth_status"] = validated_head_auth_status
            refusal_details["validated_head_root_authority_verified"] = (
                validated_head_root_authority_verified
            )
        blocking_issues[:] = [
            issue
            for issue in blocking_issues
            if issue.code not in {"EXTENSION_LAYOUT_INVALID", "CHAIN_INVALID"}
        ]
        blocking_issues.insert(
            0,
            ExtensionIssue(
                chain_inspection.refusal.code,
                chain_inspection.refusal.message,
                details=refusal_details,
            ),
        )
        return (
            None,
            chain_inspection.validated_head_index,
            chain_inspection.validated_head_doc_hash,
            False,
            None,
            None,
            None,
            None,
            0,
            available_extensions,
            validated_head_auth_status,
            validated_head_root_authority_verified,
            discovered_extension_dirs,
            input_kind,
            validated_extensions,
        )

    if not chain_inspection.links or chain_inspection.latest_state is None:
        validated_chain_state = _replay_authenticated_chain_state(
            manifest,
            payload,
            root_doc_hash=root_doc_hash,
            root_auth_payload=root_auth_payload,
            expected_sign_pub=expected_sign_pub,
            extensions=(),
            root_chunking=new_chain_chunking,
        )
        return (
            root_state,
            chain_inspection.validated_head_index,
            chain_inspection.validated_head_doc_hash,
            True,
            root_doc_hash,
            1,
            new_chain_chunking,
            validated_chain_state,
            0,
            available_extensions,
            chain_inspection.validated_head_auth_status,
            chain_inspection.validated_head_root_authority_verified,
            discovered_extension_dirs,
            input_kind,
            validated_extensions,
        )

    locked_chunking = chain_inspection.locked_chunking
    if locked_chunking is None:
        raise ValueError("extension chain requires a locked chunking profile")

    authenticated_links = tuple(item.link for item in chain_inspection.links)
    validated_chain_state = _replay_authenticated_chain_state(
        manifest,
        payload,
        root_doc_hash=root_doc_hash,
        root_auth_payload=root_auth_payload,
        expected_sign_pub=expected_sign_pub,
        extensions=authenticated_links,
        root_chunking=locked_chunking,
    )

    return (
        chain_inspection.latest_state,
        chain_inspection.validated_head_index,
        chain_inspection.validated_head_doc_hash,
        True,
        chain_inspection.links[-1].link.doc_hash,
        chain_inspection.validated_head_index + 1,
        locked_chunking,
        validated_chain_state,
        sum(item.link.document.inline_chunk_raw_bytes for item in chain_inspection.links),
        available_extensions,
        chain_inspection.validated_head_auth_status,
        chain_inspection.validated_head_root_authority_verified,
        discovered_extension_dirs,
        input_kind,
        validated_extensions,
    )


def _default_chunking_profile(args: ExtensionRequest) -> ExtensionChunkingProfile:
    try:
        return _default_chunking_profile_from_config(args)
    except ValueError as exc:
        raise ExtensionWorkflowError(
            code=api_codes.INVALID_INPUT,
            message=str(exc),
            details={"config": args.config_path},
        ) from exc


def _default_chunking_profile_from_config(args: ExtensionRequest) -> ExtensionChunkingProfile:
    configured = load_app_config(args.config_path, paper_size=args.paper_size).extension_chunking
    return ExtensionChunkingProfile(
        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
        target_size=configured.target_size,
        min_size=configured.min_size,
        max_size=configured.max_size,
    )
