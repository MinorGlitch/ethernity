#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
from typing import Callable, Iterable, Sequence


class QrScanError(RuntimeError):
    pass


@dataclass(frozen=True)
class QrDecoder:
    name: str
    decode_image_path: Callable[[Path], list[bytes]]
    decode_image_bytes: Callable[[bytes], list[bytes]]


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


def scan_qr_payloads(paths: Sequence[str | Path]) -> list[bytes]:
    decoder = _load_decoder()
    payloads: list[bytes] = []
    for path in _expand_paths(paths):
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            payloads.extend(_scan_pdf(path, decoder))
        elif suffix in _IMAGE_SUFFIXES:
            payloads.extend(_scan_image(path, decoder))
        else:
            raise QrScanError(f"unsupported scan file type: {path}")

    if not payloads:
        raise QrScanError("no QR codes found in scan inputs")
    return payloads


def _load_decoder() -> QrDecoder:
    try:
        import zxingcpp
    except ImportError as exc:  # pragma: no cover - depends on optional deps
        raise QrScanError(
            "QR decoding requires the optional dependencies: zxing-cpp and pillow"
        ) from exc

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - depends on optional deps
        raise QrScanError("QR decoding requires the optional dependency: pillow") from exc

    def decode_image(image) -> list[bytes]:
        results = zxingcpp.read_barcodes(image)
        payloads: list[bytes] = []
        for result in results:
            data = getattr(result, "bytes", None) or getattr(result, "raw_bytes", None)
            if data:
                payloads.append(bytes(data))
            elif getattr(result, "text", None):
                payloads.append(result.text.encode("utf-8"))
        return payloads

    def decode_image_path(path: Path) -> list[bytes]:
        with Image.open(path) as image:
            return decode_image(image)

    def decode_image_bytes(data: bytes) -> list[bytes]:
        with Image.open(io.BytesIO(data)) as image:
            return decode_image(image)

    return QrDecoder(
        name="zxingcpp",
        decode_image_path=decode_image_path,
        decode_image_bytes=decode_image_bytes,
    )


def _scan_image(path: Path, decoder: QrDecoder) -> list[bytes]:
    try:
        return decoder.decode_image_path(path)
    except OSError as exc:
        raise QrScanError(f"failed to read image: {path}") from exc


def _scan_pdf(path: Path, decoder: QrDecoder) -> list[bytes]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - depends on optional deps
        raise QrScanError("PDF scanning requires the optional dependency: pypdf") from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # pragma: no cover - depends on external PDFs
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
    files: list[Path] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".pdf" or suffix in _IMAGE_SUFFIXES:
            files.append(path)
    return files
