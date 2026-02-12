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

from __future__ import annotations

import base64
import binascii


def encode_qr_payload(data: bytes) -> str:
    """Encode frame bytes as unpadded base64 text."""
    encoded = base64.b64encode(data).decode("ascii")
    return encoded.rstrip("=")


def decode_qr_payload(payload: bytes | str) -> bytes:
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
