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

"""Extension-envelope assembly helpers for changed-file payloads."""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES, MAX_MANIFEST_FILES
from ethernity.core.validation import normalize_manifest_path, require_non_negative_int
from ethernity.extensions.chain import (
    LogicalFileState,
    ValidatedChainState,
    _replay_extension_candidate,
    _require_validated_chain_state,
)
from ethernity.formats.extension_chunking import (
    Chunker,
    default_extension_chunker,
)
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
    ExtensionChunkRecord,
    ExtensionChunkRef,
    ExtensionEnvelope,
    ExtensionFile,
    build_extension_header,
)
from ethernity.formats.extension_envelope_constants import CHUNK_CODEC_GZIP, CHUNK_CODEC_RAW


@dataclass(frozen=True)
class ExtensionBuildStats:
    changed_file_count: int
    logical_bytes: int
    new_chunks: int
    reused_chunks: int


@dataclass(frozen=True)
class _BuiltExtensionDocument:
    document: ExtensionEnvelope
    stats: ExtensionBuildStats


@dataclass(frozen=True)
class VerifiedExtensionCandidate:
    """Extension document proven replayable against an authenticated chain state."""

    document: ExtensionEnvelope
    stats: ExtensionBuildStats
    resulting_state: tuple[LogicalFileState, ...]


class ExtensionInputFile(Protocol):
    @property
    def relative_path(self) -> str: ...

    @property
    def data(self) -> bytes: ...

    @property
    def mtime(self) -> int | None: ...


class SelectedInputScope(Protocol):
    """Neutral input-scope contract consumed by the extension domain builder."""

    @property
    def input_files(self) -> Sequence[ExtensionInputFile]: ...

    @property
    def input_origin(self) -> str: ...

    @property
    def input_roots(self) -> Sequence[str]: ...

    def contains_path(self, path: str) -> bool: ...


def build_extension(
    chain: ValidatedChainState,
    changes: SelectedInputScope,
) -> VerifiedExtensionCandidate:
    """Build and replay-verify an extension against authenticated chain state."""

    _require_validated_chain_state(chain)
    current_files = {item.path: item for item in chain.logical_state}
    desired_files = {item.relative_path: item for item in changes.input_files}
    missing_paths = tuple(
        sorted(
            path
            for path in current_files
            if path not in desired_files and changes.contains_path(path)
        )
    )
    if missing_paths:
        raise ValueError("selected input scope would remove files; extensions cannot delete paths")
    input_files = tuple(
        item
        for item in changes.input_files
        if item.relative_path not in current_files
        or current_files[item.relative_path].data != item.data
        or current_files[item.relative_path].mtime != item.mtime
    )
    if not input_files:
        raise ValueError("extension requires at least one changed or new file")

    built = _build_extension_document(
        index=chain.head_index + 1,
        parent_doc_hash=chain.head_doc_hash,
        root_doc_hash=chain.root_doc_hash,
        chunking=chain.chunking,
        input_files=input_files,
        input_origin=changes.input_origin,
        input_roots=changes.input_roots,
        chunker=default_extension_chunker,
        existing_file_sizes={item.path: item.size for item in chain.logical_state},
        existing_chunks=dict(chain.available_chunks),
        existing_logical_bytes=sum(item.size for item in chain.logical_state),
    )
    resulting_state = _replay_extension_candidate(chain, built.document)
    return VerifiedExtensionCandidate(
        document=built.document,
        stats=built.stats,
        resulting_state=resulting_state,
    )


