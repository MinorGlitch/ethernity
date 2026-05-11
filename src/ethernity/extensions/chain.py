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

from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES, MAX_MANIFEST_FILES
from ethernity.formats.envelope_codec import extract_payloads
from ethernity.formats.envelope_types import EnvelopeManifest
from ethernity.formats.extension_chunking import (
    default_extension_chunker,
    require_canonical_chunk_refs,
)
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
    total_logical_bytes = sum(item.size for item in current_state.values())
    if total_logical_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError("root logical bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES")
    current_sizes = {item.path: item.size for item in current_state.values()}
    needed_chunk_refs = _extension_chunk_ref_counts(extensions)
    seen_chunk_ids: set[bytes] = set()
    available_chunks: dict[bytes, bytes] = (
        _virtual_root_chunk_map(
            root_state,
            locked_chunking,
            needed_ref_counts=needed_chunk_refs,
            seen_chunk_ids=seen_chunk_ids,
        )
        if locked_chunking
        else {}
    )

    for link in extensions:
        if locked_chunking is None:
            raise ValueError("extension chain requires a locked chunking profile")
        _merge_new_extension_chunks(
            available_chunks,
            link.document,
            needed_ref_counts=needed_chunk_refs,
            seen_chunk_ids=seen_chunk_ids,
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

        resolved_states = []
        for file_entry in link.document.files:
            file_state = _resolve_extension_file_state(
                file_entry,
                available_chunks,
                locked_chunking,
            )
            resolved_states.append(file_state)
        for file_state in resolved_states:
            current_state[file_state.path] = file_state
        current_sizes = projected_sizes
        total_logical_bytes = projected_logical_bytes
        _consume_extension_chunk_refs(needed_chunk_refs, available_chunks, link.document)

    return tuple(current_state[path] for path in sorted(current_state))


def build_chain_available_chunks(
    root_state: Sequence[LogicalFileState],
    chunking: ExtensionChunkingProfile,
    *,
    extensions: Sequence[ExtensionChainLink] = (),
) -> dict[bytes, bytes]:
    """Return the chain-global chunk source before building a new extension."""

    available_chunks = _virtual_root_chunk_map(root_state, chunking)
    for link in extensions:
        _merge_new_extension_chunks(available_chunks, link.document)
    return available_chunks


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


def _virtual_root_chunk_map(
    root_state: Sequence[LogicalFileState],
    chunking: ExtensionChunkingProfile,
    *,
    needed_ref_counts: Mapping[bytes, int] | None = None,
    seen_chunk_ids: set[bytes] | None = None,
) -> dict[bytes, bytes]:
    chunks: dict[bytes, bytes] = {}
    for item in root_state:
        for chunk_bytes in default_extension_chunker(item.data, chunking):
            chunk_id = hashlib.sha256(chunk_bytes).digest()
            if seen_chunk_ids is not None:
                seen_chunk_ids.add(chunk_id)
            if needed_ref_counts is not None and needed_ref_counts.get(chunk_id, 0) <= 0:
                continue
            existing = chunks.get(chunk_id)
            if existing is not None and existing != chunk_bytes:
                raise ValueError("virtual root chunk payload collision for identical chunk_id")
            chunks[chunk_id] = chunk_bytes
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


def _extension_chunk_ref_counts(extensions: Sequence[ExtensionChainLink]) -> Counter[bytes]:
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
    require_canonical_chunk_refs(
        declared_refs,
        file_bytes,
        chunking,
    )
