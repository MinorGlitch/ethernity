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

"""Chain validation and file reconstruction for extension documents."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

from ethernity.core.bounds import (
    MAX_DECOMPRESSED_PAYLOAD_BYTES,
    MAX_MANIFEST_FILES,
    MAX_RECOVERY_DECODED_CHUNK_BYTES,
)
from ethernity.core.validation import require_bytes, validate_manifest_file_tree
from ethernity.crypto.signing import (
    AUTH_VERSION,
    DOC_HASH_LEN,
    ED25519_PUB_LEN,
    ED25519_SIG_LEN,
    AuthPayload,
    verify_auth,
)
from ethernity.formats.document_codec import extract_payloads
from ethernity.formats.extension_chunking import (
    default_extension_chunker,
)
from ethernity.formats.extension_document import (
    ExtensionChunkingProfile,
    ExtensionDocument,
    ExtensionFile,
    ExtensionHeader,
    _reconstruct_extension_file_bytes,
)
from ethernity.formats.extension_mode import UpdateMode, resolve_update_mode
from ethernity.formats.manifest import BackupManifest

_VALIDATED_CHAIN_STATE_SEAL = object()

ReplayFailurePhase = Literal["auth", "lineage", "chunks", "limits", "files"]


@dataclass(frozen=True)
class _ExtensionDocumentLink:
    """One extension document plus its ciphertext hash identity.

    This type checks the document and hash types; it does not verify signatures or ancestry.
    Use AuthenticatedExtensionChainLink when replaying user-supplied documents.
    """

    doc_hash: bytes
    document: ExtensionDocument

    def __post_init__(self) -> None:
        if not isinstance(self.doc_hash, (bytes, bytearray)) or len(self.doc_hash) != 32:
            raise ValueError("extension chain link doc_hash must be 32 bytes")
        object.__setattr__(self, "doc_hash", bytes(self.doc_hash))
        if not isinstance(self.document, ExtensionDocument):
            raise ValueError("extension chain link document must be an ExtensionDocument")


@dataclass(frozen=True)
class AuthenticatedExtensionChainLink(_ExtensionDocumentLink):
    """Extension link whose AUTH payload is verified against the root signing key."""

    auth_payload: AuthPayload
    expected_sign_pub: bytes
    auth_status: str = "verified"
    root_signing_key_verified: bool = True

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
            raise ValueError("extension AUTH signing key does not match root signing key")
        if self.auth_status != "verified":
            raise ValueError("extension AUTH status must be verified")
        if self.root_signing_key_verified is not True:
            raise ValueError("extension root signing key must be verified")
        if not verify_auth(auth_doc_hash, sign_pub=auth_sign_pub, signature=auth_signature):
            raise ValueError("extension AUTH signature is invalid")


@dataclass(frozen=True)
class ReconstructedFile:
    """One reconstructed file in the latest chain state."""

    path: str
    size: int
    sha256: bytes
    mtime: int | None
    data: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.data, (bytes, bytearray)):
            raise ValueError("reconstructed file data must be bytes")
        raw = bytes(self.data)
        if len(raw) != self.size:
            raise ValueError("reconstructed file size does not match data length")
        if hashlib.sha256(raw).digest() != self.sha256:
            raise ValueError("reconstructed file sha256 does not match data")
        object.__setattr__(self, "data", raw)

    @classmethod
    def _from_verified_extension(
        cls,
        file_entry: ExtensionFile,
        data: bytes,
    ) -> ReconstructedFile:
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

    Instances are created only by authenticated replay; callers cannot
    assemble a trusted state from independently supplied chunk IDs or lineage fields.
    """

    root_doc_hash: bytes
    head_doc_hash: bytes
    head_index: int
    update_mode: UpdateMode | None
    chunking: ExtensionChunkingProfile
    root_files: tuple[ReconstructedFile, ...]
    root_chunks: tuple[tuple[bytes, bytes], ...]
    files: tuple[ReconstructedFile, ...]
    available_chunks: tuple[tuple[bytes, bytes], ...]
    links: tuple[AuthenticatedExtensionChainLink, ...]
    decoded_chunk_bytes: int
    _seal: object

    def __init__(self) -> None:
        raise TypeError("ValidatedChainState can only be created by authenticated chain replay")