def _build_extension_document(
    *,
    index: int,
    parent_doc_hash: bytes,
    root_doc_hash: bytes,
    chunking: ExtensionChunkingProfile,
    input_files: Sequence[ExtensionInputFile],
    input_origin: str,
    input_roots: Sequence[str],
    chunker: Chunker,
    existing_file_sizes: Mapping[str, int],
    existing_chunks: Mapping[bytes, bytes] | None = None,
    existing_logical_bytes: int = 0,
) -> _BuiltExtensionDocument:
    """Build a validated extension envelope from changed/new input files."""

    normalized_files = tuple(
        sorted(
            input_files,
            key=lambda item: normalize_manifest_path(
                item.relative_path,
                label="extension file path",
            ),
        )
    )
    if not normalized_files:
        raise ValueError("extension document requires at least one changed file")

    files: list[ExtensionFile] = []
    known_chunks = _normalize_chunk_map(existing_chunks)
    known_chunk_ids = set(known_chunks)
    chunk_records: dict[bytes, ExtensionChunkRecord] = {}
    logical_bytes = 0
    total_logical_bytes = require_non_negative_int(
        existing_logical_bytes,
        label="existing logical bytes",
    )
    new_chunks = 0
    reused_chunks = 0
    if total_logical_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError("root logical bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES")
    known_file_sizes = _normalize_existing_file_sizes(existing_file_sizes)
    if sum(known_file_sizes.values()) != total_logical_bytes:
        raise ValueError("existing logical bytes must match existing file size total")
    if len(known_file_sizes) > MAX_MANIFEST_FILES:
        raise ValueError(
            "existing logical state exceeds MAX_MANIFEST_FILES "
            f"({MAX_MANIFEST_FILES}): {len(known_file_sizes)} entries"
        )
    final_file_sizes = dict(known_file_sizes)
    final_logical_bytes = total_logical_bytes
    for item in normalized_files:
        normalized_path = normalize_manifest_path(item.relative_path, label="extension file path")
        previous_size = final_file_sizes.get(normalized_path, 0)
        final_logical_bytes += len(item.data) - previous_size
        final_file_sizes[normalized_path] = len(item.data)
    if len(final_file_sizes) > MAX_MANIFEST_FILES:
        raise ValueError(
            "logical latest state exceeds MAX_MANIFEST_FILES "
            f"({MAX_MANIFEST_FILES}): {len(final_file_sizes)} entries"
        )
    if final_logical_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError("logical latest state exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES")

    for item in normalized_files:
        logical_bytes += len(item.data)
        chunk_refs, file_sha256, item_new_chunks, item_reused_chunks = _chunk_refs_for_file(
            data=item.data,
            chunking=chunking,
            chunker=chunker,
            known_chunks=known_chunks,
            known_chunk_ids=known_chunk_ids,
            emitted_chunks=chunk_records,
        )
        new_chunks += item_new_chunks
        reused_chunks += item_reused_chunks
        files.append(
            ExtensionFile(
                path=item.relative_path,
                size=len(item.data),
                sha256=file_sha256,
                mtime=item.mtime,
                chunk_refs=chunk_refs,
            )
        )

    chunks = tuple(chunk_records[chunk_id] for chunk_id in sorted(chunk_records))

    document = ExtensionEnvelope(
        header=build_extension_header(
            index=index,
            parent_doc_hash=parent_doc_hash,
            root_doc_hash=root_doc_hash,
            chunking=chunking,
            input_origin=input_origin,
            input_roots=tuple(input_roots),
        ),
        files=tuple(files),
        chunks=chunks,
    )
    return _BuiltExtensionDocument(
        document=document,
        stats=ExtensionBuildStats(
            changed_file_count=len(normalized_files),
            logical_bytes=logical_bytes,
            new_chunks=new_chunks,
            reused_chunks=reused_chunks,
        ),
    )


