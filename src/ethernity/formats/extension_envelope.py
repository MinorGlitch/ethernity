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

"""Extension envelope types, validation, and codec helpers."""

from __future__ import annotations

import hashlib
import time
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES, MAX_MANIFEST_CBOR_BYTES
from ethernity.core.validation import (
    normalize_manifest_path,
    normalize_path,
    require_bytes,
    require_dict,
    require_int,
    require_keys,
    require_list,
    require_non_empty_bytes,
    require_non_empty_str,
    require_non_negative_int,
    require_positive_int,
    require_str,
)
from ethernity.encoding.cbor import dumps_canonical, loads_canonical
from ethernity.encoding.varint import decode_uvarint, encode_uvarint
from ethernity.formats.envelope_codec import MAGIC
from ethernity.formats.envelope_types import MAX_MANIFEST_FILES
from ethernity.formats.extension_envelope_constants import (
    CHAIN_ID_PERSONALIZATION,
    CHUNK_ALGORITHM_FASTCDC,
    CHUNK_CODEC_GZIP,
    CHUNK_CODEC_RAW,
    EXTENSION_ENVELOPE_VERSION,
    EXTENSION_SCHEMA_VERSION,
)

_HEADER_VERSION = 1
_HEADER_INDEX = 2
_HEADER_PARENT_DOC_HASH = 4
_HEADER_ROOT_DOC_HASH = 5
_HEADER_CREATED_AT = 7
_HEADER_CHUNKING = 10
_HEADER_INPUT_ORIGIN = 11
_HEADER_INPUT_ROOTS = 12

_ALLOWED_HEADER_KEYS = frozenset(
    {
        _HEADER_VERSION,
        _HEADER_INDEX,
        _HEADER_PARENT_DOC_HASH,
        _HEADER_ROOT_DOC_HASH,
        _HEADER_CREATED_AT,
        _HEADER_CHUNKING,
        _HEADER_INPUT_ORIGIN,
        _HEADER_INPUT_ROOTS,
    }
)

_BODY_FILES = 1
_BODY_CHUNKS = 2


def _require_exact_int_keys(
    mapping: dict[object, object],
    *,
    allowed_keys: frozenset[int] | set[int],
    label: str,
) -> None:
    invalid_keys = [key for key in mapping if isinstance(key, bool) or not isinstance(key, int)]
    if invalid_keys:
        raise ValueError(f"{label} keys must be integers")
    unknown_keys = [key for key in mapping if key not in allowed_keys]
    if unknown_keys:
        raise ValueError(f"{label} contains unknown keys")


def derive_chain_id(root_doc_hash: bytes) -> bytes:
    """Derive the deterministic chain id from the root ciphertext hash."""

    root_hash = require_bytes(root_doc_hash, 32, label="root_doc_hash")
    return hashlib.blake2b(CHAIN_ID_PERSONALIZATION + root_hash, digest_size=32).digest()


@dataclass(frozen=True)
class ExtensionChunkingProfile:
    """The locked chain chunking profile for extension recipes."""

    algorithm_id: int
    target_size: int
    min_size: int
    max_size: int

    def __post_init__(self) -> None:
        algorithm_id = require_positive_int(
            self.algorithm_id,
            label="extension chunking algorithm_id",
        )
        if algorithm_id != CHUNK_ALGORITHM_FASTCDC:
            raise ValueError("extension chunking algorithm_id must be CHUNK_ALGORITHM_FASTCDC (1)")
        target_size = require_positive_int(self.target_size, label="extension chunking target_size")
        min_size = require_positive_int(self.min_size, label="extension chunking min_size")
        max_size = require_positive_int(self.max_size, label="extension chunking max_size")
        if min_size > target_size or target_size > max_size:
            raise ValueError("extension chunking sizes must satisfy min <= target <= max")
        object.__setattr__(self, "algorithm_id", algorithm_id)
        object.__setattr__(self, "target_size", target_size)
        object.__setattr__(self, "min_size", min_size)
        object.__setattr__(self, "max_size", max_size)

    def to_cbor(self) -> list[int]:
        return [self.algorithm_id, self.target_size, self.min_size, self.max_size]

    @classmethod
    def from_cbor(cls, value: object) -> "ExtensionChunkingProfile":
        fields = require_list(value, 4, label="extension chunking")
        if len(fields) != 4:
            raise ValueError("extension chunking must contain exactly 4 items")
        return cls(
            algorithm_id=require_int(fields[0], label="extension chunking algorithm_id"),
            target_size=require_int(fields[1], label="extension chunking target_size"),
            min_size=require_int(fields[2], label="extension chunking min_size"),
            max_size=require_int(fields[3], label="extension chunking max_size"),
        )


