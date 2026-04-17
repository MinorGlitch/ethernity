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

"""Extension-aware recovery helpers for root-directory chain replay."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from pypdf import PdfReader

from ethernity.cli.features.recover.key_recovery import _resolve_auth_payload
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.crypto import _doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.io.frames import (
    _dedupe_frames,
    _frames_from_fallback_lines,
    _recovery_frames_from_scan,
    _split_main_and_auth_frames,
)
from ethernity.cli.shared.io.recovery_pdf import extract_pdf_fallback_lines_from_pdf
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.crypto import decrypt_bytes
from ethernity.crypto.signing import AuthPayload, derive_public_key
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import Frame
from ethernity.extensions.build import build_virtual_chunk_source, default_extension_chunker
from ethernity.extensions.chain import (
    ExtensionChainLink,
    LogicalFileState,
    extract_root_logical_state,
    reconstruct_latest_logical_state,
    validate_extension_chain,
)
from ethernity.extensions.discovery import (
    DiscoveredExtensionDirectory,
    discover_validated_extension_directories,
    payload_main_carriers,
)
from ethernity.formats.envelope_codec import decode_any_envelope, extract_payloads
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile
from ethernity.formats.extension_envelope import ExtensionEnvelope

if TYPE_CHECKING:
    from ethernity.cli.features.recover.planning import RecoveryPlan


@dataclass(frozen=True)
class DiscoveredRecoveryExtension:
    index: int
    dir_name: str
    doc_id_hex: str
    doc_hash: bytes
    ciphertext: bytes
    auth_frames: tuple[Frame, ...]


@dataclass(frozen=True)
class DecodedExtensionLink:
    link: ExtensionChainLink
    auth_payload: AuthPayload | None
    auth_status: str
    root_authority_verified: bool


@dataclass(frozen=True)
class ChainRecoveryResult:
    manifest: EnvelopeManifest
    extracted: tuple[tuple[ManifestFile, bytes], ...]
    selected_extension_index: int | None
    selected_extension_doc_hash: str | None


@dataclass(frozen=True)
class RootManifestAuthority:
    embedded_sign_pub: bytes | None
    mismatch: bool


@dataclass(frozen=True)
class ScannedExtensionCarriers:
    index: int
    dir_name: str
    doc_id_hex: str
    main_paths: tuple[str, ...]
    doc_hash: bytes
    ciphertext: bytes
    auth_frames: tuple[Frame, ...]


_ROOT_MAIN_FILENAMES = ("qr_document.pdf", "recovery_document.pdf")


def detect_recovery_root_dir(scan_paths: list[str]) -> Path | None:
    if len(scan_paths) != 1:
        return None
    candidate = Path(scan_paths[0]).expanduser()
    if candidate.is_symlink():
        return None
    if not candidate.is_dir():
        return None
    try:
        scan_paths = validated_root_recovery_scan_paths(candidate)
    except ValueError:
        return None
    if scan_paths:
        return candidate
    return None


def recover_chain_entries(
    plan: "RecoveryPlan", *, quiet: bool, debug: bool = False
) -> ChainRecoveryResult:
    if not plan.root_dir:
        raise ValueError("recovery chain replay requires a root_dir")

    root_dir = Path(plan.root_dir).expanduser()
    root_manifest, payload = decode_root_manifest(
        ciphertext=plan.ciphertext,
        passphrase=plan.passphrase,
        debug=debug,
    )
    root_sign_pub = validate_root_manifest_authority(root_manifest, plan.auth_payload)

    inventory = discover_recovery_extensions(
        root_dir,
        quiet=quiet,
        requested_index=plan.extension_index,
        requested_doc_hash=plan.extension_doc_hash,
    )
    if not inventory:
        return ChainRecoveryResult(
            manifest=root_manifest,
            extracted=tuple(extract_payloads(root_manifest, payload)),
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )

    if root_sign_pub is None:
        raise ValueError("root backup manifest is missing an embedded signing seed")
    links = _decode_validated_extension_prefix(
        inventory,
        manifest=root_manifest,
        payload=payload,
        root_doc_hash=plan.doc_hash,
        passphrase=plan.passphrase,
        expected_sign_pub=root_sign_pub,
        allow_unsigned=plan.allow_unsigned,
        strict_selection=_strict_extension_selection_requested(plan),
        quiet=quiet,
        debug=debug,
    )
    if not links:
        return ChainRecoveryResult(
            manifest=root_manifest,
            extracted=tuple(extract_payloads(root_manifest, payload)),
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )

    root_state = extract_root_logical_state(root_manifest, payload)
    locked_chunking = validate_extension_chain(
        root_doc_hash=plan.doc_hash,
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
        root_manifest,
        payload,
        root_doc_hash=plan.doc_hash,
        extensions=tuple(item.link for item in links),
        virtual_root_chunks=virtual_root_chunks,
    )
    latest_header = links[-1].link.document.header
    latest_manifest = _synthetic_manifest_from_state(
        root_manifest,
        latest_state,
        latest_input_origin=latest_header.input_origin,
        latest_input_roots=latest_header.input_roots,
    )
    state_by_path = {item.path: item.data for item in latest_state}
    extracted = tuple((entry, state_by_path[entry.path]) for entry in latest_manifest.files)
    return ChainRecoveryResult(
        manifest=latest_manifest,
        extracted=extracted,
        selected_extension_index=links[-1].link.document.header.index,
        selected_extension_doc_hash=links[-1].link.doc_hash.hex(),
    )


def discover_recovery_extensions(
    root_dir: Path,
    *,
    quiet: bool,
    requested_index: int | None = None,
    requested_doc_hash: str | None = None,
) -> tuple[DiscoveredRecoveryExtension, ...]:
    if requested_index is not None and requested_doc_hash is not None:
        raise ValueError("use either --extension-index or --extension-doc-hash, not both")
    if requested_index == 0:
        return ()

    requested_doc_hash_bytes = (
        None if requested_doc_hash is None else _parse_extension_doc_hash(requested_doc_hash)
    )
    if requested_index is not None and requested_index < 0:
        raise ValueError("--extension-index must be >= 0")

    discovery = discover_validated_extension_directories(root_dir)
    discovered = discovery.directories
    if discovery.first_invalid_message is not None and not discovered:
        raise ValueError(discovery.first_invalid_message)

    if requested_index is not None:
        if requested_index > len(discovered):
            if discovery.first_invalid_message is not None:
                raise ValueError(discovery.first_invalid_message)
            raise ValueError(f"extension index {requested_index} was not found")
        discovered = discovered[:requested_index]

    inventory: list[DiscoveredRecoveryExtension] = []
    for item in discovered:
        discovered_extension = _discover_recovery_extension(item, quiet=quiet)
        inventory.append(discovered_extension)
        if (
            requested_doc_hash_bytes is not None
            and discovered_extension.doc_hash == requested_doc_hash_bytes
        ):
            return tuple(inventory)

    if requested_doc_hash is not None:
        if discovery.first_invalid_message is not None:
            raise ValueError(discovery.first_invalid_message)
        normalized = requested_doc_hash.strip().lower()
        raise ValueError(f"extension doc_hash {normalized} was not found")

    return tuple(inventory)


def _discover_recovery_extension(
    item: DiscoveredExtensionDirectory,
    *,
    quiet: bool,
) -> DiscoveredRecoveryExtension:
    scanned = scan_discovered_extension_directory(item, quiet=quiet)
    return DiscoveredRecoveryExtension(
        index=scanned.index,
        dir_name=scanned.dir_name,
        doc_id_hex=scanned.doc_id_hex,
        doc_hash=scanned.doc_hash,
        ciphertext=scanned.ciphertext,
        auth_frames=scanned.auth_frames,
    )


def _scan_main_ciphertext(paths: list[str], *, quiet: bool) -> bytes:
    ciphertext, _auth_frames = scan_extension_carriers(paths, quiet=quiet)
    return ciphertext


def _scan_single_extension_carrier(path: str, *, quiet: bool) -> tuple[bytes, tuple[Frame, ...]]:
    try:
        frames = _recovery_frames_from_scan([path], quiet=quiet)
    except ValueError as exc:
        if not _should_try_recovery_fallback(path, exc):
            raise ValueError(
                f"{Path(path).name} MAIN carrier is not independently recoverable: {exc}"
            ) from exc
        try:
            fallback_lines = extract_pdf_fallback_lines_from_pdf(PdfReader(path))
            if not fallback_lines:
                raise ValueError("fallback sections were not found in the recovery document")
            frames = _frames_from_fallback_lines(
                fallback_lines,
                allow_invalid_auth=False,
                quiet=quiet,
            )
        except Exception as fallback_exc:
            raise ValueError(
                f"{Path(path).name} MAIN carrier is not independently recoverable: {fallback_exc}"
            ) from fallback_exc

    deduped = _dedupe_frames(frames)
    main_frames, auth_frames = _split_main_and_auth_frames(deduped)
    try:
        ciphertext = reassemble_payload(main_frames)
    except ValueError as exc:
        raise ValueError(
            f"{Path(path).name} MAIN carrier is not independently recoverable: {exc}"
        ) from exc
    return ciphertext, tuple(auth_frames)


def _should_try_recovery_fallback(path: str, exc: Exception) -> bool:
    name = Path(path).name
    return (
        name == "recovery_document.pdf" or name.startswith("recovery_document-")
    ) and "no QR codes found in scan inputs" in str(exc)


def scan_extension_carriers(paths: list[str], *, quiet: bool) -> tuple[bytes, list[Frame]]:
    if not paths:
        raise ValueError("no extension MAIN carriers were provided")

    expected_ciphertext: bytes | None = None
    expected_auth_frames: tuple[Frame, ...] | None = None
    first_valid_path: str | None = None
    first_error: ValueError | None = None
    baseline_name = Path(paths[0]).name

    for path in paths:
        try:
            ciphertext, auth_tuple = _scan_single_extension_carrier(path, quiet=quiet)
        except ValueError as exc:
            if first_error is None:
                first_error = exc
            continue
        if expected_ciphertext is None:
            expected_ciphertext = ciphertext
            expected_auth_frames = auth_tuple
            first_valid_path = Path(path).name
            continue
        if ciphertext != expected_ciphertext:
            raise ValueError(
                f"{Path(path).name} MAIN carrier does not match {first_valid_path or baseline_name}"
            )
        if auth_tuple != expected_auth_frames:
            raise ValueError(
                f"{Path(path).name} AUTH payloads do not match {first_valid_path or baseline_name}"
            )

    if expected_ciphertext is None:
        if first_error is not None:
            raise first_error
        raise ValueError("no extension MAIN carriers were provided")
    return expected_ciphertext, list(expected_auth_frames or ())


def _strict_extension_selection_requested(plan: "RecoveryPlan") -> bool:
    return plan.extension_index is not None or plan.extension_doc_hash is not None


def _decode_validated_extension_prefix(
    inventory: tuple[DiscoveredRecoveryExtension, ...],
    *,
    manifest: EnvelopeManifest,
    payload: bytes,
    root_doc_hash: bytes,
    passphrase: str,
    expected_sign_pub: bytes,
    allow_unsigned: bool,
    strict_selection: bool,
    quiet: bool,
    debug: bool,
) -> tuple[DecodedExtensionLink, ...]:
    decoded_prefix: list[DecodedExtensionLink] = []
    root_state = extract_root_logical_state(manifest, payload)

    for item in inventory:
        try:
            decoded = decode_authenticated_extension_link(
                item,
                passphrase=passphrase,
                expected_sign_pub=expected_sign_pub,
                allow_unsigned=allow_unsigned,
                quiet=quiet,
                debug=debug,
            )
            candidate_prefix = (*decoded_prefix, decoded)
            locked_chunking = validate_extension_chain(
                root_doc_hash=root_doc_hash,
                extensions=tuple(entry.link for entry in candidate_prefix),
            )
            virtual_root_chunks = (
                {}
                if locked_chunking is None
                else build_virtual_chunk_source(
                    tuple(entry.data for entry in root_state),
                    chunking=locked_chunking,
                    chunker=default_extension_chunker,
                )
            )
            reconstruct_latest_logical_state(
                manifest,
                payload,
                root_doc_hash=root_doc_hash,
                extensions=tuple(entry.link for entry in candidate_prefix),
                virtual_root_chunks=virtual_root_chunks,
            )
        except ValueError:
            if strict_selection:
                raise
            break
        decoded_prefix.append(decoded)

    return tuple(decoded_prefix)


def scan_discovered_extension_directory(
    item: DiscoveredExtensionDirectory,
    *,
    quiet: bool,
    scanner: Callable[[list[str]], tuple[bytes, list[Frame]]] | None = None,
) -> ScannedExtensionCarriers:
    main_paths = tuple(str(carrier.path) for carrier in payload_main_carriers(item.main_carriers))
    scan = scanner or (lambda paths: scan_extension_carriers(paths, quiet=quiet))
    ciphertext, auth_frames = scan(list(main_paths))
    doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)
    if doc_id.hex() != item.doc_id_hex:
        raise ValueError(
            f"extension {item.dir_name} MAIN carriers do not match the filename doc_id"
        )
    return ScannedExtensionCarriers(
        index=item.index,
        dir_name=item.dir_name,
        doc_id_hex=item.doc_id_hex,
        main_paths=main_paths,
        doc_hash=doc_hash,
        ciphertext=ciphertext,
        auth_frames=tuple(auth_frames),
    )


def decode_root_manifest(
    *,
    ciphertext: bytes,
    passphrase: str,
    debug: bool,
) -> tuple[EnvelopeManifest, bytes]:
    plaintext = decrypt_bytes(ciphertext, passphrase=passphrase, debug=debug)
    version, decoded = decode_any_envelope(plaintext)
    if version != 1 or not isinstance(decoded, tuple) or len(decoded) != 2:
        raise ValueError("root backup must decode as Envelope V1")
    manifest, payload = decoded
    if not isinstance(manifest, EnvelopeManifest) or not isinstance(payload, bytes):
        raise ValueError("root backup did not decode correctly")
    return manifest, payload


def _decode_root_manifest(
    *,
    ciphertext: bytes,
    passphrase: str,
    debug: bool,
) -> tuple[EnvelopeManifest, bytes]:
    return decode_root_manifest(ciphertext=ciphertext, passphrase=passphrase, debug=debug)


def resolve_root_manifest_authority(
    manifest: EnvelopeManifest,
    auth_payload: AuthPayload | None,
) -> RootManifestAuthority:
    if manifest.signing_seed is None:
        return RootManifestAuthority(embedded_sign_pub=None, mismatch=False)

    embedded_sign_pub = derive_public_key(manifest.signing_seed)
    mismatch = auth_payload is not None and auth_payload.sign_pub != embedded_sign_pub
    return RootManifestAuthority(embedded_sign_pub=embedded_sign_pub, mismatch=mismatch)


def validate_root_manifest_authority(
    manifest: EnvelopeManifest,
    auth_payload: AuthPayload | None,
) -> bytes | None:
    """Validate that any verified root AUTH matches the embedded signing seed."""

    authority = resolve_root_manifest_authority(manifest, auth_payload)
    if authority.mismatch:
        raise ApiCommandError(
            code=api_codes.ROOT_AUTHORITY_MISMATCH,
            message="embedded signing seed does not match the verified root AUTH authority",
        )
    return authority.embedded_sign_pub


def decode_authenticated_extension_link(
    item: DiscoveredRecoveryExtension,
    *,
    passphrase: str,
    expected_sign_pub: bytes | None,
    allow_unsigned: bool,
    quiet: bool,
    debug: bool,
) -> DecodedExtensionLink:
    auth_payload, auth_status = _resolve_auth_payload(
        list(item.auth_frames),
        doc_id=bytes.fromhex(item.doc_id_hex),
        doc_hash=item.doc_hash,
        allow_unsigned=False,
        require_auth=True,
        quiet=quiet,
    )
    root_authority_verified = False
    if auth_payload is not None and expected_sign_pub is not None:
        if auth_payload.sign_pub != expected_sign_pub:
            raise ValueError(
                f"extension {item.dir_name} AUTH signing key does not match root authority"
            )
        else:
            root_authority_verified = True
    plaintext = decrypt_bytes(item.ciphertext, passphrase=passphrase, debug=debug)
    version, decoded = decode_any_envelope(plaintext)
    if version != 2 or not isinstance(decoded, ExtensionEnvelope):
        raise ValueError(f"extension {item.dir_name} did not decode as an extension envelope")
    return DecodedExtensionLink(
        link=ExtensionChainLink(doc_hash=item.doc_hash, document=decoded),
        auth_payload=auth_payload,
        auth_status=auth_status,
        root_authority_verified=root_authority_verified,
    )


def _parse_extension_doc_hash(value: str) -> bytes:
    normalized = value.strip().lower()
    try:
        requested_bytes = bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError("--extension-doc-hash must be lowercase hex") from exc
    if len(requested_bytes) != 32:
        raise ValueError("--extension-doc-hash must be a 32-byte hex value")
    return requested_bytes


def _synthetic_manifest_from_state(
    root_manifest: EnvelopeManifest,
    state: tuple[LogicalFileState, ...],
    *,
    latest_input_origin: str,
    latest_input_roots: tuple[str, ...],
) -> EnvelopeManifest:
    return EnvelopeManifest(
        format_version=root_manifest.format_version,
        created_at=root_manifest.created_at,
        sealed=root_manifest.sealed,
        signing_seed=root_manifest.signing_seed,
        files=tuple(
            ManifestFile(
                path=item.path,
                size=item.size,
                sha256=item.sha256,
                mtime=item.mtime,
            )
            for item in state
        ),
        input_origin=latest_input_origin,
        input_roots=latest_input_roots,
        payload_codec="raw",
        payload_raw_len=None,
    )


def validated_root_recovery_scan_paths(root_dir: Path) -> list[str]:
    paths: list[str] = []
    for name in _ROOT_MAIN_FILENAMES:
        candidate = root_dir / name
        if candidate.is_symlink():
            raise ValueError(f"root backup MAIN carrier must not be a symlink: {name}")
        if candidate.is_file():
            paths.append(str(candidate))
    return paths


__all__ = [
    "ChainRecoveryResult",
    "DecodedExtensionLink",
    "DiscoveredRecoveryExtension",
    "decode_authenticated_extension_link",
    "detect_recovery_root_dir",
    "discover_recovery_extensions",
    "recover_chain_entries",
    "scan_extension_carriers",
    "validate_root_manifest_authority",
    "validated_root_recovery_scan_paths",
]
