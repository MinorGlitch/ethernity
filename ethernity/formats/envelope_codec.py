#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time

import cbor2

from ..encoding.varint import decode_uvarint as _decode_uvarint
from ..encoding.varint import encode_uvarint as _encode_uvarint
from .envelope_types import EnvelopeManifest, ManifestFile, PayloadPart, MANIFEST_VERSION

MAGIC = b"AY"
VERSION = 1


def build_single_file_manifest(
    input_path: str | None,
    payload: bytes,
    *,
    sealed: bool = False,
    created_at: float | None = None,
) -> EnvelopeManifest:
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
) -> tuple[EnvelopeManifest, bytes]:
    if not parts:
        raise ValueError("at least one payload part is required")
    created = time.time() if created_at is None else created_at
    files: list[ManifestFile] = []
    payload = bytearray()
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
    manifest = EnvelopeManifest(
        format_version=MANIFEST_VERSION,
        created_at=created,
        sealed=sealed,
        files=tuple(files),
    )
    return manifest, bytes(payload)


def encode_manifest(manifest: EnvelopeManifest) -> bytes:
    return cbor2.dumps(manifest.to_cbor())


def decode_manifest(data: bytes) -> EnvelopeManifest:
    decoded = cbor2.loads(data)
    return EnvelopeManifest.from_cbor(decoded)


def encode_envelope(payload: bytes, manifest: EnvelopeManifest) -> bytes:
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


def decode_envelope(data: bytes) -> tuple[EnvelopeManifest, bytes]:
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


def extract_payloads(
    manifest: EnvelopeManifest,
    payload: bytes,
) -> list[tuple[ManifestFile, bytes]]:
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
