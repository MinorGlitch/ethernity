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

"""Read-only planning helpers for extension inspection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from ethernity.cli.features.extend.published_recovery_validation import (
    validate_published_recovery_document_carrier,
)
from ethernity.cli.features.extend.scope import (
    SelectedExtendScope,
    empty_scope_inspection_payload,
    load_selected_scope,
    summarize_scope_diff,
)
from ethernity.cli.features.recover.planning import (
    RecoveryInspection,
    inspect_recovery_inputs,
    select_root_import_document_from_passphrase_shards,
)
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.crypto import doc_id_and_hash_from_ciphertext, normalize_doc_hash_hex
from ethernity.cli.shared.io.fallback_parser import format_fallback_error
from ethernity.cli.shared.io.frames import (
    _frame_from_fallback,
    _frames_from_payloads,
    format_shard_input_error,
    recovery_frames_from_scan,
    shard_frames_from_scan,
)
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.paths import expanduser_cli_paths
from ethernity.cli.shared.types import ExtendArgs
from ethernity.config.load import load_app_config
from ethernity.encoding.framing import Frame
from ethernity.extensions.chain import (
    LogicalFileState,
    build_chain_available_chunks,
    extract_root_logical_state,
)
from ethernity.extensions.discovery import (
    DiscoveredExtensionMainCarrier,
    require_backup_root_dir,
)
from ethernity.extensions.published import (
    available_extensions_from_inventory as _domain_available_extensions_from_inventory,
    available_extensions_from_recovery_chain,
    discovered_extension_indices as _domain_discovered_extension_indices,
    extension_chain_present,
    inspect_published_extension_chain,
    inspect_published_extension_inventory,
    root_head_root_authority_verified,
    sorted_chunk_items,
)
from ethernity.extensions.recovery import (
    ImportedRecoveryDocument,
    RecoveryChainInspection,
    RecoveryExtensionInventory,
    decode_root_manifest as _decode_root_manifest_shared,
    imported_document_from_recovery_frames,
    resolve_root_manifest_authority,
)
from ethernity.formats import EnvelopeManifest
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
    derive_chain_id,
)
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC


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
    blocking_issues: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class ResolvedExtendState:
    inspection: ExtendInspection
    loaded_scope: SelectedExtendScope | None
    current_state: tuple[LogicalFileState, ...] | None
    available_chunks: tuple[tuple[bytes, bytes], ...]
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


def inspect_from_args(args: ExtendArgs) -> ExtendInspection:
    return resolve_extend_state(args).inspection


def require_extend_root_dir(
    args: ExtendArgs,
    *,
    command_name: str,
) -> str:
    if not args.root_dir:
        raise ApiCommandError(
            code="INPUT_REQUIRED",
            message=f"--root-dir is required for `{command_name}`",
        )
    return args.root_dir


def resolve_extend_state(args: ExtendArgs) -> ResolvedExtendState:
    """Inspect extension layout from a writable backup root directory."""

    root_dir_arg = require_extend_root_dir(args, command_name="ethernity api inspect extend")
    try:
        root_dir = require_backup_root_dir(root_dir_arg)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("root backup directory not found:"):
            raise ApiCommandError(
                code="NOT_FOUND",
                message=message,
                details={"path": root_dir_arg},
            ) from exc
        raise ApiCommandError(
            code="INVALID_INPUT",
            message=message,
            details={"path": root_dir_arg},
        ) from exc

    blocking_issues: list[dict[str, object]] = []
    discovered_extension_dirs: tuple[int, ...] = ()
    available_extensions: tuple[dict[str, object], ...] = ()
    new_chain_chunking = _default_chunking_profile(args)
    input_kind = "standalone_root"
    extension_inventory: RecoveryExtensionInventory | None = None
    try:
        extension_inventory = _inspect_published_extension_inventory(
            root_dir,
            quiet=args.quiet,
        )
        discovered_extension_dirs = _discovered_extension_indices(extension_inventory)
        available_extensions = _available_extensions_from_inventory(extension_inventory)
        if discovered_extension_dirs:
            input_kind = "extended_root"
        if extension_inventory.failure is not None:
            blocking_issues.append(
                {
                    "code": "EXTENSION_LAYOUT_INVALID",
                    "message": extension_inventory.failure.message,
                    "details": {"root_dir": str(root_dir)},
                }
            )
    except ValueError as exc:
        blocking_issues.append(
            {
                "code": "EXTENSION_LAYOUT_INVALID",
                "message": str(exc),
                "details": {"root_dir": str(root_dir)},
            }
        )

    loaded_scope = None
    selected_scope = None
    if args.input or args.input_dir:
        try:
            loaded_scope = load_selected_scope(args)
        except FileNotFoundError as exc:
            raise ApiCommandError(
                code="NOT_FOUND",
                message=str(exc),
                details={"path": exc.filename},
            ) from exc
        except ValueError as exc:
            raise ApiCommandError(
                code="INVALID_INPUT",
                message=str(exc),
            ) from exc
        if loaded_scope is not None:
            selected_scope = loaded_scope.to_inspection_payload()
    elif args.base_dir:
        selected_scope = empty_scope_inspection_payload(base_dir_arg=args.base_dir)

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
    args: ExtendArgs,
    root_dir: Path,
    root_recovery: _RootRecoveryInspection,
    blocking_issues: list[dict[str, object]],
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
    blocking_issues.extend(dict(item) for item in root_inspection.blocking_issues)
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
    diff_summary: dict[str, object] | None = None
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
    available_chunks: tuple[tuple[bytes, bytes], ...] = ()
    root_decrypt_succeeded = False
    if root_inspection.unlock.satisfied and root_inspection.unlock.resolved_passphrase is not None:
        try:
            manifest, payload = _decode_root_manifest(
                root_inspection.ciphertext,
                passphrase=root_inspection.unlock.resolved_passphrase,
            )
        except ValueError as exc:
            blocking_issues.append(
                _blocking_issue(
                    "UNLOCK_FAILED",
                    str(exc),
                    details={"stage": "decrypt"},
                )
            )
        else:
            root_decrypt_succeeded = True
            try:
                source_summary = _manifest_summary_payload(manifest)
                current_state = extract_root_logical_state(manifest, payload)
                if manifest.sealed:
                    blocking_issues.append(
                        _blocking_issue(
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
                            _blocking_issue(
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
                        signing_authority = {
                            "available": True,
                            "satisfied": True,
                            "source": "embedded_seed",
                        }
                        if (
                            extension_inventory is not None
                            and extension_chain_present(extension_inventory)
                            and not manifest.sealed
                        ):
                            (
                                current_state,
                                validated_head_index,
                                validated_head_doc_hash,
                                ancestry_valid,
                                parent_doc_hash,
                                next_index,
                                chunking,
                                available_chunks,
                                available_extensions,
                                validated_head_auth_status,
                                validated_head_root_authority_verified,
                                discovered_extension_dirs,
                                input_kind,
                            ) = _reconstruct_extension_state(
                                root_dir=root_dir,
                                manifest=manifest,
                                payload=payload,
                                root_doc_hash=root_inspection.doc_hash,
                                passphrase=root_inspection.unlock.resolved_passphrase,
                                expected_sign_pub=authority.embedded_sign_pub,
                                root_auth_status=root_inspection.auth_status,
                                blocking_issues=blocking_issues,
                                inventory=extension_inventory,
                                new_chain_chunking=new_chain_chunking,
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
                            available_chunks = _sorted_chunk_items(
                                build_chain_available_chunks(current_state, chunking)
                            )

                if current_state is not None and loaded_scope is not None:
                    diff = summarize_scope_diff(current_state, loaded_scope)
                    diff_summary = diff.to_payload()
                    if diff.ambiguous_path_aliases:
                        blocking_issues.append(
                            _blocking_issue(
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
                            _blocking_issue(
                                "DELETE_NOT_SUPPORTED",
                                (
                                    "selected scope omits previously backed paths; "
                                    "delete/rename is unsupported"
                                ),
                                details={"missing_paths": list(diff.missing_paths)},
                            )
                        )
            except ValueError as exc:
                blocking_issues.append(
                    _blocking_issue(
                        api_codes.CHAIN_INVALID,
                        str(exc),
                        details={"stage": "chain"},
                    )
                )

    inspection = ExtendInspection(
        doc_id=doc_id_hex,
        root_dir=str(root_dir),
        input_label="Backup root directory",
        input_detail=str(root_dir.resolve()),
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
        diff_summary=diff_summary,
        blocking_issues=tuple(blocking_issues),
    )
    inspection = _apply_expected_head_guard(args, inspection)
    return ResolvedExtendState(
        inspection=inspection,
        loaded_scope=loaded_scope,
        current_state=current_state,
        available_chunks=available_chunks,
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


def _apply_expected_head_guard(args: ExtendArgs, inspection: ExtendInspection) -> ExtendInspection:
    if args.expected_head_doc_hash is None:
        return inspection
    expected_head_doc_hash = normalize_doc_hash_hex(
        args.expected_head_doc_hash,
        option="--expected-head-doc-hash",
    )
    if inspection.validated_head_doc_hash is None:
        return inspection
    if inspection.validated_head_doc_hash == expected_head_doc_hash:
        args.expected_head_doc_hash = expected_head_doc_hash
        return inspection
    issue = _blocking_issue(
        api_codes.RECOVERY_HEAD_UNTRUSTED,
        (
            "validated extension head doc_hash does not match expected head "
            f"{expected_head_doc_hash}; latest supplied head is "
            f"{inspection.validated_head_doc_hash}"
        ),
        details={
            "stage": "selection",
            "expected_head_doc_hash": expected_head_doc_hash,
            "validated_head_index": inspection.validated_head_index,
            "validated_head_doc_hash": inspection.validated_head_doc_hash,
            "freshness_scope": "supplied_carriers_only",
        },
    )
    return replace(inspection, blocking_issues=(issue, *inspection.blocking_issues))


def _inspect_root_recovery(
    root_dir: Path,
    args: ExtendArgs,
    *,
    extension_inventory: RecoveryExtensionInventory | None,
) -> _RootRecoveryInspection:
    scan_paths = _published_root_scan_paths(root_dir)
    if not scan_paths:
        raise ApiCommandError(
            code=api_codes.NOT_FOUND,
            message="root backup documents not found in the writable backup directory",
            details={"root_dir": str(root_dir)},
        )
    frames = recovery_frames_from_scan(scan_paths, quiet=args.quiet)
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
    extension_inspection = _inspect_root_recovery_with_extension_shards(
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
    return _RootRecoveryInspection(extension_inspection, "extension")


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
) -> RecoveryInspection:
    root_document = ImportedRecoveryDocument(
        doc_id=root_inspection.doc_id,
        doc_hash=root_inspection.doc_hash,
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
        return _extension_shard_unlock_failure_inspection(
            root_inspection,
            shard_frames=shard_frames,
            shard_fallback_files=shard_fallback_files,
            shard_payloads_file=shard_payloads_file,
            shard_scan=shard_scan,
            message=str(exc),
            details={"stage": "extension_shard_unlock"},
        )
    if (
        selection.root_document.doc_id != root_inspection.doc_id
        or selection.root_document.doc_hash != root_inspection.doc_hash
    ):
        return _extension_shard_unlock_failure_inspection(
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
        )
    if selection.unlock.resolved_passphrase is None:
        return _extension_shard_unlock_failure_inspection(
            root_inspection,
            shard_frames=shard_frames,
            shard_fallback_files=shard_fallback_files,
            shard_payloads_file=shard_payloads_file,
            shard_scan=shard_scan,
            message="extension passphrase shard inputs did not recover a passphrase",
            details={"stage": "extension_shard_unlock"},
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
    return replace(
        unlocked,
        unlock=selection.unlock,
        shard_frames=tuple(shard_frames),
        shard_fallback_files=tuple(shard_fallback_files),
        shard_payloads_file=tuple(shard_payloads_file),
        shard_scan=tuple(shard_scan),
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
    issue = _blocking_issue(
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
        blocking_issues=(*root_inspection.blocking_issues, issue),
    )


def _shard_frames_from_extend_args(
    args: ExtendArgs,
    *,
    quiet: bool,
) -> tuple[list[Frame], list[str], list[str], list[str]]:
    shard_fallback_files = expanduser_cli_paths(list(args.shard_fallback_file or []))
    shard_payloads_file = expanduser_cli_paths(list(args.shard_payloads_file or []))
    shard_scan = expanduser_cli_paths(list(args.shard_scan or []))
    shard_frames: list[Frame] = list(args.shard_frames or [])
    for path in shard_fallback_files:
        try:
            shard_frames.append(_frame_from_fallback(path, quiet=quiet))
        except ValueError as exc:
            raise ValueError(format_fallback_error(exc, context="Shard recovery text")) from exc
    for path in shard_payloads_file:
        try:
            shard_frames.extend(_frames_from_payloads(path, label="shard QR payloads"))
        except ValueError as exc:
            raise ValueError(format_shard_input_error(exc)) from exc
    if shard_scan:
        try:
            shard_frames.extend(shard_frames_from_scan(shard_scan, quiet=quiet))
        except ValueError as exc:
            raise ValueError(format_shard_input_error(exc)) from exc
    if (
        args.shard_frames or shard_fallback_files or shard_payloads_file or shard_scan
    ) and not shard_frames:
        raise ValueError("no shard payloads found; check shard inputs and try again")
    return shard_frames, shard_fallback_files, shard_payloads_file, shard_scan


def _decode_root_manifest(ciphertext: bytes, *, passphrase: str) -> tuple[EnvelopeManifest, bytes]:
    return _decode_root_manifest_shared(ciphertext=ciphertext, passphrase=passphrase, debug=False)


def _available_extensions_from_inventory(
    inventory: RecoveryExtensionInventory,
) -> tuple[dict[str, object], ...]:
    return _domain_available_extensions_from_inventory(inventory)


def _discovered_extension_indices(inventory: RecoveryExtensionInventory) -> tuple[int, ...]:
    return _domain_discovered_extension_indices(inventory)


def _published_root_scan_paths(root_dir: Path) -> list[str]:
    paths: list[str] = []
    for name in ("qr_document.pdf", "recovery_document.pdf"):
        candidate = root_dir / name
        if candidate.is_symlink():
            raise ApiCommandError(
                code=api_codes.INVALID_INPUT,
                message=f"root backup MAIN carrier must not be a symlink: {name}",
                details={"root_dir": str(root_dir)},
            )
        if candidate.is_file():
            paths.append(str(candidate))
    return paths


def _inspect_published_extension_inventory(
    root_dir: Path,
    *,
    quiet: bool,
) -> RecoveryExtensionInventory:
    def validate_recovery_document(
        carrier: DiscoveredExtensionMainCarrier,
        document: ImportedRecoveryDocument,
        sign_pub: bytes,
    ) -> None:
        validate_published_recovery_document_carrier(
            path=carrier.path,
            expected_doc_id=document.doc_id,
            expected_doc_hash=document.doc_hash,
            expected_sign_pub=sign_pub,
            quiet=quiet,
        )

    return inspect_published_extension_inventory(
        root_dir,
        read_carrier_document=lambda carrier: _read_published_extension_carrier_document(
            carrier,
            quiet=quiet,
        ),
        validate_recovery_document_carrier=validate_recovery_document,
    )


def _read_published_extension_carrier_document(
    carrier: DiscoveredExtensionMainCarrier,
    *,
    quiet: bool,
) -> ImportedRecoveryDocument:
    ciphertext, auth_frames = scan_extension_carriers([str(carrier.path)], quiet=quiet)
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    return ImportedRecoveryDocument(
        doc_id=doc_id,
        doc_hash=doc_hash,
        ciphertext=ciphertext,
        auth_frames=tuple(auth_frames),
        source_label=str(carrier.path),
    )


def scan_extension_carriers(paths: list[str], *, quiet: bool) -> tuple[bytes, list[Frame]]:
    if not paths:
        raise ValueError("no extension MAIN carriers were provided")
    frames = recovery_frames_from_scan(paths, quiet=quiet)
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


def _sorted_chunk_items(chunk_map: dict[bytes, bytes]) -> tuple[tuple[bytes, bytes], ...]:
    return sorted_chunk_items(chunk_map)


def _reconstruct_extension_state(
    *,
    root_dir: Path,
    manifest: EnvelopeManifest,
    payload: bytes,
    root_doc_hash: bytes,
    passphrase: str,
    expected_sign_pub: bytes | None,
    root_auth_status: str | None,
    blocking_issues: list[dict[str, object]],
    inventory: RecoveryExtensionInventory,
    new_chain_chunking: ExtensionChunkingProfile,
    quiet: bool,
) -> tuple[
    tuple[LogicalFileState, ...] | None,
    int | None,
    str | None,
    bool | None,
    bytes | None,
    int | None,
    ExtensionChunkingProfile | None,
    tuple[tuple[bytes, bytes], ...],
    tuple[dict[str, object], ...],
    str | None,
    bool | None,
    tuple[int, ...],
    str,
]:
    if expected_sign_pub is None:
        raise ValueError("root backup manifest is missing an embedded signing seed")

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
    input_kind = "extended_root" if discovered_extension_dirs else "standalone_root"
    available_extensions = _available_extensions_from_recovery_chain(chain_inspection)

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
            if issue.get("code") not in {"EXTENSION_LAYOUT_INVALID", "CHAIN_INVALID"}
        ]
        blocking_issues.insert(
            0,
            _blocking_issue(
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
            (),
            available_extensions,
            validated_head_auth_status,
            validated_head_root_authority_verified,
            discovered_extension_dirs,
            input_kind,
        )

    if not chain_inspection.links or chain_inspection.latest_state is None:
        return (
            root_state,
            chain_inspection.validated_head_index,
            chain_inspection.validated_head_doc_hash,
            True,
            root_doc_hash,
            1,
            new_chain_chunking,
            _sorted_chunk_items(build_chain_available_chunks(root_state, new_chain_chunking)),
            available_extensions,
            chain_inspection.validated_head_auth_status,
            chain_inspection.validated_head_root_authority_verified,
            discovered_extension_dirs,
            input_kind,
        )

    locked_chunking = chain_inspection.locked_chunking
    if locked_chunking is None:
        raise ValueError("extension chain requires a locked chunking profile")

    return (
        chain_inspection.latest_state,
        chain_inspection.validated_head_index,
        chain_inspection.validated_head_doc_hash,
        True,
        chain_inspection.links[-1].link.doc_hash,
        chain_inspection.validated_head_index + 1,
        locked_chunking,
        _sorted_chunk_items(
            build_chain_available_chunks(
                root_state,
                locked_chunking,
                extensions=tuple(item.link for item in chain_inspection.links),
            )
        ),
        available_extensions,
        chain_inspection.validated_head_auth_status,
        chain_inspection.validated_head_root_authority_verified,
        discovered_extension_dirs,
        input_kind,
    )


def _manifest_summary_payload(manifest: EnvelopeManifest) -> dict[str, object]:
    return {
        "format_version": manifest.format_version,
        "input_origin": manifest.input_origin,
        "input_roots": list(manifest.input_roots),
        "sealed": manifest.sealed,
        "payload_codec": manifest.payload_codec,
        "payload_raw_len": manifest.payload_raw_len,
        "file_count": len(manifest.files),
    }


def _blocking_issue(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "details": details or {},
    }


def _default_chunking_profile(args: ExtendArgs) -> ExtensionChunkingProfile:
    try:
        return _default_chunking_profile_from_config(args)
    except ValueError as exc:
        raise ApiCommandError(
            code=api_codes.INVALID_INPUT,
            message=str(exc),
            details={"config": args.config},
        ) from exc


def _default_chunking_profile_from_config(args: ExtendArgs) -> ExtensionChunkingProfile:
    configured = load_app_config(args.config, paper_size=args.paper).extension_chunking
    return ExtensionChunkingProfile(
        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
        target_size=configured.target_size,
        min_size=configured.min_size,
        max_size=configured.max_size,
    )
