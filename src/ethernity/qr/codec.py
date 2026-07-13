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

import io
from dataclasses import dataclass
from typing import Any

import segno


@dataclass(frozen=True)
class QrConfig:
    error: str = "M"
    scale: int = 4
    border: int = 4
    kind: str = "png"
    dark: str | tuple[int, int, int] | tuple[int, int, int, int] | None = None
    light: str | tuple[int, int, int] | tuple[int, int, int, int] | None = None
    version: int | None = None
    mask: int | None = None
    micro: bool | None = None
    boost_error: bool = True


def make_qr(
    data: bytes | str,
    *,
    error: str = "M",
    version: int | None = None,
    mask: int | None = None,
    micro: bool | None = None,
    boost_error: bool = True,
) -> Any:
    try:
        return segno.make(
            data,
            error=error,
            version=version,
            mask=mask,
            micro=micro,
            boost_error=boost_error,
        )
    except segno.DataOverflowError as exc:
        payload_size = len(data if isinstance(data, bytes) else data.encode("utf-8"))
        version_label = "auto" if version is None else str(version)
        micro_label = "auto" if micro is None else str(micro).lower()
        raise ValueError(
            "QR payload does not fit the configured symbol capacity: "
            f"payload_bytes={payload_size}, error={error}, version={version_label}, "
            f"micro={micro_label}; reduce the payload/chunk size or choose a lower QR error "
            "correction level"
        ) from exc


def qr_bytes(
    data: bytes | str,
    *,
    error: str = "M",
    scale: int = 4,
    border: int = 4,
    kind: str = "png",
    dark: str | tuple[int, int, int] | tuple[int, int, int, int] | None = None,
    light: str | tuple[int, int, int] | tuple[int, int, int, int] | None = None,
    version: int | None = None,
    mask: int | None = None,
    micro: bool | None = None,
    boost_error: bool = True,
) -> bytes:
    qr = make_qr(
        data,
        error=error,
        version=version,
        mask=mask,
        micro=micro,
        boost_error=boost_error,
    )

    buf = io.BytesIO()
    qr.save(
        buf,
        kind=kind,
        scale=scale,
        border=border,
        **_segno_color_kwargs(dark=dark, light=light),
    )
    return buf.getvalue()


def _segno_color_kwargs(**values: object) -> dict[str, object]:
    style: dict[str, object] = {}
    for key, value in values.items():
        normalized = _normalize_color_value(value)
        if normalized is None:
            continue
        style[key] = normalized
    return style


def _normalize_color_value(value: object) -> object | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip()
    return value