@dataclass(frozen=True)
class ExtensionChunkRef:
    """A recipe reference to one resolved chunk."""

    chunk_id: bytes
    uncompressed_len: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "chunk_id", require_bytes(self.chunk_id, 32, label="extension chunk_ref chunk_id")
        )
        object.__setattr__(
            self,
            "uncompressed_len",
            require_positive_int(
                self.uncompressed_len,
                label="extension chunk_ref uncompressed_len",
            ),
        )

    def to_cbor(self) -> list[object]:
        return [self.chunk_id, self.uncompressed_len]

    @classmethod
    def from_cbor(cls, value: object) -> "ExtensionChunkRef":
        fields = require_list(value, 2, label="extension chunk_ref")
        if len(fields) != 2:
            raise ValueError("extension chunk_ref must contain exactly 2 items")
        return cls(
            chunk_id=fields[0] if isinstance(fields[0], (bytes, bytearray)) else fields[0],
            uncompressed_len=require_int(fields[1], label="extension chunk_ref uncompressed_len"),
        )


@dataclass(frozen=True)
class ExtensionFile:
    """A changed-path file recipe stored in the extension body."""

    path: str
    size: int
    sha256: bytes
    mtime: int | None
    chunk_refs: tuple[ExtensionChunkRef, ...]

    def __post_init__(self) -> None:
        path = normalize_manifest_path(self.path, label="extension file path")
        size = require_non_negative_int(self.size, label="extension file size")
        sha256 = require_bytes(self.sha256, 32, label="extension file sha256")
        if self.mtime is not None:
            mtime = require_int(self.mtime, label="extension file mtime")
        else:
            mtime = None
        chunk_refs = tuple(self.chunk_refs)
        if size == 0:
            if chunk_refs:
                raise ValueError("zero-length extension files must have empty chunk_refs")
        else:
            if not chunk_refs:
                raise ValueError("non-empty extension files must include chunk_refs")
            total = sum(chunk_ref.uncompressed_len for chunk_ref in chunk_refs)
            if total != size:
                raise ValueError("extension file chunk_refs must sum to file size")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "size", size)
        object.__setattr__(self, "sha256", sha256)
        object.__setattr__(self, "mtime", mtime)
        object.__setattr__(self, "chunk_refs", chunk_refs)

    def to_cbor(self) -> list[object]:
        return [
            self.path,
            self.size,
            self.sha256,
            self.mtime,
            [chunk_ref.to_cbor() for chunk_ref in self.chunk_refs],
        ]

    @classmethod
    def from_cbor(cls, value: object) -> "ExtensionFile":
        fields = require_list(value, 5, label="extension file")
        if len(fields) != 5:
            raise ValueError("extension file must contain exactly 5 items")
        raw_chunk_refs = require_list(fields[4], 0, label="extension file chunk_refs")
        return cls(
            path=require_non_empty_str(fields[0], label="extension file path"),
            size=require_int(fields[1], label="extension file size"),
            sha256=fields[2] if isinstance(fields[2], (bytes, bytearray)) else fields[2],
            mtime=(
                None if fields[3] is None else require_int(fields[3], label="extension file mtime")
            ),
            chunk_refs=tuple(ExtensionChunkRef.from_cbor(item) for item in raw_chunk_refs),
        )


