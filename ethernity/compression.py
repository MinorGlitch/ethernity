#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass

from .config import CompressionConfig

MAGIC = b"AZ"
VERSION = 1

ALGO_NONE = 0
ALGO_ZSTD = 1


@dataclass(frozen=True)
class CompressionInfo:
    algorithm: str
    enabled: bool
    compressed: bool
    raw_len: int
    wrapped_len: int


def wrap_payload(payload: bytes, config: CompressionConfig) -> tuple[bytes, CompressionInfo]:
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes")
    raw = bytes(payload)
    algorithm = _normalize_algorithm(config)
    algo_id = _algo_id(algorithm)
    if algo_id == ALGO_NONE:
        data = raw
        compressed = False
    elif algo_id == ALGO_ZSTD:
        data = _compress_zstd(raw, level=config.level)
        compressed = True
    else:
        raise ValueError(f"unsupported compression algorithm: {algorithm}")

    parts = [
        MAGIC,
        _encode_uvarint(VERSION),
        _encode_uvarint(algo_id),
        _encode_uvarint(len(raw)),
        _encode_uvarint(len(data)),
        data,
    ]
    wrapped = b"".join(parts)
    info = CompressionInfo(
        algorithm=algorithm,
        enabled=bool(config.enabled),
        compressed=compressed,
        raw_len=len(raw),
        wrapped_len=len(wrapped),
    )
    return wrapped, info


def unwrap_payload(data: bytes) -> tuple[bytes, CompressionInfo]:
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("payload must be bytes")
    payload = bytes(data)
    if len(payload) < len(MAGIC) + 1:
        raise ValueError("compressed payload too short")
    if payload[: len(MAGIC)] != MAGIC:
        raise ValueError("invalid compression magic")
    idx = len(MAGIC)

    version, idx = _decode_uvarint(payload, idx)
    if version != VERSION:
        raise ValueError(f"unsupported compression version: {version}")
    algo_id, idx = _decode_uvarint(payload, idx)
    raw_len, idx = _decode_uvarint(payload, idx)
    data_len, idx = _decode_uvarint(payload, idx)
    end = idx + data_len
    if end != len(payload):
        raise ValueError("compressed payload length mismatch")
    chunk = payload[idx:end]

    if algo_id == ALGO_NONE:
        if data_len != raw_len:
            raise ValueError("raw payload length mismatch")
        algorithm = "none"
        output = chunk
        compressed = False
    elif algo_id == ALGO_ZSTD:
        output = _decompress_zstd(chunk, max_size=raw_len)
        if len(output) != raw_len:
            raise ValueError("decompressed length mismatch")
        algorithm = "zstd"
        compressed = True
    else:
        raise ValueError(f"unsupported compression algorithm id: {algo_id}")

    info = CompressionInfo(
        algorithm=algorithm,
        enabled=algo_id != ALGO_NONE,
        compressed=compressed,
        raw_len=raw_len,
        wrapped_len=len(payload),
    )
    return output, info


def _normalize_algorithm(config: CompressionConfig) -> str:
    if not config.enabled:
        return "none"
    return str(config.algorithm or "none").strip().lower()


def _algo_id(algorithm: str) -> int:
    if algorithm in ("none", "off", "false", "0"):
        return ALGO_NONE
    if algorithm == "zstd":
        return ALGO_ZSTD
    raise ValueError(f"unsupported compression algorithm: {algorithm}")


def _compress_zstd(data: bytes, *, level: int) -> bytes:
    try:
        import zstandard as zstd
    except ImportError as exc:
        raise RuntimeError("zstandard is required for zstd compression") from exc
    compressor = zstd.ZstdCompressor(level=level)
    return compressor.compress(data)


def _decompress_zstd(data: bytes, *, max_size: int) -> bytes:
    try:
        import zstandard as zstd
    except ImportError as exc:
        raise RuntimeError("zstandard is required for zstd decompression") from exc
    decompressor = zstd.ZstdDecompressor()
    return decompressor.decompress(data, max_output_size=max_size)


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
