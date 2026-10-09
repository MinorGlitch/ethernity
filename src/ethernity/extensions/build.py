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

"""Assemble extension documents from changed-file payloads."""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES, MAX_MANIFEST_FILES
from ethernity.core.validation import (
    normalize_manifest_path,
    require_non_negative_int,
    validate_manifest_file_tree,
)
from ethernity.extensions.chain import (
    ReconstructedFile,
    ValidatedChainState,
    _replay_extension_candidate,
    _require_validated_chain_state,
)
from ethernity.extensions.chunk_map import normalize_chunk_map
from ethernity.formats.extension_chunking import default_extension_chunker
from ethernity.formats.extension_constants import CHUNK_CODEC_GZIP, CHUNK_CODEC_RAW
from ethernity.formats.extension_document import (
    ExtensionChunkingProfile,
    ExtensionChunkRecord,
    ExtensionChunkRef,
    ExtensionDocument,
    ExtensionFile,
    build_extension_header,
)
from ethernity.formats.extension_mode import UpdateMode, resolve_update_mode


@dataclass(frozen=True)
class ExtensionBuildStats:
    changed_file_count: int
    file_bytes: int
    new_chunks: int
    reused_chunks: int


@dataclass(frozen=True)
class _BuiltExtensionDocument:
    document: ExtensionDocument
    stats: ExtensionBuildStats


@dataclass(frozen=True)
class VerifiedExtensionCandidate:
    """Extension document checked by replay against an authenticated chain state."""

    document: ExtensionDocument
    stats: ExtensionBuildStats
    resulting_state: tuple[ReconstructedFile, ...]


class ExtensionInputFile(Protocol):
    @property
    def relative_path(self) -> str: ...

    @property
    def data(self) -> bytes: ...

    @property
    def mtime(self) -> int | None: ...


class ExtensionInputScope(Protocol):
    """Input-scope interface consumed by the extension builder."""

    @property
    def input_files(self) -> Sequence[ExtensionInputFile]: ...

    def contains_path(self, path: str) -> bool: ...


@dataclass(frozen=True)
class _SnapshotInputFile:
    relative_path: str
    data: bytes
    mtime: int | None


def build_extension(
    chain: ValidatedChainState,
    changes: ExtensionInputScope,
    *,
    update_mode: UpdateMode | None = None,
) -> VerifiedExtensionCandidate:
    """Build and replay-verify an extension against authenticated chain state."""

    _require_validated_chain_state(chain)
    mode = resolve_update_mode(chain.update_mode, update_mode)
    current_files = {item.path: item for item in chain.files}
    desired_files = {item.relative_path: item for item in changes.input_files}
    if len(desired_files) != len(changes.input_files):
        raise ValueError("duplicate extension input paths")
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

    base_files = chain.files
    base_chunks = chain.available_chunks
    if mode == UpdateMode.CUMULATIVE:
        base_files = chain.root_files
        base_chunks = chain.root_chunks
        target: dict[str, ExtensionInputFile] = {
            item.path: _SnapshotInputFile(item.path, item.data, item.mtime) for item in chain.files
        }
        target.update(desired_files)
        original = {item.path: item for item in base_files}
        input_files = tuple(
            item
            for path, item in sorted(target.items())
            if path not in original
            or item.data != original[path].data
            or item.mtime != original[path].mtime
        )

    built = _build_extension_document(
        index=chain.head_index + 1,
        parent_doc_hash=chain.root_doc_hash
        if mode == UpdateMode.CUMULATIVE
        else chain.head_doc_hash,
        root_doc_hash=chain.root_doc_hash,
        chunking=chain.chunking,
        input_files=input_files,
        existing_file_sizes={item.path: item.size for item in base_files},
        existing_chunks=dict(base_chunks),
        existing_file_bytes=sum(item.size for item in base_files),
        update_mode=mode,
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
    existing_file_sizes: Mapping[str, int],
    existing_chunks: Mapping[bytes, bytes] | None = None,
    existing_file_bytes: int = 0,
    update_mode: UpdateMode = UpdateMode.INCREMENTAL,
) -> _BuiltExtensionDocument:
    """Build a validated extension document from changed/new input files."""

    normalized_files = tuple(
        sorted(
            input_files,
            key=lambda item: normalize_manifest_path(
                item.relative_path,
                label="extension file path",
            ),
        )
    )
    if not normalized_files and update_mode != UpdateMode.CUMULATIVE:
        raise ValueError("extension document requires at least one changed file")

    files: list[ExtensionFile] = []
    known_chunks = normalize_chunk_map(existing_chunks)
    known_chunk_ids = set(known_chunks)
    chunk_records: dict[bytes, ExtensionChunkRecord] = {}
    file_bytes = 0
    total_file_bytes = require_non_negative_int(
        existing_file_bytes,
        label="existing file bytes",
    )
    new_chunks = 0
    reused_chunks = 0
    if total_file_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError("root file bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES")
    known_file_sizes = _normalize_existing_file_sizes(existing_file_sizes)
    if sum(known_file_sizes.values()) != total_file_bytes:
        raise ValueError("existing file bytes must match existing file size total")
    if len(known_file_sizes) > MAX_MANIFEST_FILES:
        raise ValueError(
            "existing file set exceeds MAX_MANIFEST_FILES "
            f"({MAX_MANIFEST_FILES}): {len(known_file_sizes)} entries"
        )
    final_file_sizes = dict(known_file_sizes)
    final_file_bytes = total_file_bytes
    for item in normalized_files:
        normalized_path = normalize_manifest_path(item.relative_path, label="extension file path")
        previous_size = final_file_sizes.get(normalized_path, 0)
        final_file_bytes += len(item.data) - previous_size
        final_file_sizes[normalized_path] = len(item.data)
    if len(final_file_sizes) > MAX_MANIFEST_FILES:
        raise ValueError(
            "latest file set exceeds MAX_MANIFEST_FILES "
            f"({MAX_MANIFEST_FILES}): {len(final_file_sizes)} entries"
        )
    if final_file_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError("latest file set exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES")
    validate_manifest_file_tree(final_file_sizes, label="reconstructed file paths")

    for item in normalized_files:
        file_bytes += len(item.data)
        chunk_refs, file_sha256, item_new_chunks, item_reused_chunks = _chunk_refs_for_file(
            data=item.data,
            chunking=chunking,
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

    document = ExtensionDocument(
        header=build_extension_header(
            index=index,
            parent_doc_hash=parent_doc_hash,
            root_doc_hash=root_doc_hash,
            chunking=chunking,
            update_mode=update_mode,
        ),
        files=tuple(files),
        chunks=chunks,
    )
    return _BuiltExtensionDocument(
        document=document,
        stats=ExtensionBuildStats(
            changed_file_count=len(normalized_files),
            file_bytes=file_bytes,
            new_chunks=new_chunks,
            reused_chunks=reused_chunks,
        ),
    )


def _chunk_refs_for_file(
    *,
    data: bytes,
    chunking: ExtensionChunkingProfile,
    known_chunks: dict[bytes, bytes],
    known_chunk_ids: set[bytes],
    emitted_chunks: dict[bytes, ExtensionChunkRecord],
) -> tuple[tuple[ExtensionChunkRef, ...], bytes, int, int]:
    raw_ranges = default_extension_chunker(data, chunking)
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
    return tuple(refs), file_hasher.digest(), new_chunks, reused_chunks


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
    "ExtensionBuildStats",
    "ExtensionInputScope",
    "VerifiedExtensionCandidate",
    "build_extension",
]
