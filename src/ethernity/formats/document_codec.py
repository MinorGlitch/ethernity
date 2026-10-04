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

"""Encode, decode, and extract standalone backups and extension documents."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from ethernity.core.bounds import MAX_MANIFEST_CBOR_BYTES
from ethernity.core.validation import (
    normalize_manifest_path,
    normalize_path,
    validate_manifest_file_tree,
)
from ethernity.encoding.cbor import dumps_deterministic, loads_deterministic
from ethernity.encoding.varint import (
    decode_uvarint as _decode_uvarint,
    encode_uvarint as _encode_uvarint,
)
from ethernity.formats.document_constants import MAGIC, VERSION
from ethernity.formats.extension_document import ExtensionDocument
from ethernity.formats.manifest import (
    MANIFEST_VERSION,
    SIGNING_SEED_LEN,
    BackupFile,
    BackupManifest,
    ManifestFile,
)
from ethernity.formats.payload_codec import decode_payload_from_manifest


def build_single_file_manifest(
    input_path: str | None,
    payload: bytes,
    *,
    sealed: bool = False,
    created_at: float | None = None,
    signing_seed: bytes | None = None,
) -> BackupManifest:
    """Build a manifest for a single payload file-like input."""

    path = _normalize_path(input_path)
    mtime = _read_mtime(input_path)
    part = BackupFile(path=path, data=payload, mtime=mtime)
    manifest, _payload = build_manifest_and_payload(
        (part,),
        sealed=sealed,
        created_at=created_at,
        signing_seed=signing_seed,
        input_origin="file",
        input_roots=(),
    )
    return manifest


def build_manifest_and_payload(
    parts: tuple[BackupFile, ...] | list[BackupFile],
    *,
    sealed: bool = False,
    created_at: float | None = None,
    signing_seed: bytes | None = None,
    input_origin: str = "file",
    input_roots: tuple[str, ...] | list[str] = (),
) -> tuple[BackupManifest, bytes]:
    """Build a manifest and concatenated payload bytes from payload parts."""

    if not parts:
        raise ValueError("at least one payload part is required")

    if sealed:
        if signing_seed is not None:
            raise ValueError("sealed manifests must not include seed")
        signing_seed_bytes = None
    else:
        if signing_seed is None:
            raise ValueError("unsealed manifests must include seed")
        if not isinstance(signing_seed, (bytes, bytearray)):
            raise ValueError("seed must be bytes")
        signing_seed_bytes = bytes(signing_seed)
        if len(signing_seed_bytes) != SIGNING_SEED_LEN:
            raise ValueError(f"seed must be {SIGNING_SEED_LEN} bytes")

    created = int(time.time()) if created_at is None else created_at
    files: list[ManifestFile] = []
    payload = bytearray()
    seen_paths: set[str] = set()
    normalized_parts: list[tuple[str, BackupFile]] = []
    for part in parts:
        normalized_parts.append((normalize_manifest_path(part.path, label="payload path"), part))
    normalized_parts.sort(key=lambda item: item[0])
    validate_manifest_file_tree(
        (path for path, _part in normalized_parts),
        label="payload file paths",
    )

    for path, part in normalized_parts:
        if path in seen_paths:
            raise ValueError(f"duplicate payload path: {path}")
        seen_paths.add(path)
        data = part.data
        payload.extend(data)
        files.append(
            ManifestFile(
                path=path,
                size=len(data),
                sha256=hashlib.sha256(data).digest(),
                mtime=part.mtime,
            )
        )
    manifest = BackupManifest(
        format_version=MANIFEST_VERSION,
        created_at=created,
        sealed=sealed,
        signing_seed=signing_seed_bytes,
        input_origin=input_origin,
        input_roots=tuple(input_roots),
        files=tuple(files),
    )
    return manifest, bytes(payload)


def encode_manifest(manifest: BackupManifest) -> bytes:
    """Encode a manifest and enforce manifest CBOR size bounds."""

    encoded = dumps_deterministic(manifest.to_cbor())
    if len(encoded) > MAX_MANIFEST_CBOR_BYTES:
        raise ValueError(
            f"manifest exceeds MAX_MANIFEST_CBOR_BYTES ({MAX_MANIFEST_CBOR_BYTES}): "
            f"{len(encoded)} bytes"
        )
    return encoded


def decode_manifest(data: bytes) -> BackupManifest:
    """Decode and validate a manifest from deterministic CBOR bytes."""

    if len(data) > MAX_MANIFEST_CBOR_BYTES:
        raise ValueError(
            f"manifest exceeds MAX_MANIFEST_CBOR_BYTES ({MAX_MANIFEST_CBOR_BYTES}): "
            f"{len(data)} bytes"
        )
    try:
        decoded = loads_deterministic(data, label="manifest")
    except UnicodeDecodeError as exc:
        raise ValueError("manifest contains invalid UTF-8") from exc
    return BackupManifest.from_cbor(decoded)


def encode_backup_document(payload: bytes, manifest: BackupManifest) -> bytes:
    """Encode a standalone backup's manifest and stored file payload."""

    manifest_bytes = encode_manifest(manifest)
    parts = [
        MAGIC,
        _encode_uvarint(VERSION),
        _encode_uvarint(len(manifest_bytes)),
        manifest_bytes,
        _encode_uvarint(len(payload)),
        payload,
    ]
    return b"".join(parts)


