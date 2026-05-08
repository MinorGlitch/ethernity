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
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ethernity.cli.shared.types import InputFile
from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES
from ethernity.core.validation import normalize_manifest_path
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
    ExtensionChunkRecord,
    ExtensionChunkRef,
    ExtensionEnvelope,
    ExtensionFile,
    build_extension_header,
)
from ethernity.formats.extension_envelope_constants import CHUNK_CODEC_GZIP, CHUNK_CODEC_RAW

Chunker = Callable[[bytes, ExtensionChunkingProfile], Sequence[bytes]]

_ROLLING_HASH_MASK = (1 << 64) - 1
_MIN_MASK_BITS = 4
_ROLLING_WINDOW_SIZE = 64


def _build_gear_table() -> tuple[int, ...]:
    state = 0x9E3779B97F4A7C15
    values: list[int] = []
    for _index in range(256):
        state ^= (state >> 12) & _ROLLING_HASH_MASK
        state ^= (state << 25) & _ROLLING_HASH_MASK
        state ^= (state >> 27) & _ROLLING_HASH_MASK
        state = (state * 0x2545F4914F6CDD1D) & _ROLLING_HASH_MASK
        values.append(state)
    return tuple(values)


_GEAR_TABLE = _build_gear_table()


@dataclass(frozen=True)
class ExtensionBuildStats:
    changed_file_count: int
    logical_bytes: int
    new_chunks: int
    reused_chunks: int


@dataclass(frozen=True)
class BuiltExtensionDocument:
    document: ExtensionEnvelope
    stats: ExtensionBuildStats


def build_extension_document(
    *,
    index: int,
    parent_doc_hash: bytes,
    root_doc_hash: bytes,
    chunking: ExtensionChunkingProfile,
    input_files: Sequence[InputFile],
    input_origin: str,
    input_roots: Sequence[str],
    chunker: Chunker,
    existing_chunks: Mapping[bytes, bytes] | None = None,
    existing_logical_bytes: int = 0,
    existing_file_sizes: Mapping[str, int] | None = None,
) -> BuiltExtensionDocument:
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
    chunk_payloads: dict[bytes, bytes] = {}
    logical_bytes = 0
    total_logical_bytes = existing_logical_bytes
    new_chunks = 0
    reused_chunks = 0
    if total_logical_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError("root logical bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES")
    known_file_sizes = {
        normalize_manifest_path(path, label="extension file path"): size
        for path, size in (existing_file_sizes or {}).items()
    }

    for item in normalized_files:
        logical_bytes += len(item.data)
        normalized_path = normalize_manifest_path(item.relative_path, label="extension file path")
        previous_size = known_file_sizes.get(normalized_path, 0)
        total_logical_bytes += len(item.data) - previous_size
        if total_logical_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
            raise ValueError("logical latest state exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES")
        chunk_refs, item_new_chunks, item_reused_chunks = _chunk_refs_for_file(
            data=item.data,
            chunking=chunking,
            chunker=chunker,
            known_chunks=known_chunks,
            emitted_chunks=chunk_payloads,
        )
        new_chunks += item_new_chunks
        reused_chunks += item_reused_chunks
        known_file_sizes[normalized_path] = len(item.data)
        files.append(
            ExtensionFile(
                path=item.relative_path,
                size=len(item.data),
                sha256=hashlib.sha256(item.data).digest(),
                mtime=item.mtime,
                chunk_refs=chunk_refs,
            )
        )

    chunks = tuple(
        _build_chunk_record(chunk_id=chunk_id, chunk_bytes=chunk_payloads[chunk_id])
        for chunk_id in sorted(chunk_payloads)
    )

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
    return BuiltExtensionDocument(
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
    emitted_chunks: dict[bytes, bytes],
) -> tuple[tuple[ExtensionChunkRef, ...], int, int]:
    raw_chunks = tuple(bytes(chunk) for chunk in chunker(data, chunking))
    if not data:
        if raw_chunks:
            raise ValueError("empty file chunker output must be empty")
        return (), 0, 0
    if not raw_chunks:
        raise ValueError("non-empty file chunker output must contain at least one chunk")

    refs: list[ExtensionChunkRef] = []
    total = 0
    new_chunks = 0
    reused_chunks = 0
    offset = 0
    for chunk_bytes in raw_chunks:
        if not chunk_bytes:
            raise ValueError("chunker must not emit empty chunks")
        chunk_id = hashlib.sha256(chunk_bytes).digest()
        next_offset = offset + len(chunk_bytes)
        if data[offset:next_offset] != chunk_bytes:
            raise ValueError("chunker output must preserve the original input bytes")
        total += len(chunk_bytes)
        existing = known_chunks.get(chunk_id)
        if existing is None:
            known_chunks[chunk_id] = chunk_bytes
            emitted_chunks[chunk_id] = chunk_bytes
            new_chunks += 1
        elif existing != chunk_bytes:
            raise ValueError("chunk payload collision for identical sha256 chunk_id")
        else:
            reused_chunks += 1
        refs.append(
            ExtensionChunkRef(
                chunk_id=chunk_id,
                uncompressed_len=len(chunk_bytes),
            )
        )
        offset = next_offset

    if total != len(data):
        raise ValueError("chunker output must fully cover the input file bytes")

    return tuple(refs), new_chunks, reused_chunks


