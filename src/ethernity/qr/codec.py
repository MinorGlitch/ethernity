#!/usr/bin/env python3
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import segno
from PIL import Image, ImageColor, ImageDraw


@dataclass(frozen=True)
class QrConfig:
    error: str = "Q"
    scale: int = 4
    border: int = 4
    kind: str = "png"
    dark: str | tuple[int, int, int] | tuple[int, int, int, int] | None = None
    light: str | tuple[int, int, int] | tuple[int, int, int, int] | None = None
    module_shape: str = "square"
    version: int | None = None
    mask: int | None = None
    micro: bool | None = None
    boost_error: bool = True


_ROUNDED_RATIO = 0.2


def _color_to_rgba(
    value: object,
    fallback: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    normalized = _normalize_color_value(value)
    if normalized is None:
        return fallback
    if isinstance(normalized, str):
        if normalized.lower() in ("none", "transparent"):
            return fallback
        rgb = ImageColor.getcolor(normalized, "RGBA")
        if isinstance(rgb, int):
            return (rgb, rgb, rgb, 255)
        return (int(rgb[0]), int(rgb[1]), int(rgb[2]), int(rgb[3]))
    if isinstance(normalized, (tuple, list)):
        if len(normalized) == 3:
            return (int(normalized[0]), int(normalized[1]), int(normalized[2]), 255)
        if len(normalized) == 4:
            return (
                int(normalized[0]),
                int(normalized[1]),
                int(normalized[2]),
                int(normalized[3]),
            )
    return fallback


def _draw_module(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    *,
    scale: int,
    radius: float,
    color: tuple[int, int, int, int],
) -> None:
    if radius > 0:
        draw.rounded_rectangle(
            (x, y, x + scale, y + scale),
            radius=radius,
            fill=color,
        )
        return
    draw.rectangle((x, y, x + scale, y + scale), fill=color)


def make_qr(
    data: bytes | str,
    *,
    error: str = "Q",
    version: int | None = None,
    mask: int | None = None,
    micro: bool | None = None,
    boost_error: bool = True,
) -> Any:
    return segno.make(
        data,
        error=error,
        version=version,
        mask=mask,
        micro=micro,
        boost_error=boost_error,
    )


def qr_bytes(
    data: bytes | str,
    *,
    error: str = "Q",
    scale: int = 4,
    border: int = 4,
    kind: str = "png",
    dark: str | tuple[int, int, int] | tuple[int, int, int, int] | None = None,
    light: str | tuple[int, int, int] | tuple[int, int, int, int] | None = None,
    module_shape: str = "square",
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
    shape = module_shape.strip().lower()
    allowed_shapes = {"square", "rounded"}
    if shape not in allowed_shapes:
        raise ValueError(f"unsupported module_shape: {module_shape}")
    if shape != "square":
        if kind.lower() != "png":
            raise ValueError("custom module shapes are only supported for PNG output")
        return _render_custom_qr(
            qr,
            scale=scale,
            border=border,
            dark=dark,
            light=light,
            roundness=_ROUNDED_RATIO,
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


def save_qr(
    path: str,
    data: bytes | str,
    *,
    error: str = "Q",
    scale: int = 4,
    border: int = 4,
    kind: str | None = None,
    dark: str | tuple[int, int, int] | tuple[int, int, int, int] | None = None,
    light: str | tuple[int, int, int] | tuple[int, int, int, int] | None = None,
    module_shape: str = "square",
    version: int | None = None,
    mask: int | None = None,
    micro: bool | None = None,
    boost_error: bool = True,
) -> None:
    if kind is None:
        suffix = Path(path).suffix.lower().lstrip(".")
        kind = suffix or "png"
    png = qr_bytes(
        data,
        error=error,
        scale=scale,
        border=border,
        kind=kind,
        dark=dark,
        light=light,
        module_shape=module_shape,
        version=version,
        mask=mask,
        micro=micro,
        boost_error=boost_error,
    )
    with open(path, "wb") as handle:
        handle.write(png)


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


def _render_custom_qr(
    qr: Any,
    *,
    scale: int,
    border: int,
    dark: object,
    light: object,
    roundness: float,
) -> bytes:
    light_rgba = _color_to_rgba(light, (255, 255, 255, 255))
    dark_rgba = _color_to_rgba(dark, (0, 0, 0, 255))

    width, height = qr.symbol_size(scale=scale, border=border)
    image = Image.new("RGBA", (width, height), light_rgba)
    draw = ImageDraw.Draw(image)

    radius = max(0.0, min(roundness, 0.5)) * scale

    for row_idx, row in enumerate(qr.matrix_iter(scale=1, border=border)):
        for col_idx, is_dark in enumerate(row):
            x = col_idx * scale
            y = row_idx * scale
            if not is_dark:
                continue
            _draw_module(draw, x, y, scale=scale, radius=radius, color=dark_rgba)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
