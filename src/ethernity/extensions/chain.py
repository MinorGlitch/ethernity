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

"""Chain validation and logical-state reconstruction for extension envelopes."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ethernity.core.bounds import (
    MAX_DECOMPRESSED_PAYLOAD_BYTES,
    MAX_MANIFEST_FILES,
    MAX_RECOVERY_DECODED_CHUNK_BYTES,
)
from ethernity.core.validation import require_bytes
from ethernity.crypto.signing import (
    AUTH_VERSION,
    DOC_HASH_LEN,
    ED25519_PUB_LEN,
    ED25519_SIG_LEN,
    AuthPayload,
    verify_auth,
)
from ethernity.formats.envelope_codec import extract_payloads
from ethernity.formats.envelope_types import EnvelopeManifest
from ethernity.formats.extension_chunking import (
    default_extension_chunker,
)
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
    ExtensionEnvelope,
    ExtensionFile,
    _reconstruct_extension_file_bytes,
)

_VALIDATED_CHAIN_STATE_SEAL = object()

ReplayFailurePhase = Literal["auth", "lineage", "chunks", "limits", "files"]


@dataclass(frozen=True)
class _StructuralExtensionChainLink:
    """One extension document plus its ciphertext hash identity.

    This type validates structural ancestry only; it does not prove AUTH or root-authority trust.
    Use AuthenticatedExtensionChainLink for recovery paths that will replay user-supplied links.
    """

    doc_hash: bytes
    document: ExtensionEnvelope

    def __post_init__(self) -> None:
        if not isinstance(self.doc_hash, (bytes, bytearray)) or len(self.doc_hash) != 32:
            raise ValueError("extension chain link doc_hash must be 32 bytes")
        object.__setattr__(self, "doc_hash", bytes(self.doc_hash))
        if not isinstance(self.document, ExtensionEnvelope):
            raise ValueError("extension chain link document must be an ExtensionEnvelope")


@dataclass(frozen=True)
class AuthenticatedExtensionChainLink(_StructuralExtensionChainLink):
    """Extension link whose AUTH payload is verified against the root signing authority."""

    auth_payload: AuthPayload
    expected_sign_pub: bytes
    auth_status: str = "verified"
    root_authority_verified: bool = True

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.auth_payload, AuthPayload):
            raise ValueError("authenticated extension link requires an AuthPayload")
        if self.auth_payload.version != AUTH_VERSION:
            raise ValueError("authenticated extension AUTH version is unsupported")

        auth_doc_hash = require_bytes(
            self.auth_payload.doc_hash,
            DOC_HASH_LEN,
            label="doc_hash",
            prefix="extension AUTH ",
        )
        auth_sign_pub = require_bytes(
            self.auth_payload.sign_pub,
            ED25519_PUB_LEN,
            label="sign_pub",
            prefix="extension AUTH ",
        )
        auth_signature = require_bytes(
            self.auth_payload.signature,
            ED25519_SIG_LEN,
            label="signature",
            prefix="extension AUTH ",
        )
        expected_sign_pub = require_bytes(
            self.expected_sign_pub,
            ED25519_PUB_LEN,
            label="expected_sign_pub",
        )
        object.__setattr__(
            self,
            "auth_payload",
            AuthPayload(
                version=AUTH_VERSION,
                doc_hash=auth_doc_hash,
                sign_pub=auth_sign_pub,
                signature=auth_signature,
            ),
        )
        object.__setattr__(self, "expected_sign_pub", expected_sign_pub)

        if auth_doc_hash != self.doc_hash:
            raise ValueError("extension AUTH doc_hash does not match chain link doc_hash")
        if auth_sign_pub != expected_sign_pub:
            raise ValueError("extension AUTH signing key does not match root authority")
        if self.auth_status != "verified":
            raise ValueError("extension AUTH status must be verified")
        if self.root_authority_verified is not True:
            raise ValueError("extension root authority must be verified")
        if not verify_auth(auth_doc_hash, sign_pub=auth_sign_pub, signature=auth_signature):
            raise ValueError("extension AUTH signature is invalid")


@dataclass(frozen=True)
class LogicalFileState:
    """One reconstructed logical file in the latest chain state."""

    path: str
    size: int
    sha256: bytes
    mtime: int | None
    data: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.data, (bytes, bytearray)):
            raise ValueError("logical file data must be bytes")
        raw = bytes(self.data)
        if len(raw) != self.size:
            raise ValueError("logical file size does not match data length")
        if hashlib.sha256(raw).digest() != self.sha256:
            raise ValueError("logical file sha256 does not match data")
        object.__setattr__(self, "data", raw)

    @classmethod
    def _from_verified_extension(
        cls,
        file_entry: ExtensionFile,
        data: bytes,
    ) -> LogicalFileState:
        state = object.__new__(cls)
        object.__setattr__(state, "path", file_entry.path)
        object.__setattr__(state, "size", file_entry.size)
        object.__setattr__(state, "sha256", file_entry.sha256)
        object.__setattr__(state, "mtime", file_entry.mtime)
        object.__setattr__(state, "data", data)
        return state


class ExtensionReplayError(ValueError):
    """One-pass replay failure with the exact failing and last validated heads."""

    def __init__(
        self,
        message: str,
        *,
        failure_phase: ReplayFailurePhase,
        failing_index: int,
        failing_hash: bytes,
        last_validated_head_index: int,
        last_validated_head_hash: bytes,
    ) -> None:
        super().__init__(message)
        if failure_phase not in {"auth", "lineage", "chunks", "limits", "files"}:
            raise ValueError(f"unsupported extension replay failure phase: {failure_phase}")
        if (
            isinstance(failing_index, bool)
            or not isinstance(failing_index, int)
            or failing_index < 1
        ):
            raise ValueError("extension replay failing_index must be positive")
        if (
            isinstance(last_validated_head_index, bool)
            or not isinstance(last_validated_head_index, int)
            or last_validated_head_index < 0
        ):
            raise ValueError("extension replay last validated head index must be non-negative")
        self.failure_phase = failure_phase
        self.failing_index = failing_index
        self.failing_hash = require_bytes(failing_hash, 32, label="failing_hash")
        self.last_validated_head_index = last_validated_head_index
        self.last_validated_head_hash = require_bytes(
            last_validated_head_hash,
            32,
            label="last_validated_head_hash",
        )


@dataclass(frozen=True, init=False)
class ValidatedChainState:
    """Authenticated replay result accepted by the extension builder.

    Instances are minted only by authenticated replay; callers cannot
    assemble a trusted state from independently supplied chunk IDs or lineage fields.
    """

    root_doc_hash: bytes
    head_doc_hash: bytes
    head_index: int
    chunking: ExtensionChunkingProfile
    logical_state: tuple[LogicalFileState, ...]
    available_chunks: tuple[tuple[bytes, bytes], ...]
    _seal: object

    def __init__(self) -> None:
        raise TypeError("ValidatedChainState can only be created by authenticated chain replay")


def _replay_authenticated_chain_state(
    manifest: EnvelopeManifest,
    payload: bytes,
    *,
    root_doc_hash: bytes,
    root_auth_payload: AuthPayload,
    expected_sign_pub: bytes,
    extensions: Sequence[AuthenticatedExtensionChainLink],
    root_chunking: ExtensionChunkingProfile,
) -> ValidatedChainState:
    """Authenticate and replay a complete chain into an append-capable state."""

    if not isinstance(root_auth_payload, AuthPayload):
        raise ValueError("authenticated chain replay requires a root AUTH payload")
    if root_auth_payload.version != AUTH_VERSION:
        raise ValueError("root AUTH version is unsupported")
    authenticated_root_doc_hash = require_bytes(
        root_auth_payload.doc_hash,
        DOC_HASH_LEN,
        label="doc_hash",
        prefix="root AUTH ",
    )
    root_sign_pub = require_bytes(
        root_auth_payload.sign_pub,
        ED25519_PUB_LEN,
        label="sign_pub",
        prefix="root AUTH ",
    )
    root_signature = require_bytes(
        root_auth_payload.signature,
        ED25519_SIG_LEN,
        label="signature",
        prefix="root AUTH ",
    )
    trusted_sign_pub = require_bytes(
        expected_sign_pub,
        ED25519_PUB_LEN,
        label="expected_sign_pub",
    )
    expected_root_doc_hash = require_bytes(
        root_doc_hash,
        DOC_HASH_LEN,
        label="root_doc_hash",
    )
    if authenticated_root_doc_hash != expected_root_doc_hash:
        raise ValueError("root AUTH doc_hash does not match the replayed root document")
    if root_sign_pub != trusted_sign_pub:
        raise ValueError("root AUTH signing key does not match the expected root authority")
    if not verify_auth(
        authenticated_root_doc_hash,
        sign_pub=root_sign_pub,
        signature=root_signature,
    ):
        raise ValueError("root AUTH signature is invalid")

    logical_state = reconstruct_authenticated_latest_logical_state(
        manifest,
        payload,
        root_doc_hash=authenticated_root_doc_hash,
        expected_sign_pub=trusted_sign_pub,
        extensions=extensions,
    )
    chunking = extensions[0].document.header.chunking if extensions else root_chunking
    root_state = extract_root_logical_state(manifest, payload)
    available_chunks = build_chain_available_chunks(
        root_state,
        chunking,
        extensions=extensions,
    )
    head_doc_hash = extensions[-1].doc_hash if extensions else authenticated_root_doc_hash

    state = object.__new__(ValidatedChainState)
    object.__setattr__(state, "root_doc_hash", authenticated_root_doc_hash)
    object.__setattr__(state, "head_doc_hash", head_doc_hash)
    object.__setattr__(state, "head_index", len(extensions))
    object.__setattr__(state, "chunking", chunking)
    object.__setattr__(state, "logical_state", logical_state)
    object.__setattr__(state, "available_chunks", tuple(sorted(available_chunks.items())))
    object.__setattr__(state, "_seal", _VALIDATED_CHAIN_STATE_SEAL)
    return state


def extract_root_logical_state(
    manifest: EnvelopeManifest,
    payload: bytes,
) -> tuple[LogicalFileState, ...]:
    """Extract the standalone root logical state from a V1 manifest and payload."""

    extracted = extract_payloads(manifest, payload)
    return tuple(
        LogicalFileState(
            path=file_entry.path,
            size=file_entry.size,
            sha256=file_entry.sha256,
            mtime=file_entry.mtime,
            data=file_bytes,
        )
        for file_entry, file_bytes in extracted
    )


def _reconstruct_structural_latest_logical_state(
    manifest: EnvelopeManifest,
    payload: bytes,
    *,
    root_doc_hash: bytes,
    extensions: Sequence[_StructuralExtensionChainLink],
    expected_sign_pub: bytes | None = None,
) -> tuple[LogicalFileState, ...]:
    """Validate and replay a chain in one pass.

    This helper is intentionally private. Recovery/import replay must use
    reconstruct_authenticated_latest_logical_state so root AUTH and per-link AUTH cannot be skipped
    by accident.
    """

    root_state = extract_root_logical_state(manifest, payload)
    expected_root_doc_hash = require_bytes(root_doc_hash, 32, label="root_doc_hash")
    trusted_sign_pub = (
        None
        if expected_sign_pub is None
        else require_bytes(expected_sign_pub, ED25519_PUB_LEN, label="expected_sign_pub")
    )
    locked_chunking: ExtensionChunkingProfile | None = None

    current_state = {item.path: item for item in root_state}
    if len(current_state) > MAX_MANIFEST_FILES:
        raise ValueError(
            "root logical state exceeds MAX_MANIFEST_FILES "
            f"({MAX_MANIFEST_FILES}): {len(current_state)} entries"
        )
    total_logical_bytes = sum(item.size for item in current_state.values())
    if total_logical_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError("root logical bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES")
    current_sizes = {item.path: item.size for item in current_state.values()}
    needed_chunk_refs = _extension_chunk_ref_counts(extensions)
    seen_chunk_ids: set[bytes] = set()
    available_chunks: dict[bytes, bytes] = {}
    expected_parent_doc_hash = expected_root_doc_hash
    expected_index = 1
    last_validated_head_index = 0
    last_validated_head_hash = expected_root_doc_hash
    decoded_chunk_bytes = 0

    for link in extensions:
        header = link.document.header
        needs_root_chunk_map = False
        try:
            if trusted_sign_pub is not None:
                if not isinstance(link, AuthenticatedExtensionChainLink):
                    raise ValueError("authenticated extension chain requires authenticated links")
                if link.expected_sign_pub != trusted_sign_pub:
                    raise ValueError("extension AUTH signing key does not match root authority")
        except ValueError as exc:
            raise _extension_replay_error(
                exc,
                phase="auth",
                link=link,
                last_validated_head_index=last_validated_head_index,
                last_validated_head_hash=last_validated_head_hash,
            ) from exc

        try:
            if header.index != expected_index:
                raise ValueError(
                    "extension index sequence is invalid: "
                    f"expected {expected_index}, got {header.index}"
                )
            if header.root_doc_hash != expected_root_doc_hash:
                raise ValueError("extension root_doc_hash does not match root backup")
            if header.parent_doc_hash != expected_parent_doc_hash:
                raise ValueError("extension parent_doc_hash does not match previous document")
            if locked_chunking is None:
                locked_chunking = header.chunking
                needs_root_chunk_map = True
            elif header.chunking != locked_chunking:
                raise ValueError("extension chunking profile must match the locked chain profile")
        except ValueError as exc:
            raise _extension_replay_error(
                exc,
                phase="lineage",
                link=link,
                last_validated_head_index=last_validated_head_index,
                last_validated_head_hash=last_validated_head_hash,
            ) from exc

        try:
            if needs_root_chunk_map:
                available_chunks = _virtual_root_chunk_map(
                    root_state,
                    locked_chunking,
                    needed_ref_counts=needed_chunk_refs,
                    seen_chunk_ids=seen_chunk_ids,
                )
            _merge_new_extension_chunks(
                available_chunks,
                link.document,
                needed_ref_counts=needed_chunk_refs,
                seen_chunk_ids=seen_chunk_ids,
            )
        except ValueError as exc:
            raise _extension_replay_error(
                exc,
                phase="chunks",
                link=link,
                last_validated_head_index=last_validated_head_index,
                last_validated_head_hash=last_validated_head_hash,
            ) from exc

        try:
            decoded_chunk_bytes += link.document.inline_chunk_raw_bytes
            if decoded_chunk_bytes > MAX_RECOVERY_DECODED_CHUNK_BYTES:
                raise ValueError(
                    "extension chain inline chunk bytes exceed "
                    "MAX_RECOVERY_DECODED_CHUNK_BYTES "
                    f"({MAX_RECOVERY_DECODED_CHUNK_BYTES}); rebuild the latest logical state as "
                    "a fresh standalone backup before adding more files"
                )
            projected_sizes = dict(current_sizes)
            for file_entry in link.document.files:
                projected_sizes[file_entry.path] = file_entry.size
            if len(projected_sizes) > MAX_MANIFEST_FILES:
                raise ValueError(
                    "logical latest state exceeds MAX_MANIFEST_FILES "
                    f"({MAX_MANIFEST_FILES}): {len(projected_sizes)} entries"
                )
            projected_logical_bytes = sum(projected_sizes.values())
            if projected_logical_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
                raise ValueError("logical latest state exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES")
        except ValueError as exc:
            raise _extension_replay_error(
                exc,
                phase="limits",
                link=link,
                last_validated_head_index=last_validated_head_index,
                last_validated_head_hash=last_validated_head_hash,
            ) from exc

        try:
            resolved_states = [
                _resolve_extension_file_state(file_entry, available_chunks, locked_chunking)
                for file_entry in link.document.files
            ]
        except ValueError as exc:
            raise _extension_replay_error(
                exc,
                phase="files",
                link=link,
                last_validated_head_index=last_validated_head_index,
                last_validated_head_hash=last_validated_head_hash,
            ) from exc
        for file_state in resolved_states:
            current_state[file_state.path] = file_state
        current_sizes = projected_sizes
        total_logical_bytes = projected_logical_bytes
        _consume_extension_chunk_refs(needed_chunk_refs, available_chunks, link.document)
        expected_parent_doc_hash = link.doc_hash
        expected_index += 1
        last_validated_head_index = header.index
        last_validated_head_hash = link.doc_hash

    return tuple(current_state[path] for path in sorted(current_state))


def reconstruct_authenticated_latest_logical_state(
    manifest: EnvelopeManifest,
    payload: bytes,
    *,
    root_doc_hash: bytes,
    expected_sign_pub: bytes,
    extensions: Sequence[AuthenticatedExtensionChainLink],
) -> tuple[LogicalFileState, ...]:
    """Reconstruct latest logical state from links verified against the root authority."""

    return _reconstruct_structural_latest_logical_state(
        manifest,
        payload,
        root_doc_hash=root_doc_hash,
        extensions=extensions,
        expected_sign_pub=expected_sign_pub,
    )


def _extension_replay_error(
    exc: ValueError,
    *,
    phase: ReplayFailurePhase,
    link: _StructuralExtensionChainLink,
    last_validated_head_index: int,
    last_validated_head_hash: bytes,
) -> ExtensionReplayError:
    if isinstance(exc, ExtensionReplayError):
        return exc
    return ExtensionReplayError(
        str(exc),
        failure_phase=phase,
        failing_index=link.document.header.index,
        failing_hash=link.doc_hash,
        last_validated_head_index=last_validated_head_index,
        last_validated_head_hash=last_validated_head_hash,
    )


def build_chain_available_chunks(
    root_state: Sequence[LogicalFileState],
    chunking: ExtensionChunkingProfile,
    *,
    extensions: Sequence[_StructuralExtensionChainLink] = (),
) -> dict[bytes, bytes]:
    """Return the chain-global chunk source before building a new extension."""

    available_chunks = _virtual_root_chunk_map(root_state, chunking)
    for link in extensions:
        _merge_new_extension_chunks(available_chunks, link.document)
    return available_chunks


def build_chain_known_chunk_ids(
    root_state: Sequence[LogicalFileState],
    chunking: ExtensionChunkingProfile,
    *,
    extensions: Sequence[_StructuralExtensionChainLink] = (),
) -> frozenset[bytes]:
    """Return every virtual-root or extension chunk identity without retaining raw history."""

    known_chunk_ids: set[bytes] = set()
    for item in root_state:
        data_view = memoryview(item.data)
        known_chunk_ids.update(
            hashlib.sha256(data_view[start:end]).digest()
            for start, end in default_extension_chunker(item.data, chunking)
        )
    for link in extensions:
        known_chunk_ids.update(chunk.chunk_id for chunk in link.document.chunks)
    return frozenset(known_chunk_ids)


def _validate_structural_extension_chain(
    *,
    root_doc_hash: bytes,
    extensions: Sequence[_StructuralExtensionChainLink],
) -> ExtensionChunkingProfile | None:
    """Validate extension-link ordering and ancestry metadata without AUTH checks."""

    if not isinstance(root_doc_hash, (bytes, bytearray)) or len(root_doc_hash) != 32:
        raise ValueError("root_doc_hash must be 32 bytes")
    if not extensions:
        return None

    expected_root_doc_hash = bytes(root_doc_hash)
    expected_parent_doc_hash = expected_root_doc_hash
    expected_index = 1
    locked_chunking: ExtensionChunkingProfile | None = None
    decoded_chunk_bytes = 0

    for link in extensions:
        header = link.document.header
        if header.index != expected_index:
            raise ValueError(
                "extension index sequence is invalid: "
                f"expected {expected_index}, got {header.index}"
            )
        if header.root_doc_hash != expected_root_doc_hash:
            raise ValueError("extension root_doc_hash does not match root backup")
        if header.parent_doc_hash != expected_parent_doc_hash:
            raise ValueError("extension parent_doc_hash does not match previous document")
        if locked_chunking is None:
            locked_chunking = header.chunking
        elif header.chunking != locked_chunking:
            raise ValueError("extension chunking profile must match the locked chain profile")
        decoded_chunk_bytes += link.document.inline_chunk_raw_bytes
        if decoded_chunk_bytes > MAX_RECOVERY_DECODED_CHUNK_BYTES:
            raise ValueError(
                "extension chain inline chunk bytes exceed "
                "MAX_RECOVERY_DECODED_CHUNK_BYTES "
                f"({MAX_RECOVERY_DECODED_CHUNK_BYTES}); rebuild the latest logical state as a "
                "fresh standalone backup before adding more files"
            )
        expected_parent_doc_hash = link.doc_hash
        expected_index += 1

    return locked_chunking


def validate_authenticated_extension_chain(
    *,
    root_doc_hash: bytes,
    expected_sign_pub: bytes,
    extensions: Sequence[AuthenticatedExtensionChainLink],
) -> ExtensionChunkingProfile | None:
    """Validate AUTH-verified extension links and structural ancestry metadata."""

    expected_sign_pub = require_bytes(
        expected_sign_pub,
        ED25519_PUB_LEN,
        label="expected_sign_pub",
    )
    for link in extensions:
        if not isinstance(link, AuthenticatedExtensionChainLink):
            raise ValueError("authenticated extension chain requires authenticated links")
        if link.expected_sign_pub != expected_sign_pub:
            raise ValueError("extension AUTH signing key does not match root authority")
    return _validate_structural_extension_chain(root_doc_hash=root_doc_hash, extensions=extensions)


def _require_validated_chain_state(chain: ValidatedChainState) -> None:
    if (
        not isinstance(chain, ValidatedChainState)
        or getattr(chain, "_seal", None) is not _VALIDATED_CHAIN_STATE_SEAL
    ):
        raise TypeError("extension build requires a ValidatedChainState from authenticated replay")


def _replay_extension_candidate(
    chain: ValidatedChainState,
    document: ExtensionEnvelope,
) -> tuple[LogicalFileState, ...]:
    """Replay one unsigned candidate against a sealed authenticated chain state."""

    _require_validated_chain_state(chain)

    header = document.header
    if header.index != chain.head_index + 1:
        raise ValueError("extension candidate index does not follow the authenticated head")
    if header.root_doc_hash != chain.root_doc_hash:
        raise ValueError("extension candidate root_doc_hash does not match the authenticated root")
    if header.parent_doc_hash != chain.head_doc_hash:
        raise ValueError(
            "extension candidate parent_doc_hash does not match the authenticated head"
        )
    if header.chunking != chain.chunking:
        raise ValueError("extension candidate chunking does not match the locked chain profile")

    available_chunks = dict(chain.available_chunks)
    _merge_new_extension_chunks(available_chunks, document)

    current_state = {item.path: item for item in chain.logical_state}
    projected_sizes = {path: item.size for path, item in current_state.items()}
    for file_entry in document.files:
        projected_sizes[file_entry.path] = file_entry.size
    if len(projected_sizes) > MAX_MANIFEST_FILES:
        raise ValueError(
            "logical latest state exceeds MAX_MANIFEST_FILES "
            f"({MAX_MANIFEST_FILES}): {len(projected_sizes)} entries"
        )
    if sum(projected_sizes.values()) > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError("logical latest state exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES")

    for file_entry in document.files:
        resolved = _resolve_extension_file_state(file_entry, available_chunks, chain.chunking)
        current_state[resolved.path] = resolved
    return tuple(current_state[path] for path in sorted(current_state))


__all__ = [
    "AuthenticatedExtensionChainLink",
    "ExtensionReplayError",
    "LogicalFileState",
    "ValidatedChainState",
    "build_chain_available_chunks",
    "build_chain_known_chunk_ids",
    "extract_root_logical_state",
    "reconstruct_authenticated_latest_logical_state",
    "validate_authenticated_extension_chain",
]


def _normalize_chunk_map(
    chunk_map: Mapping[bytes, bytes] | None,
) -> dict[bytes, bytes]:
    if chunk_map is None:
        return {}
    normalized: dict[bytes, bytes] = {}
    for chunk_id, chunk_bytes in chunk_map.items():
        if not isinstance(chunk_id, (bytes, bytearray)) or len(chunk_id) != 32:
            raise ValueError("virtual root chunk_id must be 32 bytes")
        if not isinstance(chunk_bytes, (bytes, bytearray)):
            raise ValueError("virtual root chunk bytes must be bytes")
        raw_chunk_id = bytes(chunk_id)
        raw_chunk_bytes = bytes(chunk_bytes)
        if hashlib.sha256(raw_chunk_bytes).digest() != raw_chunk_id:
            raise ValueError("virtual root chunk bytes do not hash to chunk_id")
        normalized[raw_chunk_id] = raw_chunk_bytes
    return normalized


def _virtual_root_chunk_map(
    root_state: Sequence[LogicalFileState],
    chunking: ExtensionChunkingProfile,
    *,
    needed_ref_counts: Mapping[bytes, int] | None = None,
    seen_chunk_ids: set[bytes] | None = None,
) -> dict[bytes, bytes]:
    chunks: dict[bytes, bytes] = {}
    for item in root_state:
        data_view = memoryview(item.data)
        for start, end in default_extension_chunker(item.data, chunking):
            chunk_view = data_view[start:end]
            chunk_id = hashlib.sha256(chunk_view).digest()
            if seen_chunk_ids is not None:
                seen_chunk_ids.add(chunk_id)
            if needed_ref_counts is not None and needed_ref_counts.get(chunk_id, 0) <= 0:
                continue
            existing = chunks.get(chunk_id)
            if existing is not None and existing != chunk_view:
                raise ValueError("virtual root chunk payload collision for identical chunk_id")
            if existing is None:
                chunks[chunk_id] = chunk_view.tobytes()
    return chunks


def _merge_chunk_map(target: dict[bytes, bytes], source: Mapping[bytes, bytes]) -> None:
    for chunk_id, chunk_bytes in source.items():
        existing = target.get(chunk_id)
        if existing is not None and existing != chunk_bytes:
            raise ValueError("available chunk payload collision for identical chunk_id")
        target[chunk_id] = chunk_bytes


def _merge_new_extension_chunks(
    target: dict[bytes, bytes],
    extension: ExtensionEnvelope,
    *,
    needed_ref_counts: Mapping[bytes, int] | None = None,
    seen_chunk_ids: set[bytes] | None = None,
) -> None:
    for chunk_record in extension.chunks:
        decoded_chunk = chunk_record.decode_data()
        if seen_chunk_ids is not None:
            if chunk_record.chunk_id in seen_chunk_ids:
                existing = target.get(chunk_record.chunk_id)
                if existing is not None and existing != decoded_chunk:
                    raise ValueError("available chunk payload collision for identical chunk_id")
                raise ValueError("extension chunks must be newly introduced")
            seen_chunk_ids.add(chunk_record.chunk_id)
        else:
            existing = target.get(chunk_record.chunk_id)
            if existing is not None:
                if existing != decoded_chunk:
                    raise ValueError("available chunk payload collision for identical chunk_id")
                raise ValueError("extension chunks must be newly introduced")
        if needed_ref_counts is not None and needed_ref_counts.get(chunk_record.chunk_id, 0) <= 0:
            continue
        existing = target.get(chunk_record.chunk_id)
        if existing is not None:
            if existing != decoded_chunk:
                raise ValueError("available chunk payload collision for identical chunk_id")
            raise ValueError("extension chunks must be newly introduced")
        target[chunk_record.chunk_id] = decoded_chunk


def _extension_chunk_ref_counts(
    extensions: Sequence[_StructuralExtensionChainLink],
) -> Counter[bytes]:
    counts: Counter[bytes] = Counter()
    for link in extensions:
        for file_entry in link.document.files:
            counts.update(chunk_ref.chunk_id for chunk_ref in file_entry.chunk_refs)
    return counts


def _consume_extension_chunk_refs(
    ref_counts: Counter[bytes],
    available_chunks: dict[bytes, bytes],
    extension: ExtensionEnvelope,
) -> None:
    for file_entry in extension.files:
        for chunk_ref in file_entry.chunk_refs:
            remaining = ref_counts[chunk_ref.chunk_id] - 1
            if remaining <= 0:
                del ref_counts[chunk_ref.chunk_id]
                available_chunks.pop(chunk_ref.chunk_id, None)
            else:
                ref_counts[chunk_ref.chunk_id] = remaining


def _resolve_extension_file_state(
    file_entry: ExtensionFile,
    available_chunks: Mapping[bytes, bytes],
    chunking: ExtensionChunkingProfile,
) -> LogicalFileState:
    file_bytes = _reconstruct_extension_file_bytes(file_entry, available_chunks, chunking)
    return LogicalFileState._from_verified_extension(file_entry, file_bytes)
