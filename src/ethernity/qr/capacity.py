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

from ..encoding.framing import DOC_ID_LEN, VERSION, Frame, encode_frame
from ..encoding.qr_payloads import encode_qr_payload
from .codec import QrConfig, make_qr


def choose_frame_chunk_size(
    payload_len: int,
    *,
    preferred_chunk_size: int,
    doc_id: bytes,
    frame_type: int,
    qr_config: QrConfig,
) -> int:
    """Choose a chunk_size for chunk_payload() that fits the current QR settings.

    The chosen size is <= preferred_chunk_size and is validated by probing QR capacity using the
    Version 1 QR payload representation (frame bytes -> base64 text without padding).
    """
    if payload_len <= 0:
        raise ValueError("payload_len must be positive")
    if preferred_chunk_size <= 0:
        raise ValueError("preferred_chunk_size must be positive")
    if len(doc_id) != DOC_ID_LEN:
        raise ValueError(f"doc_id must be {DOC_ID_LEN} bytes")

    chunk_size = min(preferred_chunk_size, payload_len)
    while True:
        total = (payload_len + chunk_size - 1) // chunk_size
        max_data_len = _max_frame_data_len(payload_len, total=total)
        if _fits_qr_frame(
            max_data_len,
            total=total,
            doc_id=doc_id,
            frame_type=frame_type,
            qr_config=qr_config,
        ):
            return chunk_size
        chunk_size = _max_fitting_frame_data_len(
            upper=max_data_len,
            total=total,
            doc_id=doc_id,
            frame_type=frame_type,
            qr_config=qr_config,
        )
        if chunk_size <= 0:
            raise ValueError("unable to select a valid chunk size for current QR settings")


def _max_frame_data_len(payload_len: int, *, total: int) -> int:
    if total <= 0:
        raise ValueError("total must be positive")
    base = payload_len // total
    return base + (1 if payload_len % total else 0)


def _fits_qr_frame(
    data_len: int,
    *,
    total: int,
    doc_id: bytes,
    frame_type: int,
    qr_config: QrConfig,
) -> bool:
    if data_len <= 0:
        return False
    if total <= 0:
        return False
    if len(doc_id) != DOC_ID_LEN:
        return False

    # Use a pattern that forces the QR payload into byte mode (base64 strings for random bytes
    # almost always include lowercase anyway, but this makes probing conservative/deterministic).
    frame = Frame(
        version=VERSION,
        frame_type=frame_type,
        doc_id=doc_id,
        index=total - 1,
        total=total,
        data=b"\xff" * data_len,
    )
    qr_payload = encode_qr_payload(encode_frame(frame))
    return _fits_qr_payload(qr_payload, qr_config)


def _max_fitting_frame_data_len(
    *,
    upper: int,
    total: int,
    doc_id: bytes,
    frame_type: int,
    qr_config: QrConfig,
) -> int:
    if upper <= 0:
        raise ValueError("upper must be positive")

    if not _fits_qr_frame(
        1,
        total=total,
        doc_id=doc_id,
        frame_type=frame_type,
        qr_config=qr_config,
    ):
        raise ValueError(
            "QR settings cannot encode even the smallest frame payload; "
            "increase QR version or lower error correction"
        )

    lower = 1
    upper_bound = upper
    while lower < upper_bound:
        mid = (lower + upper_bound + 1) // 2
        if _fits_qr_frame(
            mid,
            total=total,
            doc_id=doc_id,
            frame_type=frame_type,
            qr_config=qr_config,
        ):
            lower = mid
        else:
            upper_bound = mid - 1
    return lower


def _fits_qr_payload(payload: bytes | str, config: QrConfig) -> bool:
    try:
        make_qr(
            payload,
            error=config.error,
            version=config.version,
            mask=config.mask,
            micro=config.micro,
            boost_error=config.boost_error,
        )
    except (ValueError, TypeError):
        return False
    return True