@dataclass(frozen=True)
class ExtensionChunkRecord:
    """A newly introduced chunk stored inline in the extension body."""

    chunk_id: bytes
    codec: int
    raw_len: int
    data: bytes

    def __post_init__(self) -> None:
        chunk_id = require_bytes(self.chunk_id, 32, label="extension chunk chunk_id")
        codec = require_int(self.codec, label="extension chunk codec")
        if codec not in {CHUNK_CODEC_RAW, CHUNK_CODEC_GZIP}:
            raise ValueError("extension chunk codec must be one of: 0, 1")
        raw_len = require_positive_int(self.raw_len, label="extension chunk raw_len")
        if raw_len > MAX_DECOMPRESSED_PAYLOAD_BYTES:
            raise ValueError(
                "extension chunk raw_len exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES "
                f"({MAX_DECOMPRESSED_PAYLOAD_BYTES})"
            )
        data = require_non_empty_bytes(self.data, label="extension chunk data")
        object.__setattr__(self, "chunk_id", chunk_id)
        object.__setattr__(self, "codec", codec)
        object.__setattr__(self, "raw_len", raw_len)
        object.__setattr__(self, "data", data)

    def to_cbor(self) -> list[object]:
        return [self.chunk_id, self.codec, self.raw_len, self.data]

    def decode_data(self) -> bytes:
        if self.codec == CHUNK_CODEC_RAW:
            if len(self.data) != self.raw_len:
                raise ValueError("raw extension chunk data length must equal raw_len")
            decoded = self.data
        else:
            decoded = _decode_gzip_chunk(self.data, expected_len=self.raw_len)
        if hashlib.sha256(decoded).digest() != self.chunk_id:
            raise ValueError("extension chunk bytes do not hash to chunk_id")
        return decoded

    @classmethod
    def from_cbor(cls, value: object) -> "ExtensionChunkRecord":
        fields = require_list(value, 4, label="extension chunk")
        if len(fields) != 4:
            raise ValueError("extension chunk must contain exactly 4 items")
        record = cls(
            chunk_id=fields[0] if isinstance(fields[0], (bytes, bytearray)) else fields[0],
            codec=require_int(fields[1], label="extension chunk codec"),
            raw_len=require_int(fields[2], label="extension chunk raw_len"),
            data=fields[3] if isinstance(fields[3], (bytes, bytearray)) else fields[3],
        )
        record.decode_data()
        return record


@dataclass(frozen=True)
class ExtensionEnvelopeHeader:
    """Authenticated extension header metadata."""

    version: int
    index: int
    parent_doc_hash: bytes
    root_doc_hash: bytes
    created_at: int
    chunking: ExtensionChunkingProfile
    input_origin: str
    input_roots: tuple[str, ...]

    def __post_init__(self) -> None:
        version = require_int(self.version, label="extension header version")
        if version != EXTENSION_SCHEMA_VERSION:
            raise ValueError(f"unsupported extension header version: {version}")
        index = require_positive_int(self.index, label="extension header index")
        parent_doc_hash = require_bytes(
            self.parent_doc_hash, 32, label="extension header parent_doc_hash"
        )
        root_doc_hash = require_bytes(
            self.root_doc_hash,
            32,
            label="extension header root_doc_hash",
        )
        created_at = require_int(self.created_at, label="extension header created_at")
        chunking = self.chunking
        if not isinstance(chunking, ExtensionChunkingProfile):
            raise ValueError("extension header chunking must be an ExtensionChunkingProfile")
        input_origin = require_str(self.input_origin, label="extension header input_origin")
        if input_origin not in {"file", "directory", "mixed"}:
            raise ValueError("extension header input_origin must be one of: file, directory, mixed")
        normalized_roots = tuple(_normalize_root_label(root) for root in self.input_roots)
        _validate_input_origin_roots(input_origin, normalized_roots)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "parent_doc_hash", parent_doc_hash)
        object.__setattr__(self, "root_doc_hash", root_doc_hash)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "chunking", chunking)
        object.__setattr__(self, "input_origin", input_origin)
        object.__setattr__(self, "input_roots", normalized_roots)

    def to_cbor(self) -> dict[int, object]:
        return {
            _HEADER_VERSION: self.version,
            _HEADER_INDEX: self.index,
            _HEADER_PARENT_DOC_HASH: self.parent_doc_hash,
            _HEADER_ROOT_DOC_HASH: self.root_doc_hash,
            _HEADER_CREATED_AT: self.created_at,
            _HEADER_CHUNKING: self.chunking.to_cbor(),
            _HEADER_INPUT_ORIGIN: self.input_origin,
            _HEADER_INPUT_ROOTS: list(self.input_roots),
        }

    @classmethod
    def from_cbor(cls, value: object) -> "ExtensionEnvelopeHeader":
        header = require_dict(value, label="extension header")
        _require_exact_int_keys(header, allowed_keys=_ALLOWED_HEADER_KEYS, label="extension header")
        require_keys(
            header,
            (
                _HEADER_VERSION,
                _HEADER_INDEX,
                _HEADER_PARENT_DOC_HASH,
                _HEADER_ROOT_DOC_HASH,
                _HEADER_CREATED_AT,
                _HEADER_CHUNKING,
                _HEADER_INPUT_ORIGIN,
                _HEADER_INPUT_ROOTS,
            ),
            label="extension header",
        )
        roots = require_list(header[_HEADER_INPUT_ROOTS], 0, label="extension header input_roots")
        return cls(
            version=require_int(header[_HEADER_VERSION], label="extension header version"),
            index=require_int(header[_HEADER_INDEX], label="extension header index"),
            parent_doc_hash=header[_HEADER_PARENT_DOC_HASH],
            root_doc_hash=header[_HEADER_ROOT_DOC_HASH],
            created_at=require_int(header[_HEADER_CREATED_AT], label="extension header created_at"),
            chunking=ExtensionChunkingProfile.from_cbor(header[_HEADER_CHUNKING]),
            input_origin=require_str(
                header[_HEADER_INPUT_ORIGIN], label="extension header input_origin"
            ),
            input_roots=tuple(
                normalize_path(root, label="extension header input_root") for root in roots
            ),
        )


