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

"""Scan QR payloads from PDFs and images using zxingcpp and Pillow."""

from __future__ import annotations

import functools
import importlib
import io
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from ethernity.extensions.layout import is_staging_dir_name


def _optional_import(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        return None


pil_image = _optional_import("PIL.Image")
pypdf = _optional_import("pypdf")
zxingcpp = _optional_import("zxingcpp")


class QrScanError(RuntimeError):
    """Raised when scan inputs cannot be read or contain no usable QR codes."""

    pass


@dataclass(frozen=True)
class QrDecoder:
    """Decoder adapter used to scan QR payloads from paths and image bytes."""

    name: str
    decode_image_path: Callable[[Path], list[bytes]]
    decode_image_bytes: Callable[[bytes], list[bytes]]


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
_EXTENSIONS_DIR_NAME = "extensions"
_PDF_MAGIC = b"%PDF-"
_IMAGE_MAGICS = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"BM",
    b"II*\x00",
    b"MM\x00*",
    b"RIFF",
)


def _module(name: str, default: Any) -> Any:
    """Return an imported module override from `sys.modules` when present."""

    return sys.modules.get(name, default)


def _decode_image(image, *, zxing_module) -> list[bytes]:
    """Decode QR codes in an opened image object."""

    results = zxing_module.read_barcodes(image, formats=zxing_module.BarcodeFormat.QRCode)
    payloads: list[bytes] = []
    for result in results:
        data = getattr(result, "bytes", None) or getattr(result, "raw_bytes", None)
        if data:
            payloads.append(bytes(data))
        elif getattr(result, "text", None):
            payloads.append(result.text.encode("utf-8"))
    return payloads


def _decode_image_path(path: Path, *, zxing_module, image_module) -> list[bytes]:
    """Open and decode a QR image from a filesystem path."""

    with image_module.open(path) as image:
        return _decode_image(image, zxing_module=zxing_module)


def _decode_image_bytes(data: bytes, *, zxing_module, image_module) -> list[bytes]:
    """Open and decode a QR image from in-memory image bytes."""

    with image_module.open(io.BytesIO(data)) as image:
        return _decode_image(image, zxing_module=zxing_module)


def scan_qr_payloads(paths: Sequence[str | Path]) -> list[bytes]:
    """Scan one or more paths and return decoded QR payload bytes."""

    decoder = _load_decoder()
    payloads: list[bytes] = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            raise QrScanError(f"scan path not found: {path}")
        if path.is_dir():
            scan_files = _iter_scan_files(path)
            if not scan_files:
                raise QrScanError(f"no scan files found in directory: {path}")
            for scan_file in scan_files:
                payloads.extend(_scan_one_path(scan_file, decoder))
        else:
            payloads.extend(_scan_one_path(path, decoder))

    if not payloads:
        raise QrScanError("no QR codes found in scan inputs")
    return payloads


def _scan_one_path(path: Path, decoder: QrDecoder) -> list[bytes]:
    if _looks_like_pdf(path):
        return _scan_pdf(path, decoder)
    if _looks_like_image(path):
        return _scan_image(path, decoder)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _scan_pdf(path, decoder)
    if suffix in _IMAGE_SUFFIXES:
        return _scan_image(path, decoder)
    raise QrScanError(f"unsupported scan file content: {path}")


def _load_decoder() -> QrDecoder:
    """Build the default zxingcpp/Pillow-backed QR decoder adapter."""

    zxing_module = _module("zxingcpp", zxingcpp)
    image_module = _module("PIL.Image", pil_image)
    if zxing_module is None:
        raise QrScanError("zxingcpp is required to scan QR payloads")
    if image_module is None:
        raise QrScanError("Pillow is required to scan QR payloads")

    return QrDecoder(
        name="zxingcpp",
        decode_image_path=functools.partial(
            _decode_image_path,
            zxing_module=zxing_module,
            image_module=image_module,
        ),
        decode_image_bytes=functools.partial(
            _decode_image_bytes,
            zxing_module=zxing_module,
            image_module=image_module,
        ),
    )


def _scan_image(path: Path, decoder: QrDecoder) -> list[bytes]:
    """Decode QR payloads from an image file."""

    try:
        return decoder.decode_image_path(path)
    except OSError as exc:
        raise QrScanError(f"failed to read image: {path}") from exc


def _scan_pdf(path: Path, decoder: QrDecoder) -> list[bytes]:
    """Decode QR payloads from all embedded page images in a PDF."""

    pypdf_module = _module("pypdf", pypdf)
    if pypdf_module is None:
        raise QrScanError("pypdf is required to scan PDF inputs")
    try:
        reader = pypdf_module.PdfReader(str(path))
    except (OSError, pypdf_module.errors.PdfReadError, ValueError) as exc:
        raise QrScanError(f"failed to read PDF: {path}") from exc
    payloads: list[bytes] = []
    for page in reader.pages:
        if not hasattr(page, "images"):
            raise QrScanError("pypdf is missing page.images support (upgrade pypdf)")
        for image in page.images:
            try:
                payloads.extend(decoder.decode_image_bytes(image.data))
            except OSError:
                continue
    return payloads


def _expand_paths(paths: Sequence[str | Path]) -> Iterable[Path]:
    """Expand path inputs, recursing into directories for supported scan files."""

    for raw in paths:
        path = Path(raw)
        if not path.exists():
            raise QrScanError(f"scan path not found: {path}")
        if path.is_dir():
            scan_files = _iter_scan_files(path)
            if not scan_files:
                raise QrScanError(f"no scan files found in directory: {path}")
            yield from scan_files
        else:
            yield path


def _iter_scan_files(directory: Path) -> list[Path]:
    """Collect supported scan files from a directory tree."""

    if _is_under_unpublished_extension_workspace(directory):
        return []

    files: list[Path] = []
    for root, dirnames, filenames in os.walk(directory):
        root_path = Path(root)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not _is_under_unpublished_extension_workspace(root_path / name)
        )
        for filename in filenames:
            path = root_path / filename
            suffix = path.suffix.lower()
            if _looks_like_scan_file(path) or suffix == ".pdf" or suffix in _IMAGE_SUFFIXES:
                files.append(path)
    files.sort()
    return files


def _is_under_unpublished_extension_workspace(path: Path) -> bool:
    parts = path.parts
    for index, part in enumerate(parts[:-1]):
        if part == _EXTENSIONS_DIR_NAME and is_staging_dir_name(parts[index + 1]):
            return True
    return False


def _looks_like_scan_file(path: Path) -> bool:
    return _looks_like_pdf(path) or _looks_like_image(path)


def _read_file_prefix(path: Path, size: int = 16) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def _looks_like_pdf(path: Path) -> bool:
    return _read_file_prefix(path).startswith(_PDF_MAGIC)


def _looks_like_image(path: Path) -> bool:
    prefix = _read_file_prefix(path)
    if any(prefix.startswith(magic) for magic in _IMAGE_MAGICS):
        if prefix.startswith(b"RIFF") and prefix[8:12] != b"WEBP":
            return False
        return True
    return False