def default_extension_chunker(
    data: bytes,
    profile: ExtensionChunkingProfile,
) -> tuple[bytes, ...]:
    if not data:
        return ()
    chunks: list[bytes] = []
    start = 0
    data_view = memoryview(data)
    primary_mask, secondary_mask = _rolling_masks(profile.target_size)
    while start < len(data):
        chunk_end = _next_chunk_boundary(
            data_view,
            start=start,
            min_size=profile.min_size,
            target_size=profile.target_size,
            max_size=profile.max_size,
            primary_mask=primary_mask,
            secondary_mask=secondary_mask,
        )
        chunks.append(bytes(data_view[start:chunk_end]))
        start = chunk_end
    return tuple(chunks)


def build_virtual_chunk_source(
    file_payloads: Sequence[bytes],
    *,
    chunking: ExtensionChunkingProfile,
    chunker: Chunker,
) -> dict[bytes, bytes]:
    known_chunks: dict[bytes, bytes] = {}
    emitted_chunks: dict[bytes, bytes] = {}
    for payload in file_payloads:
        _chunk_refs_for_file(
            data=bytes(payload),
            chunking=chunking,
            chunker=chunker,
            known_chunks=known_chunks,
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
    gzip_record.decode_data()
    return gzip_record


def _rolling_masks(target_size: int) -> tuple[int, int]:
    target_bits = max(_MIN_MASK_BITS, int(round(math.log2(max(2, target_size)))))
    primary_bits = min(63, target_bits)
    secondary_bits = max(_MIN_MASK_BITS, target_bits - 2)
    return (1 << primary_bits) - 1, (1 << secondary_bits) - 1


def _next_chunk_boundary(
    data: memoryview,
    *,
    start: int,
    min_size: int,
    target_size: int,
    max_size: int,
    primary_mask: int,
    secondary_mask: int,
) -> int:
    total_len = len(data)
    if total_len - start <= min_size:
        return total_len

    min_end = min(total_len, start + min_size)
    target_end = min(total_len, start + target_size)
    max_end = min(total_len, start + max_size)
    fingerprint = 0
    window = [0] * _ROLLING_WINDOW_SIZE
    window_count = 0
    window_pos = 0

    for index in range(start, max_end):
        byte_value = data[index]
        if window_count < _ROLLING_WINDOW_SIZE:
            fingerprint = _roll_fingerprint(fingerprint, byte_value)
            window[window_pos] = byte_value
            window_pos = (window_pos + 1) % _ROLLING_WINDOW_SIZE
            window_count += 1
        else:
            outgoing = window[window_pos]
            window[window_pos] = byte_value
            window_pos = (window_pos + 1) % _ROLLING_WINDOW_SIZE
            fingerprint = (
                _rotate_left(fingerprint, 1) ^ _GEAR_TABLE[outgoing] ^ _GEAR_TABLE[byte_value]
            ) & _ROLLING_HASH_MASK
        if index + 1 < min_end:
            continue
        mask = primary_mask if index + 1 < target_end else secondary_mask
        if fingerprint & mask == 0:
            return index + 1

    return max_end


def _roll_fingerprint(current: int, byte_value: int) -> int:
    return _rotate_left(current, 1) ^ _GEAR_TABLE[byte_value]


def _rotate_left(value: int, shift: int) -> int:
    shift &= 63
    return ((value << shift) | (value >> (64 - shift))) & _ROLLING_HASH_MASK


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


__all__ = [
    "BuiltExtensionDocument",
    "Chunker",
    "ExtensionBuildStats",
    "build_extension_document",
    "build_virtual_chunk_source",
    "default_extension_chunker",
]