@dataclass(frozen=True)
class ExtensionEnvelope:
    """One extension envelope with header and body."""

    header: ExtensionEnvelopeHeader
    files: tuple[ExtensionFile, ...]
    chunks: tuple[ExtensionChunkRecord, ...]

    def __post_init__(self) -> None:
        files = tuple(self.files)
        chunks = tuple(self.chunks)
        if not files:
            raise ValueError("extension body files are required")
        if len(files) > MAX_MANIFEST_FILES:
            raise ValueError(
                "extension files exceed MAX_MANIFEST_FILES "
                f"({MAX_MANIFEST_FILES}): {len(files)} entries"
            )
        seen_paths: set[str] = set()
        previous_path = ""
        for file_entry in files:
            if file_entry.path in seen_paths:
                raise ValueError(f"duplicate extension file path: {file_entry.path}")
            if previous_path and file_entry.path < previous_path:
                raise ValueError("extension files must be ordered by normalized path")
            previous_path = file_entry.path
            seen_paths.add(file_entry.path)
        seen_chunk_ids: set[bytes] = set()
        previous_chunk_id = b""
        total_inline_chunk_bytes = 0
        for chunk_record in chunks:
            total_inline_chunk_bytes += chunk_record.raw_len
            if total_inline_chunk_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
                raise ValueError(
                    "extension inline chunk bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES"
                )
            if chunk_record.chunk_id in seen_chunk_ids:
                raise ValueError("duplicate extension chunk_id")
            if previous_chunk_id and chunk_record.chunk_id < previous_chunk_id:
                raise ValueError("extension chunks must be ordered by raw chunk_id")
            previous_chunk_id = chunk_record.chunk_id
            seen_chunk_ids.add(chunk_record.chunk_id)
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "chunks", chunks)

    def to_cbor_sections(self) -> tuple[dict[int, object], dict[int, object]]:
        header = self.header.to_cbor()
        body: dict[int, object] = {
            _BODY_FILES: [file_entry.to_cbor() for file_entry in self.files],
            _BODY_CHUNKS: [chunk_record.to_cbor() for chunk_record in self.chunks],
        }
        return header, body

    def encode(self) -> bytes:
        for chunk_record in self.chunks:
            chunk_record.decode_data()
        header, body = self.to_cbor_sections()
        header_bytes = dumps_canonical(header)
        body_bytes = dumps_canonical(body)
        if len(header_bytes) > MAX_MANIFEST_CBOR_BYTES:
            raise ValueError(
                f"extension header exceeds MAX_MANIFEST_CBOR_BYTES ({MAX_MANIFEST_CBOR_BYTES})"
            )
        if len(body_bytes) > MAX_MANIFEST_CBOR_BYTES:
            raise ValueError(
                f"extension body exceeds MAX_MANIFEST_CBOR_BYTES ({MAX_MANIFEST_CBOR_BYTES})"
            )
        return b"".join(
            (
                MAGIC,
                encode_uvarint(EXTENSION_ENVELOPE_VERSION),
                encode_uvarint(len(header_bytes)),
                header_bytes,
                encode_uvarint(len(body_bytes)),
                body_bytes,
            )
        )

    def reconstruct_files(
        self,
        *,
        available_chunks: Mapping[bytes, bytes] | None = None,
    ) -> list[tuple[ExtensionFile, bytes]]:
        chunk_bytes = _normalize_available_chunks(available_chunks)
        for chunk_record in self.chunks:
            decoded_chunk = chunk_record.decode_data()
            existing = chunk_bytes.get(chunk_record.chunk_id)
            if existing is not None and existing != decoded_chunk:
                raise ValueError("extension available_chunks conflict with inline chunk bytes")
            chunk_bytes[chunk_record.chunk_id] = decoded_chunk
        reconstructed: list[tuple[ExtensionFile, bytes]] = []
        total_reconstructed = 0
        for file_entry in self.files:
            payload = bytearray()
            for chunk_ref in file_entry.chunk_refs:
                resolved = chunk_bytes.get(chunk_ref.chunk_id)
                if resolved is None:
                    raise ValueError("extension file references unresolved chunk_id")
                if len(resolved) != chunk_ref.uncompressed_len:
                    raise ValueError("extension chunk_ref length does not match resolved chunk")
                payload.extend(resolved)
            file_bytes = bytes(payload)
            if len(file_bytes) != file_entry.size:
                raise ValueError("extension reconstructed file size mismatch")
            if hashlib.sha256(file_bytes).digest() != file_entry.sha256:
                raise ValueError(f"extension file sha256 mismatch for {file_entry.path}")
            total_reconstructed += len(file_bytes)
            if total_reconstructed > MAX_DECOMPRESSED_PAYLOAD_BYTES:
                raise ValueError(
                    "extension reconstructed logical bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES"
                )
            reconstructed.append((file_entry, file_bytes))
        return reconstructed

    @classmethod
    def decode(cls, data: bytes) -> "ExtensionEnvelope":
        idx = 0
        if len(data) < len(MAGIC) + 1:
            raise ValueError("extension envelope too short")
        if data[: len(MAGIC)] != MAGIC:
            raise ValueError("invalid envelope magic")
        idx += len(MAGIC)

        version, idx = decode_uvarint(data, idx)
        if version != EXTENSION_ENVELOPE_VERSION:
            raise ValueError(f"unsupported envelope version: {version}")

        header_len, idx = decode_uvarint(data, idx)
        if header_len > MAX_MANIFEST_CBOR_BYTES:
            raise ValueError(
                f"extension header exceeds MAX_MANIFEST_CBOR_BYTES ({MAX_MANIFEST_CBOR_BYTES})"
            )
        header_end = idx + header_len
        if header_end > len(data):
            raise ValueError("truncated extension header")
        header = ExtensionEnvelopeHeader.from_cbor(
            loads_canonical(data[idx:header_end], label="extension header")
        )
        idx = header_end

        body_len, idx = decode_uvarint(data, idx)
        if body_len > MAX_MANIFEST_CBOR_BYTES:
            raise ValueError(
                f"extension body exceeds MAX_MANIFEST_CBOR_BYTES ({MAX_MANIFEST_CBOR_BYTES})"
            )
        body_end = idx + body_len
        if body_end != len(data):
            raise ValueError("extension body length mismatch")
        body = require_dict(
            loads_canonical(data[idx:body_end], label="extension body"),
            label="extension body",
        )
        _require_exact_int_keys(
            body,
            allowed_keys={_BODY_FILES, _BODY_CHUNKS},
            label="extension body",
        )
        require_keys(body, (_BODY_FILES, _BODY_CHUNKS), label="extension body")
        files_raw = require_list(body[_BODY_FILES], 1, label="extension body files")
        chunks_raw = require_list(body[_BODY_CHUNKS], 0, label="extension body chunks")
        _require_inline_chunk_raw_len_bounds(chunks_raw)
        return cls(
            header=header,
            files=tuple(ExtensionFile.from_cbor(item) for item in files_raw),
            chunks=tuple(ExtensionChunkRecord.from_cbor(item) for item in chunks_raw),
        )