def replay_authenticated_chain(
    manifest: BackupManifest,
    payload: bytes,
    *,
    root_doc_hash: bytes,
    root_auth_payload: AuthPayload,
    expected_sign_pub: bytes,
    extensions: Sequence[AuthenticatedExtensionChainLink],
    root_chunking: ExtensionChunkingProfile,
) -> ValidatedChainState:
    """Authenticate and replay a complete chain into one reusable validated result."""

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
        raise ValueError("root AUTH signing key does not match the expected root signing key")
    if not verify_auth(
        authenticated_root_doc_hash,
        sign_pub=root_sign_pub,
        signature=root_signature,
    ):
        raise ValueError("root AUTH signature is invalid")

    chunking = extensions[0].document.header.chunking if extensions else root_chunking
    root_state = extract_root_files(manifest, payload)
    files, available_chunks, decoded_chunk_bytes, root_chunks = _replay_chain_from_root_state(
        root_state=root_state,
        root_doc_hash=authenticated_root_doc_hash,
        expected_sign_pub=trusted_sign_pub,
        extensions=extensions,
        chunking=chunking,
    )
    head_doc_hash = extensions[-1].doc_hash if extensions else authenticated_root_doc_hash

    state = object.__new__(ValidatedChainState)
    object.__setattr__(state, "root_doc_hash", authenticated_root_doc_hash)
    object.__setattr__(state, "head_doc_hash", head_doc_hash)
    object.__setattr__(
        state, "head_index", extensions[-1].document.header.index if extensions else 0
    )
    object.__setattr__(
        state, "update_mode", extensions[-1].document.header.update_mode if extensions else None
    )
    object.__setattr__(state, "chunking", chunking)
    object.__setattr__(state, "root_files", root_state)
    object.__setattr__(state, "root_chunks", tuple(sorted(root_chunks.items())))
    object.__setattr__(state, "files", files)
    object.__setattr__(state, "available_chunks", tuple(sorted(available_chunks.items())))
    object.__setattr__(state, "links", tuple(extensions))
    object.__setattr__(state, "decoded_chunk_bytes", decoded_chunk_bytes)
    object.__setattr__(state, "_seal", _VALIDATED_CHAIN_STATE_SEAL)
    return state


def extract_root_files(
    manifest: BackupManifest,
    payload: bytes,
) -> tuple[ReconstructedFile, ...]:
    """Extract the root backup's files from its manifest and payload."""

    validate_manifest_file_tree(
        (file_entry.path for file_entry in manifest.files),
        label="root file paths",
    )
    extracted = extract_payloads(manifest, payload)
    return tuple(
        ReconstructedFile(
            path=file_entry.path,
            size=file_entry.size,
            sha256=file_entry.sha256,
            mtime=file_entry.mtime,
            data=file_bytes,
        )
        for file_entry, file_bytes in extracted
    )


def _replay_chain_from_root_state(
    *,
    root_state: Sequence[ReconstructedFile],
    root_doc_hash: bytes,
    expected_sign_pub: bytes,
    extensions: Sequence[AuthenticatedExtensionChainLink],
    chunking: ExtensionChunkingProfile,
) -> tuple[tuple[ReconstructedFile, ...], dict[bytes, bytes], int, dict[bytes, bytes]]:
    """Validate ancestry and replay links once while retaining append-ready chunks."""

    expected_root_doc_hash = require_bytes(root_doc_hash, 32, label="root_doc_hash")
    trusted_sign_pub = require_bytes(
        expected_sign_pub,
        ED25519_PUB_LEN,
        label="expected_sign_pub",
    )
    current_state = {item.path: item for item in root_state}
    if len(current_state) > MAX_MANIFEST_FILES:
        raise ValueError(
            "root file set exceeds MAX_MANIFEST_FILES "
            f"({MAX_MANIFEST_FILES}): {len(current_state)} entries"
        )
    total_file_bytes = sum(item.size for item in current_state.values())
    if total_file_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError("root file bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES")

    root_chunks = _chunk_root_files(root_state, chunking)
    available_chunks = dict(root_chunks)
    current_sizes = {item.path: item.size for item in current_state.values()}
    expected_parent_doc_hash = expected_root_doc_hash
    expected_index = 1
    last_validated_head_index = 0
    last_validated_head_hash = expected_root_doc_hash
    decoded_chunk_bytes = 0
    locked_mode = extensions[0].document.header.update_mode if extensions else None

    for link in extensions:
        header = link.document.header
        with _replay_phase(
            "auth",
            link,
            last_validated_head_index,
            last_validated_head_hash,
        ):
            if not isinstance(link, AuthenticatedExtensionChainLink):
                raise ValueError("authenticated extension chain requires authenticated links")
            if link.expected_sign_pub != trusted_sign_pub:
                raise ValueError("extension AUTH signing key does not match root signing key")

        with _replay_phase(
            "lineage",
            link,
            last_validated_head_index,
            last_validated_head_hash,
        ):
            cumulative = _validate_extension_lineage(
                header,
                locked_mode=locked_mode,
                last_validated_head_index=last_validated_head_index,
                expected_index=expected_index,
                expected_root_doc_hash=expected_root_doc_hash,
                expected_parent_doc_hash=expected_parent_doc_hash,
                chunking=chunking,
            )

        if cumulative:
            # Each cumulative document is replayed independently against the original.
            current_state = {item.path: item for item in root_state}
            current_sizes = {item.path: item.size for item in root_state}
            available_chunks = dict(root_chunks)

        with _replay_phase(
            "chunks",
            link,
            last_validated_head_index,
            last_validated_head_hash,
        ):
            _merge_new_extension_chunks(
                available_chunks,
                link.document,
            )

        with _replay_phase(
            "limits",
            link,
            last_validated_head_index,
            last_validated_head_hash,
        ):
            decoded_chunk_bytes, projected_sizes, projected_file_bytes = _project_extension_sizes(
                link.document, current_sizes, decoded_chunk_bytes
            )

        with _replay_phase(
            "files",
            link,
            last_validated_head_index,
            last_validated_head_hash,
        ):
            validate_manifest_file_tree(projected_sizes, label="reconstructed file paths")
            resolved_states = tuple(
                _resolve_extension_file_state(file_entry, available_chunks, chunking)
                for file_entry in link.document.files
            )
        for file_state in resolved_states:
            current_state[file_state.path] = file_state
        current_sizes = projected_sizes
        total_file_bytes = projected_file_bytes
        expected_parent_doc_hash = link.doc_hash
        expected_index += 1
        last_validated_head_index = header.index
        last_validated_head_hash = link.doc_hash

    return (
        tuple(current_state[path] for path in sorted(current_state)),
        available_chunks,
        decoded_chunk_bytes,
        root_chunks,
    )


