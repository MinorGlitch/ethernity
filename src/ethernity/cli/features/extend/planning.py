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

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ethernity.cli.features.extend.scope import (
    SelectedExtendScope,
    empty_scope_inspection_payload,
    load_selected_scope,
    summarize_scope_diff,
)
from ethernity.cli.features.recover.chain import (
    DecodedExtensionLink,
    DiscoveredRecoveryExtension,
    decode_authenticated_extension_link,
    decode_root_manifest as _decode_root_manifest_shared,
    resolve_root_manifest_authority,
    scan_discovered_extension_directory,
    scan_extension_carriers,
    validated_root_recovery_scan_paths,
)
from ethernity.cli.features.recover.planning import RecoveryInspection, inspect_recovery_inputs
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.io.fallback_parser import format_fallback_error
from ethernity.cli.shared.io.frames import (
    _frame_from_fallback,
    _frames_from_payloads,
    _recovery_frames_from_scan,
    _shard_frames_from_scan,
    format_shard_input_error,
)
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.paths import expanduser_cli_paths
from ethernity.cli.shared.types import ExtendArgs
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.framing import Frame
from ethernity.extensions.build import build_virtual_chunk_source, default_extension_chunker
from ethernity.extensions.chain import (
    LogicalFileState,
    extract_root_logical_state,
    reconstruct_latest_logical_state,
    validate_extension_chain,
)
from ethernity.extensions.discovery import (
    discover_validated_extension_directories,
    require_backup_root_dir,
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
    resolved_passphrase: str | None
    root_doc_hash: bytes | None
    parent_doc_hash: bytes | None
    next_index: int | None
    signing_seed: bytes | None
    chunking: ExtensionChunkingProfile | None


@dataclass(frozen=True)
class _DiscoveredExtensionCiphertext:
    index: int
    dir_name: str
    doc_id_hex: str
    main_paths: tuple[str, ...]
    doc_hash_hex: str | None
    doc_hash: bytes | None
    ciphertext: bytes | None
    auth_frames: tuple[Frame, ...]


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
    input_kind = "standalone_root"
    extension_inventory: tuple[_DiscoveredExtensionCiphertext, ...] = ()
    discovery = discover_validated_extension_directories(root_dir)
    if discovery.first_invalid_message is not None:
        blocking_issues.append(
            {
                "code": "EXTENSION_LAYOUT_INVALID",
                "message": discovery.first_invalid_message,
                "details": {"root_dir": str(root_dir)},
            }
        )
    else:
        discovered = discovery.directories
        try:
            discovered_extension_dirs = tuple(item.index for item in discovered)
            extension_inventory = _inspect_discovered_extensions(discovered, quiet=args.quiet)
            available_extensions = tuple(
                {
                    "dir_name": item.dir_name,
                    "doc_id": item.doc_id_hex,
                    "doc_hash": item.doc_hash_hex,
                }
                for item in extension_inventory
            )
            if discovered:
                input_kind = "extended_root"
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

    root_inspection = _inspect_root_recovery(root_dir, args)
    blocking_issues.extend(dict(item) for item in root_inspection.blocking_issues)

    doc_id_hex = root_inspection.doc_id.hex()
    doc_hash_hex = root_inspection.doc_hash.hex()
    chain_id_hex = derive_chain_id(root_inspection.doc_hash).hex()
    source_summary: dict[str, object] | None = None
    validated_head_index: int | None = None
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

    current_state: tuple[LogicalFileState, ...] | None = None
    if root_inspection.unlock.satisfied and root_inspection.unlock.resolved_passphrase is not None:
        try:
            manifest, payload = _decode_root_manifest(
                root_inspection.ciphertext,
                passphrase=root_inspection.unlock.resolved_passphrase,
            )
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
                authority = resolve_root_manifest_authority(manifest, root_inspection.auth_payload)
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

                    if extension_inventory and not manifest.sealed:
                        (
                            current_state,
                            validated_head_index,
                            ancestry_valid,
                            parent_doc_hash,
                            next_index,
                            chunking,
                            available_extensions,
                            validated_head_auth_status,
                            validated_head_root_authority_verified,
                        ) = _reconstruct_extension_state(
                            manifest=manifest,
                            payload=payload,
                            root_doc_hash=root_inspection.doc_hash,
                            extension_inventory=extension_inventory,
                            passphrase=root_inspection.unlock.resolved_passphrase,
                            blocking_issues=blocking_issues,
                        )
                    else:
                        parent_doc_hash = root_inspection.doc_hash
                        next_index = 1
                        chunking = _default_chunking_profile()

            if current_state is not None and loaded_scope is not None:
                diff = summarize_scope_diff(current_state, loaded_scope)
                diff_summary = diff.to_payload()
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
                    "UNLOCK_FAILED",
                    str(exc),
                    details={"stage": "decrypt"},
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
            "satisfied": root_inspection.unlock.satisfied,
        },
        discovered_extension_dirs=discovered_extension_dirs,
        validated_head_index=validated_head_index,
        available_extensions=available_extensions,
        ancestry_valid=ancestry_valid,
        validated_head_auth_status=validated_head_auth_status,
        validated_head_root_authority_verified=validated_head_root_authority_verified,
        signing_authority=signing_authority,
        selected_scope=selected_scope,
        diff_summary=diff_summary,
        blocking_issues=tuple(blocking_issues),
    )
    return ResolvedExtendState(
        inspection=inspection,
        loaded_scope=loaded_scope,
        current_state=current_state,
        resolved_passphrase=root_inspection.unlock.resolved_passphrase,
        root_doc_hash=root_doc_hash_bytes,
        parent_doc_hash=parent_doc_hash,
        next_index=next_index,
        signing_seed=signing_seed,
        chunking=chunking,
    )


