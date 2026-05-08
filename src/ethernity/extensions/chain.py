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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES, MAX_MANIFEST_FILES
from ethernity.extensions.chunking import default_extension_chunker
from ethernity.formats.envelope_codec import extract_payloads
from ethernity.formats.envelope_types import EnvelopeManifest
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
    ExtensionEnvelope,
    ExtensionFile,
)


@dataclass(frozen=True)
class ExtensionChainLink:
    """One authenticated extension document plus its ciphertext hash identity."""

    doc_hash: bytes
    document: ExtensionEnvelope

    def __post_init__(self) -> None:
        if not isinstance(self.doc_hash, (bytes, bytearray)) or len(self.doc_hash) != 32:
            raise ValueError("extension chain link doc_hash must be 32 bytes")
        object.__setattr__(self, "doc_hash", bytes(self.doc_hash))
        if not isinstance(self.document, ExtensionEnvelope):
            raise ValueError("extension chain link document must be an ExtensionEnvelope")


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


def reconstruct_latest_logical_state(
    manifest: EnvelopeManifest,
    payload: bytes,
    *,
    root_doc_hash: bytes,
    extensions: Sequence[ExtensionChainLink],
    virtual_root_chunks: Mapping[bytes, bytes] | None = None,
) -> tuple[LogicalFileState, ...]:
    """Reconstruct the latest logical state for a root plus validated extensions."""

    root_state = extract_root_logical_state(manifest, payload)
    locked_chunking = validate_extension_chain(root_doc_hash=root_doc_hash, extensions=extensions)

    current_state = {item.path: item for item in root_state}
    if len(current_state) > MAX_MANIFEST_FILES:
        raise ValueError(
            "root logical state exceeds MAX_MANIFEST_FILES "
            f"({MAX_MANIFEST_FILES}): {len(current_state)} entries"
        )
    available_chunks = _normalize_chunk_map(virtual_root_chunks)
    total_logical_bytes = sum(item.size for item in current_state.values())
    if total_logical_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError("root logical bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES")

    for link in extensions:
        if locked_chunking is None:
            raise ValueError("extension chain requires a locked chunking profile")
        for chunk_record in link.document.chunks:
            available_chunks[chunk_record.chunk_id] = chunk_record.decode_data()

        for file_entry in link.document.files:
            if file_entry.path not in current_state and len(current_state) >= MAX_MANIFEST_FILES:
                raise ValueError(
                    "logical latest state exceeds MAX_MANIFEST_FILES "
                    f"({MAX_MANIFEST_FILES}): {len(current_state) + 1} entries"
                )
            previous_entry = current_state.get(file_entry.path)
            previous_size = previous_entry.size if previous_entry is not None else 0
            projected_logical_bytes = total_logical_bytes + file_entry.size - previous_size
            if projected_logical_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
                raise ValueError("logical latest state exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES")
            file_state = _resolve_extension_file_state(
                file_entry,
                available_chunks,
                locked_chunking,
            )
            total_logical_bytes = projected_logical_bytes
            current_state[file_state.path] = file_state

    return tuple(current_state[path] for path in sorted(current_state))


def validate_extension_chain(
    *,
    root_doc_hash: bytes,
    extensions: Sequence[ExtensionChainLink],
) -> ExtensionChunkingProfile | None:
    """Validate extension-link ordering and authenticated ancestry metadata."""

    if not isinstance(root_doc_hash, (bytes, bytearray)) or len(root_doc_hash) != 32:
        raise ValueError("root_doc_hash must be 32 bytes")
    if not extensions:
        return None

    expected_root_doc_hash = bytes(root_doc_hash)
    expected_parent_doc_hash = expected_root_doc_hash
    expected_index = 1
    locked_chunking: ExtensionChunkingProfile | None = None

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
        expected_parent_doc_hash = link.doc_hash
        expected_index += 1

    return locked_chunking


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


def _resolve_extension_file_state(
    file_entry: ExtensionFile,
    available_chunks: Mapping[bytes, bytes],
    chunking: ExtensionChunkingProfile,
) -> LogicalFileState:
    payload = bytearray()
    resolved_size = 0
    for chunk_ref in file_entry.chunk_refs:
        next_resolved_size = resolved_size + chunk_ref.uncompressed_len
        if next_resolved_size > file_entry.size:
            raise ValueError("extension file chunk_refs exceed declared file size")
        resolved = available_chunks.get(chunk_ref.chunk_id)
        if resolved is None:
            raise ValueError(f"extension file references unresolved chunk_id: {file_entry.path}")
        if len(resolved) != chunk_ref.uncompressed_len:
            raise ValueError("extension chunk_ref length does not match resolved chunk")
        payload.extend(resolved)
        resolved_size = next_resolved_size
    file_bytes = bytes(payload)
    _validate_canonical_chunk_recipe(file_entry, file_bytes, chunking)
    return LogicalFileState(
        path=file_entry.path,
        size=file_entry.size,
        sha256=file_entry.sha256,
        mtime=file_entry.mtime,
        data=file_bytes,
    )


def _validate_canonical_chunk_recipe(
    file_entry: ExtensionFile,
    file_bytes: bytes,
    chunking: ExtensionChunkingProfile,
) -> None:
    declared_refs = tuple(
        (chunk_ref.chunk_id, chunk_ref.uncompressed_len) for chunk_ref in file_entry.chunk_refs
    )
    canonical_refs = tuple(
        (hashlib.sha256(chunk).digest(), len(chunk))
        for chunk in default_extension_chunker(file_bytes, chunking)
    )
    if declared_refs != canonical_refs:
        raise ValueError("extension file chunk_refs do not match locked chunking profile")