def build_extension_header(
    *,
    index: int,
    parent_doc_hash: bytes,
    root_doc_hash: bytes,
    chunking: ExtensionChunkingProfile,
    input_origin: str,
    input_roots: tuple[str, ...] | list[str],
    created_at: int | None = None,
) -> ExtensionEnvelopeHeader:
    """Build a validated extension header with the derived chain id."""

    created = int(time.time()) if created_at is None else created_at
    root_hash = require_bytes(root_doc_hash, 32, label="root_doc_hash")
    return ExtensionEnvelopeHeader(
        version=EXTENSION_SCHEMA_VERSION,
        index=index,
        parent_doc_hash=parent_doc_hash,
        root_doc_hash=root_hash,
        created_at=created,
        chunking=chunking,
        input_origin=input_origin,
        input_roots=tuple(input_roots),
    )


def _decode_gzip_chunk(data: bytes, *, expected_len: int) -> bytes:
    decompressor = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    try:
        decoded = decompressor.decompress(data, max_length=expected_len + 1)
    except zlib.error as exc:
        raise ValueError("invalid gzip chunk") from exc
    if len(decoded) > expected_len:
        raise ValueError("decoded chunk exceeds raw_len")
    if decompressor.unconsumed_tail:
        raise ValueError("decoded chunk exceeds raw_len")
    try:
        decoded += decompressor.flush(expected_len + 1 - len(decoded))
    except zlib.error as exc:
        raise ValueError("invalid gzip chunk") from exc
    if len(decoded) > expected_len:
        raise ValueError("decoded chunk exceeds raw_len")
    if not decompressor.eof:
        raise ValueError("invalid gzip chunk")
    if decompressor.unused_data:
        raise ValueError("gzip chunk contains trailing data")
    if len(decoded) != expected_len:
        raise ValueError("decoded chunk length does not match raw_len")
    return decoded


