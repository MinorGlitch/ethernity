#!/usr/bin/env python3
from __future__ import annotations

import base64
import binascii

SUPPORTED_QR_PAYLOAD_ENCODINGS = {"binary", "base64"}


def normalize_qr_payload_encoding(value: str | None) -> str:
    if value is None:
        return "binary"
    normalized = value.strip().lower()
    if normalized in ("binary", "raw"):
        return "binary"
    if normalized in ("base64", "b64"):
        return "base64"
    raise ValueError(f"unsupported QR payload encoding: {value}")


def encode_qr_payload(data: bytes, encoding: str) -> bytes | str:
    encoding = normalize_qr_payload_encoding(encoding)
    if encoding == "binary":
        return data
    encoded = base64.b64encode(data).decode("ascii")
    return encoded.rstrip("=")


def decode_qr_payload(payload: bytes | str, encoding: str) -> bytes:
    encoding = normalize_qr_payload_encoding(encoding)
    if encoding == "binary":
        if isinstance(payload, bytes):
            return payload
        return payload.encode("utf-8")
    if isinstance(payload, bytes):
        try:
            text = payload.decode("ascii")
        except UnicodeDecodeError:
            return payload
    else:
        text = payload
    cleaned = "".join(text.split())
    try:
        return base64.b64decode(_pad_base64(cleaned), validate=True)
    except (binascii.Error, ValueError) as exc:
        if isinstance(payload, bytes):
            return payload
        raise ValueError("invalid base64 QR payload") from exc


def _pad_base64(text: str) -> str:
    padding = (-len(text)) % 4
    return text + ("=" * padding)
