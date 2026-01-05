#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import time

import cbor2

MAGIC = b"AY"
VERSION = 1
MANIFEST_VERSION = 4


@dataclass(frozen=True)
class ManifestFile:
    path: str
    size: int
    sha256: bytes
    mtime: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "mtime": self.mtime,
        }


@dataclass(frozen=True)
class Manifest:
    format_version: int
    created_at: float
    sealed: bool
    files: tuple[ManifestFile, ...]

    def to_cbor(self) -> list[object]:
        prefixes = _build_prefix_table([file.path for file in self.files])
        prefix_index = {prefix: idx for idx, prefix in enumerate(prefixes)}
        prefixes_sorted = sorted(prefixes[1:], key=len, reverse=True)
        files = []
        for file in self.files:
            prefix = _select_prefix(file.path, prefixes_sorted)
            idx = prefix_index[prefix]
            suffix = _strip_prefix(file.path, prefix)
            files.append([idx, suffix, file.size, file.sha256, file.mtime])
        return [
            self.format_version,
            self.created_at,
            self.sealed,
            prefixes,
            files,
        ]

    def to_dict(self) -> dict[str, object]:
        return {
            "format_version": self.format_version,
            "created_at": self.created_at,
            "sealed": self.sealed,
            "files": [file.to_dict() for file in self.files],
        }

    @classmethod
    def from_cbor(cls, data: object) -> Manifest:
        if not isinstance(data, (list, tuple)) or len(data) < 5:
            raise ValueError("manifest must be a list")
        format_version = data[0]
        created_at = data[1]
        sealed = data[2]
        prefixes = data[3]
        files_raw = data[4]
        if not isinstance(format_version, int):
            raise ValueError("manifest format_version must be an int")
        if format_version != MANIFEST_VERSION:
            raise ValueError(f"unsupported manifest version: {format_version}")
        if not isinstance(created_at, (int, float)):
            raise ValueError("manifest created_at must be a number")
        if not isinstance(sealed, bool):
            raise ValueError("manifest sealed must be a boolean")
        if not isinstance(prefixes, list) or not prefixes:
            raise ValueError("manifest prefixes are required")
        if prefixes[0] != "":
            raise ValueError("manifest prefixes must start with empty string")
        for prefix in prefixes:
            if not isinstance(prefix, str):
                raise ValueError("manifest prefix must be a string")
        if not isinstance(files_raw, list) or not files_raw:
            raise ValueError("manifest files are required")
        files: list[ManifestFile] = []
        for entry in files_raw:
            if not isinstance(entry, (list, tuple)) or len(entry) < 5:
                raise ValueError("manifest file entry must be a list")
            prefix_idx, suffix, size, sha256, mtime = entry[:5]
            if not isinstance(prefix_idx, int):
                raise ValueError("manifest file prefix index must be an int")
            if prefix_idx < 0 or prefix_idx >= len(prefixes):
                raise ValueError("manifest file prefix index out of range")
            if not isinstance(suffix, str) or not suffix:
                raise ValueError("manifest file suffix must be a non-empty string")
            prefix = prefixes[prefix_idx]
            if prefix:
                path = f"{prefix}/{suffix}"
            else:
                path = suffix
            if not isinstance(path, str):
                raise ValueError("manifest file path must be a string")
            if not isinstance(size, int) or size < 0:
                raise ValueError("manifest file size must be a non-negative int")
            sha_bytes = _coerce_sha256(sha256)
            if sha_bytes is None:
                raise ValueError("manifest file sha256 must be 32 raw bytes or 64 hex chars")
            if mtime is not None and not isinstance(mtime, int):
                raise ValueError("manifest file mtime must be an int")
            files.append(
                ManifestFile(
                    path=path,
                    size=size,
                    sha256=sha_bytes,
                    mtime=int(mtime) if mtime is not None else None,
                )
            )
        return cls(
            format_version=format_version,
            created_at=float(created_at),
            sealed=sealed,
            files=tuple(files),
        )


@dataclass(frozen=True)
class PayloadPart:
    path: str
    data: bytes
    mtime: int | None


def build_single_file_manifest(
    input_path: str | None,
    payload: bytes,
    *,
    sealed: bool = False,
    created_at: float | None = None,
) -> Manifest:
    path = _normalize_path(input_path)
    mtime = _read_mtime(input_path)
    part = PayloadPart(path=path, data=payload, mtime=mtime)
    manifest, _payload = build_manifest_and_payload((part,), sealed=sealed, created_at=created_at)
    return manifest