def _project_extension_sizes(
    document: ExtensionDocument, current_sizes: dict[str, int], decoded_chunk_bytes: int
) -> tuple[int, dict[str, int], int]:
    decoded_chunk_bytes += document.inline_chunk_raw_bytes
    if decoded_chunk_bytes > MAX_RECOVERY_DECODED_CHUNK_BYTES:
        raise ValueError(
            "extension chain inline chunk bytes exceed "
            "MAX_RECOVERY_DECODED_CHUNK_BYTES "
            f"({MAX_RECOVERY_DECODED_CHUNK_BYTES}); rebuild the latest file set as "
            "a fresh standalone backup before adding more files"
        )
    projected_sizes = dict(current_sizes)
    for file_entry in document.files:
        projected_sizes[file_entry.path] = file_entry.size
    if len(projected_sizes) > MAX_MANIFEST_FILES:
        raise ValueError(
            "latest file set exceeds MAX_MANIFEST_FILES "
            f"({MAX_MANIFEST_FILES}): {len(projected_sizes)} entries"
        )
    projected_file_bytes = sum(projected_sizes.values())
    if projected_file_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError("latest file set exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES")
    return decoded_chunk_bytes, projected_sizes, projected_file_bytes


def _validate_extension_lineage(
    header: ExtensionHeader,
    *,
    locked_mode: UpdateMode | None,
    last_validated_head_index: int,
    expected_index: int,
    expected_root_doc_hash: bytes,
    expected_parent_doc_hash: bytes,
    chunking: ExtensionChunkingProfile,
) -> bool:
    resolve_update_mode(locked_mode, header.update_mode)
    cumulative = header.update_mode == UpdateMode.CUMULATIVE
    if header.index <= last_validated_head_index or (
        not cumulative and header.index != expected_index
    ):
        raise ValueError(
            f"extension index sequence is invalid: expected {expected_index}, got {header.index}"
        )
    if header.root_doc_hash != expected_root_doc_hash:
        raise ValueError("extension root_doc_hash does not match root backup")
    parent = expected_root_doc_hash if cumulative else expected_parent_doc_hash
    if header.parent_doc_hash != parent:
        raise ValueError("extension parent_doc_hash does not match previous document")
    if header.chunking != chunking:
        raise ValueError("extension chunking profile must match the locked chain profile")
    return cumulative