def _inspect_root_recovery(root_dir: Path, args: ExtendArgs) -> RecoveryInspection:
    try:
        scan_paths = validated_root_recovery_scan_paths(root_dir)
    except ValueError as exc:
        raise ApiCommandError(
            code=api_codes.INVALID_INPUT,
            message=str(exc),
            details={"root_dir": str(root_dir)},
        ) from exc
    if not scan_paths:
        raise ApiCommandError(
            code=api_codes.NOT_FOUND,
            message="root backup documents not found in the writable backup directory",
            details={"root_dir": str(root_dir)},
        )
    frames = _recovery_frames_from_scan(scan_paths, quiet=args.quiet)
    shard_frames, shard_fallback_files, shard_payloads_file, shard_scan = (
        _shard_frames_from_extend_args(args, quiet=args.quiet)
    )
    return inspect_recovery_inputs(
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
            shard_frames.extend(_shard_frames_from_scan(shard_scan, quiet=quiet))
        except ValueError as exc:
            raise ValueError(format_shard_input_error(exc)) from exc
    if (
        args.shard_frames or shard_fallback_files or shard_payloads_file or shard_scan
    ) and not shard_frames:
        raise ValueError("no shard payloads found; check shard inputs and try again")
    return shard_frames, shard_fallback_files, shard_payloads_file, shard_scan


def _inspect_discovered_extensions(
    discovered: tuple[Any, ...],
    *,
    quiet: bool,
) -> tuple[_DiscoveredExtensionCiphertext, ...]:
    inventory: list[_DiscoveredExtensionCiphertext] = []
    for item in discovered:
        try:
            scanned = scan_discovered_extension_directory(
                item,
                quiet=quiet,
                scanner=lambda paths: scan_extension_carriers(paths, quiet=quiet),
            )
        except ValueError as exc:
            raise ValueError(
                f"extension {item.dir_name} MAIN carriers could not be reconstructed"
            ) from exc
        inventory.append(
            _DiscoveredExtensionCiphertext(
                index=scanned.index,
                dir_name=scanned.dir_name,
                doc_id_hex=scanned.doc_id_hex,
                main_paths=scanned.main_paths,
                doc_hash_hex=scanned.doc_hash.hex(),
                doc_hash=scanned.doc_hash,
                ciphertext=scanned.ciphertext,
                auth_frames=scanned.auth_frames,
            )
        )
    return tuple(inventory)


def _scan_main_ciphertext(paths: list[str], *, quiet: bool) -> bytes:
    ciphertext, _auth_frames = scan_extension_carriers(paths, quiet=quiet)
    return ciphertext


def _decode_root_manifest(ciphertext: bytes, *, passphrase: str) -> tuple[EnvelopeManifest, bytes]:
    return _decode_root_manifest_shared(ciphertext=ciphertext, passphrase=passphrase, debug=False)


def _reconstruct_extension_state(
    *,
    manifest: EnvelopeManifest,
    payload: bytes,
    root_doc_hash: bytes,
    extension_inventory: tuple[_DiscoveredExtensionCiphertext, ...],
    passphrase: str,
    blocking_issues: list[dict[str, object]],
) -> tuple[
    tuple[LogicalFileState, ...],
    int | None,
    bool | None,
    bytes | None,
    int | None,
    ExtensionChunkingProfile | None,
    tuple[dict[str, object], ...],
    str | None,
    bool | None,
]:
    links: list[DecodedExtensionLink] = []
    available_extensions: list[dict[str, object]] = []
    expected_sign_pub = derive_public_key(manifest.signing_seed) if manifest.signing_seed else None
    for item in extension_inventory:
        if item.ciphertext is None or item.doc_hash is None:
            blocking_issues.append(
                _blocking_issue(
                    "CHAIN_INVALID",
                    f"extension {item.dir_name} MAIN carriers could not be reconstructed",
                    details={"dir_name": item.dir_name},
                )
            )
            root_state = extract_root_logical_state(manifest, payload)
            return (
                root_state,
                None,
                False,
                None,
                None,
                None,
                tuple(available_extensions),
                None,
                None,
            )
        discovered = DiscoveredRecoveryExtension(
            index=item.index,
            dir_name=item.dir_name,
            doc_id_hex=item.doc_id_hex,
            doc_hash=item.doc_hash,
            ciphertext=item.ciphertext,
            auth_frames=item.auth_frames,
        )
        try:
            decoded_link = decode_authenticated_extension_link(
                discovered,
                passphrase=passphrase,
                expected_sign_pub=expected_sign_pub,
                allow_unsigned=False,
                quiet=True,
                debug=False,
            )
        except ValueError as exc:
            blocking_issues.append(
                _blocking_issue(
                    "CHAIN_INVALID",
                    str(exc),
                    details={"dir_name": item.dir_name},
                )
            )
            root_state = extract_root_logical_state(manifest, payload)
            return (
                root_state,
                None,
                False,
                None,
                None,
                None,
                tuple(available_extensions),
                None,
                None,
            )
        links.append(decoded_link)
        available_extensions.append(
            {
                "dir_name": item.dir_name,
                "doc_id": item.doc_id_hex,
                "doc_hash": item.doc_hash.hex(),
                "auth_status": decoded_link.auth_status,
                "root_authority_verified": decoded_link.root_authority_verified,
            }
        )

    root_state = extract_root_logical_state(manifest, payload)
    try:
        locked_chunking = validate_extension_chain(
            root_doc_hash=root_doc_hash,
            extensions=tuple(item.link for item in links),
        )
        virtual_root_chunks = (
            {}
            if locked_chunking is None
            else build_virtual_chunk_source(
                tuple(item.data for item in root_state),
                chunking=locked_chunking,
                chunker=default_extension_chunker,
            )
        )
        latest_state = reconstruct_latest_logical_state(
            manifest,
            payload,
            root_doc_hash=root_doc_hash,
            extensions=tuple(item.link for item in links),
            virtual_root_chunks=virtual_root_chunks,
        )
    except ValueError as exc:
        blocking_issues.append(
            _blocking_issue(
                "CHAIN_INVALID",
                str(exc),
            )
        )
        return root_state, None, False, None, None, None, tuple(available_extensions), None, None

    return (
        latest_state,
        len(links),
        True,
        links[-1].link.doc_hash,
        len(links) + 1,
        locked_chunking,
        tuple(available_extensions),
        links[-1].auth_status,
        links[-1].root_authority_verified,
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


def _default_chunking_profile() -> ExtensionChunkingProfile:
    return ExtensionChunkingProfile(
        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
        target_size=64 * 1024,
        min_size=16 * 1024,
        max_size=256 * 1024,
    )