def _normalize_available_chunks(
    available_chunks: Mapping[bytes, bytes] | None,
) -> dict[bytes, bytes]:
    if available_chunks is None:
        return {}
    normalized: dict[bytes, bytes] = {}
    for chunk_id, chunk_bytes in available_chunks.items():
        raw_chunk_id = require_bytes(chunk_id, 32, label="extension available chunk_id")
        raw_chunk_bytes = require_non_empty_bytes(
            chunk_bytes,
            label="extension available chunk bytes",
        )
        if hashlib.sha256(raw_chunk_bytes).digest() != raw_chunk_id:
            raise ValueError("extension available chunk bytes do not hash to chunk_id")
        normalized[raw_chunk_id] = raw_chunk_bytes
    return normalized


def _require_inline_chunk_raw_len_bounds(chunks_raw: Sequence[object]) -> None:
    total_raw_len = 0
    for item in chunks_raw:
        fields = require_list(item, 4, label="extension chunk")
        if len(fields) != 4:
            raise ValueError("extension chunk must contain exactly 4 items")
        raw_len = require_int(fields[2], label="extension chunk raw_len")
        if raw_len > MAX_DECOMPRESSED_PAYLOAD_BYTES:
            raise ValueError(
                "extension chunk raw_len exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES "
                f"({MAX_DECOMPRESSED_PAYLOAD_BYTES})"
            )
        total_raw_len += raw_len
        if total_raw_len > MAX_DECOMPRESSED_PAYLOAD_BYTES:
            raise ValueError("extension inline chunk bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES")


def _normalize_root_label(value: object) -> str:
    root = normalize_path(value, label="extension header input_root")
    root = root.strip()
    if not root:
        raise ValueError("extension header input_root must be a non-empty string")
    if "/" in root or "\\" in root:
        raise ValueError("extension header input_root must be a leaf label without path separators")
    return root


def _validate_input_origin_roots(input_origin: str, input_roots: tuple[str, ...]) -> None:
    if input_origin == "file":
        if input_roots:
            raise ValueError("extension header input_roots must be empty when input_origin is file")
        return
    if not input_roots:
        raise ValueError(
            "extension header input_roots must be non-empty for directory or mixed input"
        )


__all__ = [
    "ExtensionEnvelope",
    "ExtensionEnvelopeHeader",
    "ExtensionChunkingProfile",
    "ExtensionChunkRecord",
    "ExtensionChunkRef",
    "ExtensionFile",
    "build_extension_header",
    "derive_chain_id",
]
