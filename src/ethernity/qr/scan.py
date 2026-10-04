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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from ethernity.security.resource_worker import (
    DisposableWorkerError,
    WorkerLimits,
    run_disposable_worker,
)


def _optional_import(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except (ImportError, OSError):
        return None


pil_image = _optional_import("PIL.Image")
pypdf = _optional_import("pypdf")
zxingcpp = _optional_import("zxingcpp")


class QrScanError(RuntimeError):
    """Raised when scan inputs cannot be read or contain no usable QR codes."""

    pass


class NoQrPayloadsError(QrScanError):
    """Raised when readable scan inputs contain no QR payloads."""

    pass


@dataclass(frozen=True)
class QrDecoder:
    """Decoder adapter used to scan QR payloads from paths and image bytes."""

    name: str
    decode_image_path: Callable[[Path], list[bytes]]
    decode_image_bytes: Callable[[bytes], list[bytes]]


@dataclass(frozen=True)
class ScannedQrPayload:
    """Decoded QR payload bytes with the file they came from."""

    data: bytes
    source_path: Path
    source_is_explicit: bool = False


@dataclass(frozen=True)
class _ScanInput:
    """Internal scan path plus whether the user supplied the file directly."""

    path: Path
    explicit: bool


__all__ = [
    "NoQrPayloadsError",
    "QrDecoder",
    "QrScanError",
    "ScannedQrPayload",
    "looks_like_image",
    "looks_like_pdf",
    "scan_qr_payloads",
    "scan_qr_payloads_with_sources",
]


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
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
MAX_SCAN_INPUT_FILES = 2048
MAX_SCAN_INPUT_BYTES = 256 * 1024 * 1024
MAX_SCAN_PDF_PAGES = 4096
MAX_SCAN_PDF_IMAGES = 8192
MAX_SCAN_PDF_IMAGE_BYTES = 32 * 1024 * 1024
MAX_SCAN_IMAGE_PIXELS = 100_000_000
MAX_SCAN_QR_PAYLOADS = 8192
MAX_SCAN_WORKER_MEMORY_BYTES = 1024 * 1024 * 1024
MAX_SCAN_WORKER_CPU_SECONDS = 30
MAX_SCAN_WORKER_WALL_SECONDS = 45.0
MAX_SCAN_TOTAL_WALL_SECONDS = 180.0
MAX_SCAN_WORKER_OUTPUT_BYTES = 32 * 1024 * 1024


def _module(name: str, default: Any) -> Any:
    """Return an imported module override from `sys.modules` when present."""

    return sys.modules.get(name, default)


def _decode_image(image, *, zxing_module) -> list[bytes]:
    """Decode QR codes in an opened image object."""

    _enforce_image_pixel_budget(image)
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


def scan_qr_payloads(
    paths: Sequence[str | Path],
) -> list[bytes]:
    """Scan one or more paths and return decoded QR payload bytes."""

    return [payload.data for payload in scan_qr_payloads_with_sources(paths)]


def scan_qr_payloads_with_sources(
    paths: Sequence[str | Path],
) -> list[ScannedQrPayload]:
    """Scan one or more paths and return decoded QR payload bytes with source paths."""

    decoder = _load_decoder()
    payloads: list[ScannedQrPayload] = []
    scan_file_count = 0
    started_at = time.monotonic()
    for scan_input in _expand_paths(paths):
        path = scan_input.path
        scan_file_count += 1
        if scan_file_count > MAX_SCAN_INPUT_FILES:
            raise QrScanError(f"scan inputs exceed MAX_SCAN_INPUT_FILES ({MAX_SCAN_INPUT_FILES})")
        elapsed = time.monotonic() - started_at
        remaining_wall_seconds = MAX_SCAN_TOTAL_WALL_SECONDS - elapsed
        if remaining_wall_seconds <= 0:
            raise QrScanError(
                f"scan exceeded MAX_SCAN_TOTAL_WALL_SECONDS ({MAX_SCAN_TOTAL_WALL_SECONDS:g})"
            )
        source_payloads = (
            _scan_one_path_disposable(
                path,
                wall_seconds=min(MAX_SCAN_WORKER_WALL_SECONDS, remaining_wall_seconds),
            )
            if decoder.name == "zxingcpp"
            else _scan_one_path(path, decoder)
        )
        if scan_input.explicit and not source_payloads:
            raise NoQrPayloadsError(f"explicit scan input contains no QR codes: {path}")
        if len(payloads) + len(source_payloads) > MAX_SCAN_QR_PAYLOADS:
            raise QrScanError(
                f"decoded QR payloads exceed MAX_SCAN_QR_PAYLOADS ({MAX_SCAN_QR_PAYLOADS})"
            )
        payloads.extend(
            ScannedQrPayload(
                data=bytes(payload),
                source_path=path,
                source_is_explicit=scan_input.explicit,
            )
            for payload in source_payloads
        )

    if not payloads:
        raise NoQrPayloadsError("no QR codes found in scan inputs")
    return payloads


def _scan_one_path(path: Path, decoder: QrDecoder) -> list[bytes]:
    _enforce_scan_file_budget(path)
    if looks_like_pdf(path):
        return _scan_pdf(path, decoder)
    if looks_like_image(path):
        return _scan_image(path, decoder)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _scan_pdf(path, decoder)
    if suffix in _IMAGE_SUFFIXES:
        return _scan_image(path, decoder)
    raise QrScanError(f"unsupported scan file content: {path}")


def _scan_one_path_disposable(path: Path, *, wall_seconds: float) -> list[bytes]:
    """Parse and decode one untrusted file in a disposable subprocess."""

    try:
        return run_disposable_worker(
            "QR scan",
            _scan_one_path_worker,
            (str(path),),
            limits=WorkerLimits(
                memory_bytes=MAX_SCAN_WORKER_MEMORY_BYTES,
                cpu_seconds=MAX_SCAN_WORKER_CPU_SECONDS,
                wall_seconds=wall_seconds,
                output_bytes=MAX_SCAN_WORKER_OUTPUT_BYTES,
            ),
        )
    except DisposableWorkerError as exc:
        raise QrScanError(str(exc)) from exc


def _scan_one_path_worker(path_text: str) -> list[bytes]:
    path = Path(path_text)
    return _scan_one_path(path, _load_decoder())


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
    image_count = 0
    for page_index, page in enumerate(reader.pages, start=1):
        if page_index > MAX_SCAN_PDF_PAGES:
            raise QrScanError(f"PDF exceeds MAX_SCAN_PDF_PAGES ({MAX_SCAN_PDF_PAGES}): {path}")
        if not hasattr(page, "images"):
            raise QrScanError("pypdf is missing page.images support (upgrade pypdf)")
        for image in page.images:
            image_count += 1
            if image_count > MAX_SCAN_PDF_IMAGES:
                raise QrScanError(
                    f"PDF images exceed MAX_SCAN_PDF_IMAGES ({MAX_SCAN_PDF_IMAGES}): {path}"
                )
            data = image.data
            if len(data) > MAX_SCAN_PDF_IMAGE_BYTES:
                raise QrScanError(
                    "PDF embedded image exceeds MAX_SCAN_PDF_IMAGE_BYTES "
                    f"({MAX_SCAN_PDF_IMAGE_BYTES}): {path}"
                )
            try:
                payloads.extend(decoder.decode_image_bytes(data))
            except OSError:
                continue
    return payloads


def _enforce_scan_file_budget(path: Path) -> None:
    try:
        stat = path.stat()
    except OSError as exc:
        raise QrScanError(f"failed to stat scan file: {path}") from exc
    if not path.is_file():
        raise QrScanError(f"scan path must be a regular file: {path}")
    if stat.st_size > MAX_SCAN_INPUT_BYTES:
        raise QrScanError(
            f"scan file exceeds MAX_SCAN_INPUT_BYTES ({MAX_SCAN_INPUT_BYTES}): {path}"
        )


def _enforce_image_pixel_budget(image) -> None:
    size = getattr(image, "size", None)
    if not isinstance(size, tuple) or len(size) != 2:
        return
    width, height = size
    if not isinstance(width, int) or not isinstance(height, int):
        return
    if width < 0 or height < 0:
        raise QrScanError("scan image has invalid dimensions")
    if width * height > MAX_SCAN_IMAGE_PIXELS:
        raise QrScanError(f"scan image exceeds MAX_SCAN_IMAGE_PIXELS ({MAX_SCAN_IMAGE_PIXELS})")


def _expand_paths(
    paths: Sequence[str | Path],
) -> Iterable[_ScanInput]:
    """Expand path inputs, recursing into directories for supported scan files."""

    for raw in paths:
        path = Path(raw)
        if path.is_symlink():
            raise QrScanError(f"scan path must not be a symlink: {path}")
        if not path.exists():
            raise QrScanError(f"scan path not found: {path}")
        if path.is_dir():
            scan_files = _iter_scan_files(path)
            if not scan_files:
                raise QrScanError(f"no scan files found in directory: {path}")
            yield from (_ScanInput(path=scan_file, explicit=False) for scan_file in scan_files)
        else:
            yield _ScanInput(path=path, explicit=True)


def _iter_scan_files(
    directory: Path,
) -> list[Path]:
    """Collect supported scan files from a directory tree."""

    if directory.is_symlink():
        raise QrScanError(f"scan directory must not be a symlink: {directory}")
    if any(part.startswith(".staging-") for part in directory.parts):
        return []
    files: list[Path] = []
    for root, dirnames, filenames in os.walk(directory):
        root_path = Path(root)
        dirnames[:] = sorted(name for name in dirnames if not name.startswith(".staging-"))
        for name in dirnames:
            if (root_path / name).is_symlink():
                raise QrScanError(
                    f"scan directory must not contain symlinked directories: {root_path / name}"
                )
        for filename in filenames:
            path = root_path / filename
            if path.is_symlink():
                raise QrScanError(f"scan file must not be a symlink: {path}")
            suffix = path.suffix.lower()
            if _looks_like_scan_file(path) or suffix == ".pdf" or suffix in _IMAGE_SUFFIXES:
                if len(files) >= MAX_SCAN_INPUT_FILES:
                    raise QrScanError(
                        f"scan inputs exceed MAX_SCAN_INPUT_FILES ({MAX_SCAN_INPUT_FILES})"
                    )
                files.append(path)
    files.sort()
    return files


def _looks_like_scan_file(path: Path) -> bool:
    return looks_like_pdf(path) or looks_like_image(path)


def _read_file_prefix(path: Path, size: int = 16) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def looks_like_pdf(path: Path) -> bool:
    return _read_file_prefix(path).startswith(_PDF_MAGIC)


def looks_like_image(path: Path) -> bool:
    prefix = _read_file_prefix(path)
    if any(prefix.startswith(magic) for magic in _IMAGE_MAGICS):
        if prefix.startswith(b"RIFF") and prefix[8:12] != b"WEBP":
            return False
        return True
    return False