def _extension_replay_error(
    exc: ValueError,
    *,
    phase: ReplayFailurePhase,
    link: _ExtensionDocumentLink,
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


def _require_validated_chain_state(chain: ValidatedChainState) -> None:
    if (
        not isinstance(chain, ValidatedChainState)
        or getattr(chain, "_seal", None) is not _VALIDATED_CHAIN_STATE_SEAL
    ):
        raise TypeError("extension build requires a ValidatedChainState from authenticated replay")


def _replay_extension_candidate(
    chain: ValidatedChainState,
    document: ExtensionDocument,
) -> tuple[ReconstructedFile, ...]:
    """Replay one unsigned candidate against a sealed authenticated chain state."""

    _require_validated_chain_state(chain)

    header = document.header
    if header.index != chain.head_index + 1:
        raise ValueError("extension candidate index does not follow the authenticated head")
    if header.root_doc_hash != chain.root_doc_hash:
        raise ValueError("extension candidate root_doc_hash does not match the authenticated root")
    mode = resolve_update_mode(chain.update_mode, header.update_mode)
    cumulative = mode == UpdateMode.CUMULATIVE
    if header.parent_doc_hash != (chain.root_doc_hash if cumulative else chain.head_doc_hash):
        raise ValueError(
            "extension candidate parent_doc_hash does not match the authenticated head"
        )
    if header.chunking != chain.chunking:
        raise ValueError("extension candidate chunking does not match the locked chain profile")

    available_chunks = dict(chain.root_chunks if cumulative else chain.available_chunks)
    _merge_new_extension_chunks(available_chunks, document)

    current_state = {item.path: item for item in (chain.root_files if cumulative else chain.files)}
    projected_sizes = {path: item.size for path, item in current_state.items()}
    for file_entry in document.files:
        projected_sizes[file_entry.path] = file_entry.size
    if len(projected_sizes) > MAX_MANIFEST_FILES:
        raise ValueError(
            "latest file set exceeds MAX_MANIFEST_FILES "
            f"({MAX_MANIFEST_FILES}): {len(projected_sizes)} entries"
        )
    if sum(projected_sizes.values()) > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError("latest file set exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES")
    validate_manifest_file_tree(projected_sizes, label="reconstructed file paths")

    for file_entry in document.files:
        resolved = _resolve_extension_file_state(file_entry, available_chunks, chain.chunking)
        current_state[resolved.path] = resolved
    return tuple(current_state[path] for path in sorted(current_state))


__all__ = [
    "AuthenticatedExtensionChainLink",
    "ExtensionReplayError",
    "ReconstructedFile",
    "ValidatedChainState",
    "extract_root_files",
    "replay_authenticated_chain",
]


def _chunk_root_files(
    root_state: Sequence[ReconstructedFile],
    chunking: ExtensionChunkingProfile,
) -> dict[bytes, bytes]:
    chunks: dict[bytes, bytes] = {}
    for item in root_state:
        data_view = memoryview(item.data)
        for start, end in default_extension_chunker(item.data, chunking):
            chunk_view = data_view[start:end]
            chunk_id = hashlib.sha256(chunk_view).digest()
            existing = chunks.get(chunk_id)
            if existing is not None and existing != chunk_view:
                raise ValueError("derived root chunk payload collision for identical chunk_id")
            if existing is None:
                chunks[chunk_id] = chunk_view.tobytes()
    return chunks


def _merge_new_extension_chunks(
    target: dict[bytes, bytes],
    extension: ExtensionDocument,
) -> None:
    for chunk_record in extension.chunks:
        decoded_chunk = chunk_record.decode_data()
        existing = target.get(chunk_record.chunk_id)
        if existing is not None:
            if existing != decoded_chunk:
                raise ValueError("available chunk payload collision for identical chunk_id")
            raise ValueError("extension chunks must be newly introduced")
        target[chunk_record.chunk_id] = decoded_chunk


def _resolve_extension_file_state(
    file_entry: ExtensionFile,
    available_chunks: Mapping[bytes, bytes],
    chunking: ExtensionChunkingProfile,
) -> ReconstructedFile:
    file_bytes = _reconstruct_extension_file_bytes(file_entry, available_chunks, chunking)
    return ReconstructedFile._from_verified_extension(file_entry, file_bytes)


@contextmanager
def _replay_phase(
    phase: ReplayFailurePhase,
    link: AuthenticatedExtensionChainLink,
    last_validated_head_index: int,
    last_validated_head_hash: bytes,
) -> Iterator[None]:
    """Attach the same validated-prefix context to each replay failure."""
    try:
        yield
    except ValueError as exc:
        raise _extension_replay_error(
            exc,
            phase=phase,
            link=link,
            last_validated_head_index=last_validated_head_index,
            last_validated_head_hash=last_validated_head_hash,
        ) from exc