def _chunk_refs_for_file(
    *,
    data: bytes,
    chunking: ExtensionChunkingProfile,
    chunker: Chunker,
    known_chunks: dict[bytes, bytes],
    known_chunk_ids: set[bytes],
    emitted_chunks: dict[bytes, ExtensionChunkRecord],
) -> tuple[tuple[ExtensionChunkRef, ...], bytes, int, int]:
    raw_ranges = tuple(chunker(data, chunking))
    if not data:
        if raw_ranges:
            raise ValueError("empty file chunker output must be empty")
        return (), hashlib.sha256().digest(), 0, 0
    if not raw_ranges:
        raise ValueError("non-empty file chunker output must contain at least one chunk")

    refs: list[ExtensionChunkRef] = []
    file_hasher = hashlib.sha256()
    new_chunks = 0
    reused_chunks = 0
    offset = 0
    data_view = memoryview(data)
    for start, end in raw_ranges:
        if start != offset or end <= start or end > len(data_view):
            raise ValueError("chunker ranges must contiguously cover the original input bytes")
        chunk_view = data_view[start:end]
        if not chunk_view:
            raise ValueError("chunker must not emit empty chunks")
        file_hasher.update(chunk_view)
        chunk_id = hashlib.sha256(chunk_view).digest()
        existing = known_chunks.get(chunk_id)
        if existing is None and chunk_id not in known_chunk_ids:
            chunk_bytes = chunk_view.tobytes()
            known_chunk_ids.add(chunk_id)
            known_chunks[chunk_id] = chunk_bytes
            emitted_chunks[chunk_id] = _build_chunk_record(
                chunk_id=chunk_id,
                chunk_bytes=chunk_bytes,
            )
            new_chunks += 1
        elif existing is not None and existing != chunk_view:
            raise ValueError("chunk payload collision for identical sha256 chunk_id")
        else:
            reused_chunks += 1
        refs.append(
            ExtensionChunkRef(
                chunk_id=chunk_id,
                uncompressed_len=len(chunk_view),
            )
        )
        offset = end

    if offset != len(data):
        raise ValueError("chunker output must fully cover the input file bytes")
    if chunker is not default_extension_chunker and raw_ranges != default_extension_chunker(
        data, chunking
    ):
        raise ValueError("chunker output does not match locked extension chunking profile")

    return tuple(refs), file_hasher.digest(), new_chunks, reused_chunks


def build_virtual_chunk_source(
    file_payloads: Sequence[bytes],
    *,
    chunking: ExtensionChunkingProfile,
    chunker: Chunker,
) -> dict[bytes, bytes]:
    known_chunks: dict[bytes, bytes] = {}
    known_chunk_ids: set[bytes] = set()
    emitted_chunks: dict[bytes, ExtensionChunkRecord] = {}
    for payload in file_payloads:
        _chunk_refs_for_file(
            data=bytes(payload),
            chunking=chunking,
            chunker=chunker,
            known_chunks=known_chunks,
            known_chunk_ids=known_chunk_ids,
            emitted_chunks=emitted_chunks,
        )
    return known_chunks


def _build_chunk_record(*, chunk_id: bytes, chunk_bytes: bytes) -> ExtensionChunkRecord:
    raw_record = ExtensionChunkRecord(
        chunk_id=chunk_id,
        codec=CHUNK_CODEC_RAW,
        raw_len=len(chunk_bytes),
        data=chunk_bytes,
    )
    compressed = gzip.compress(chunk_bytes, compresslevel=9, mtime=0)
    if len(compressed) >= len(chunk_bytes):
        return raw_record
    gzip_record = ExtensionChunkRecord(
        chunk_id=chunk_id,
        codec=CHUNK_CODEC_GZIP,
        raw_len=len(chunk_bytes),
        data=compressed,
    )
    return gzip_record


def _normalize_chunk_map(chunk_map: Mapping[bytes, bytes] | None) -> dict[bytes, bytes]:
    if chunk_map is None:
        return {}

    normalized: dict[bytes, bytes] = {}
    for chunk_id, chunk_bytes in chunk_map.items():
        raw_chunk_id = bytes(chunk_id)
        raw_chunk_bytes = bytes(chunk_bytes)
        if len(raw_chunk_id) != 32:
            raise ValueError("existing chunk_id must be 32 bytes")
        if hashlib.sha256(raw_chunk_bytes).digest() != raw_chunk_id:
            raise ValueError("existing chunk bytes do not hash to chunk_id")
        normalized[raw_chunk_id] = raw_chunk_bytes
    return normalized


def _normalize_existing_file_sizes(
    file_sizes: Mapping[str, int],
) -> dict[str, int]:
    if file_sizes is None:
        raise ValueError("existing file sizes are required")

    return {
        normalize_manifest_path(path, label="extension file path"): require_non_negative_int(
            size,
            label="existing file size",
        )
        for path, size in file_sizes.items()
    }


__all__ = [
    "Chunker",
    "ExtensionBuildStats",
    "SelectedInputScope",
    "VerifiedExtensionCandidate",
    "build_extension",
    "build_virtual_chunk_source",
    "default_extension_chunker",
]