def build_manifest_and_payload(
    parts: tuple[PayloadPart, ...] | list[PayloadPart],
    *,
    sealed: bool = False,
    created_at: float | None = None,
) -> tuple[Manifest, bytes]:
    if not parts:
        raise ValueError("at least one payload part is required")
    created = time.time() if created_at is None else created_at
    files: list[ManifestFile] = []
    payload = bytearray()
    offset = 0
    seen_paths: set[str] = set()
    for part in parts:
        if part.path in seen_paths:
            raise ValueError(f"duplicate payload path: {part.path}")
        seen_paths.add(part.path)
        data = part.data
        payload.extend(data)
        files.append(
            ManifestFile(
                path=part.path,
                size=len(data),
                sha256=hashlib.sha256(data).digest(),
                mtime=part.mtime,
            )
        )
        offset += len(data)
    manifest = Manifest(
        format_version=MANIFEST_VERSION,
        created_at=created,
        sealed=sealed,
        files=tuple(files),
    )
    return manifest, bytes(payload)


def encode_manifest(manifest: Manifest) -> bytes:
    return cbor2.dumps(manifest.to_cbor())


def decode_manifest(data: bytes) -> Manifest:
    decoded = cbor2.loads(data)
    return Manifest.from_cbor(decoded)


def encode_envelope(payload: bytes, manifest: Manifest) -> bytes:
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


def decode_envelope(data: bytes) -> tuple[Manifest, bytes]:
    idx = 0
    if len(data) < len(MAGIC) + 1:
        raise ValueError("envelope too short")
    if data[: len(MAGIC)] != MAGIC:
        raise ValueError("invalid envelope magic")
    idx += len(MAGIC)

    version, idx = _decode_uvarint(data, idx)
    if version != VERSION:
        raise ValueError(f"unsupported envelope version: {version}")

    manifest_len, idx = _decode_uvarint(data, idx)
    if manifest_len < 0:
        raise ValueError("invalid manifest length")
    end_manifest = idx + manifest_len
    if end_manifest > len(data):
        raise ValueError("truncated manifest")
    manifest_bytes = data[idx:end_manifest]
    idx = end_manifest
    manifest = decode_manifest(manifest_bytes)

    payload_len, idx = _decode_uvarint(data, idx)
    if payload_len < 0:
        raise ValueError("invalid payload length")
    end_payload = idx + payload_len
    if end_payload != len(data):
        raise ValueError("payload length mismatch")
    payload = data[idx:end_payload]
    return manifest, payload


def extract_payloads(manifest: Manifest, payload: bytes) -> list[tuple[ManifestFile, bytes]]:
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
    if offset != len(payload):
        raise ValueError("payload length does not match manifest sizes")
    return outputs


def _coerce_sha256(value: object) -> bytes | None:
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if len(raw) == 32:
            return raw
        return None
    if isinstance(value, str) and len(value) == 64:
        try:
            return bytes.fromhex(value)
        except ValueError:
            return None
    return None


def _build_prefix_table(paths: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for path in paths:
        parts = path.split("/")
        prefix = ""
        for idx in range(len(parts) - 1):
            prefix = parts[idx] if idx == 0 else f"{prefix}/{parts[idx]}"
            counts[prefix] = counts.get(prefix, 0) + 1
    prefixes = [""] + sorted((p for p, count in counts.items() if count > 1), key=lambda p: (len(p), p))
    return prefixes


def _select_prefix(path: str, prefixes: list[str]) -> str:
    for prefix in prefixes:
        if path.startswith(f"{prefix}/"):
            return prefix
    return ""


def _strip_prefix(path: str, prefix: str) -> str:
    if not prefix:
        return path
    return path[len(prefix) + 1 :]


def _normalize_path(path: str | None) -> str:
    if not path or path == "-":
        return "data.txt"
    return Path(path).name


def _read_mtime(path: str | None) -> int | None:
    if not path or path == "-":
        return None
    try:
        return int(os.stat(path).st_mtime)
    except OSError:
        return None


def _encode_uvarint(value: int) -> bytes:
    if value < 0:
        raise ValueError("value must be non-negative")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def _decode_uvarint(data: bytes, start: int) -> tuple[int, int]:
    value = 0
    shift = 0
    idx = start
    while True:
        if idx >= len(data):
            raise ValueError("truncated varint")
        byte = data[idx]
        idx += 1
        value |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return value, idx
        shift += 7
        if shift > 63:
            raise ValueError("varint too large")