def decode_backup_document(data: bytes) -> tuple[BackupManifest, bytes]:
    """Decode a standalone backup and return `(manifest, stored_payload)`."""

    idx = 0
    if len(data) < len(MAGIC) + 1:
        raise ValueError("document too short")
    if data[: len(MAGIC)] != MAGIC:
        raise ValueError("invalid document magic")
    idx += len(MAGIC)

    version, idx = _decode_uvarint(data, idx)
    if version != VERSION:
        raise ValueError(f"unsupported document version: {version}")

    manifest_len, idx = _decode_uvarint(data, idx)
    if manifest_len > MAX_MANIFEST_CBOR_BYTES:
        raise ValueError(
            f"manifest exceeds MAX_MANIFEST_CBOR_BYTES ({MAX_MANIFEST_CBOR_BYTES}): "
            f"{manifest_len} bytes"
        )
    end_manifest = idx + manifest_len
    if end_manifest > len(data):
        raise ValueError("truncated manifest")
    manifest_bytes = data[idx:end_manifest]
    idx = end_manifest
    manifest = decode_manifest(manifest_bytes)

    payload_len, idx = _decode_uvarint(data, idx)
    end_payload = idx + payload_len
    if end_payload != len(data):
        raise ValueError("payload length mismatch")
    payload = data[idx:end_payload]
    return manifest, payload


def encode_extension_document(document: object) -> bytes:
    """Encode an extension document."""

    if not isinstance(document, ExtensionDocument):
        raise ValueError("encode_extension_document expects an ExtensionDocument")
    return document.encode()


def decode_extension_document(
    data: bytes,
    *,
    max_inline_chunk_bytes: int | None = None,
) -> object:
    """Decode an extension document."""

    if max_inline_chunk_bytes is None:
        return ExtensionDocument.decode(data)
    return ExtensionDocument.decode(data, max_inline_chunk_bytes=max_inline_chunk_bytes)


def detect_document_version(data: bytes) -> int:
    """Read the document version after its magic bytes, without decoding its body."""

    idx = len(MAGIC)
    if len(data) < idx + 1:
        raise ValueError("document too short")
    if data[:idx] != MAGIC:
        raise ValueError("invalid document magic")
    version, _next_idx = _decode_uvarint(data, idx)
    return version


def decode_document(
    data: bytes,
    *,
    max_extension_inline_chunk_bytes: int | None = None,
) -> tuple[int, object]:
    """Decode a root backup or extension and return `(version, decoded_document)`."""

    version = detect_document_version(data)
    if version == VERSION:
        return version, decode_backup_document(data)
    if version == 2:
        return version, decode_extension_document(
            data,
            max_inline_chunk_bytes=max_extension_inline_chunk_bytes,
        )
    raise ValueError(f"unsupported document version: {version}")


def extract_payloads(
    manifest: BackupManifest,
    payload: bytes,
) -> list[tuple[ManifestFile, bytes]]:
    """Split payload bytes into manifest entries and verify entry hashes."""

    payload = decode_payload_from_manifest(manifest, payload)
    expected_payload_len = sum(entry.size for entry in manifest.files)
    if len(payload) != expected_payload_len:
        raise ValueError("payload length does not match manifest sizes")

    outputs: list[tuple[ManifestFile, bytes]] = []
    offset = 0
    for entry in manifest.files:
        end = offset + entry.size
        if end > len(payload):
            raise ValueError("manifest file exceeds payload size")
        data = payload[offset:end]
        if hashlib.sha256(data).digest() != entry.sha256:
            raise ValueError(f"sha256 mismatch for {entry.path}")
        outputs.append((entry, data))
        offset = end
    return outputs


def _normalize_path(path: str | None) -> str:
    """Normalize a single-file input path for manifest use."""

    if not path or path == "-":
        return "data.txt"
    return normalize_path(Path(path).name, label="input path")


def _read_mtime(path: str | None) -> int | None:
    """Read integer mtime for a local path, ignoring stat failures."""

    if not path or path == "-":
        return None
    try:
        return int(os.stat(path).st_mtime)
    except OSError:
        return None
