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

"""QR payload transport encoding/decoding helpers."""

from __future__ import annotations

import base64
import binascii
from typing import Final, Literal

QrPayloadCodec = Literal["raw", "base64"]
QR_PAYLOAD_CODEC_RAW: Final[QrPayloadCodec] = "raw"
QR_PAYLOAD_CODEC_BASE64: Final[QrPayloadCodec] = "base64"


def encode_qr_payload(
    data: bytes,
    *,
    codec: QrPayloadCodec = QR_PAYLOAD_CODEC_BASE64,
) -> bytes | str:
    """Encode frame bytes for QR transport."""
    if codec == QR_PAYLOAD_CODEC_RAW:
        return data
    if codec != QR_PAYLOAD_CODEC_BASE64:
        raise ValueError(f"unsupported QR payload codec: {codec}")
    encoded = base64.b64encode(data).decode("ascii")
    return encoded.rstrip("=")


def decode_qr_payload(
    payload: bytes | str,
    *,
    codec: QrPayloadCodec = QR_PAYLOAD_CODEC_BASE64,
) -> bytes:
    """Decode frame bytes from QR transport payload."""
    if codec == QR_PAYLOAD_CODEC_RAW:
        if isinstance(payload, bytes):
            return payload
        raise ValueError("invalid raw QR payload")
    if codec != QR_PAYLOAD_CODEC_BASE64:
        raise ValueError(f"unsupported QR payload codec: {codec}")
    return _decode_base64_qr_payload(payload)


def _decode_base64_qr_payload(payload: bytes | str) -> bytes:
    """Decode unpadded base64 QR payload text."""
    if isinstance(payload, bytes):
        try:
            text = payload.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("invalid base64 QR payload") from exc
    else:
        text = payload
    cleaned = "".join(text.split())
    if "=" in cleaned:
        raise ValueError("invalid base64 QR payload")
    try:
        return base64.b64decode(_pad_unpadded_base64(cleaned), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 QR payload") from exc


def _pad_unpadded_base64(text: str) -> str:
    """Add required padding to unpadded base64 text."""
    padding = (-len(text)) % 4
    return text + ("=" * padding)


__all__ = [
    "QR_PAYLOAD_CODEC_BASE64",
    "QR_PAYLOAD_CODEC_RAW",
    "QrPayloadCodec",
    "decode_qr_payload",
    "encode_qr_payload",
]
