from __future__ import annotations

import io
from pathlib import Path
from typing import Sequence

from PIL import ImageGrab

from ethernity.cli.io.frames import _frame_from_scanned_payload
from ethernity.encoding.framing import Frame
from ethernity.qr.scan import QrScanError, _load_decoder, scan_qr_payloads

from .bootstrap import SRC_ROOT as _SRC_ROOT  # noqa: F401
from .constants import SCAN_SUFFIXES
from .formatting import payload_lines_from_frames


def _frames_from_scanned_payloads(
    payloads: Sequence[bytes | str], *, source: str
) -> tuple[list[Frame], list[str]]:
    frames: list[Frame] = []
    errors: list[str] = []
    for index, payload in enumerate(payloads, start=1):
        try:
            frames.append(_frame_from_scanned_payload(payload))
        except ValueError as exc:
            errors.append(f"#{index}: {exc}")
    if not frames:
        if errors:
            raise ValueError(f"no valid QR payloads found in {source}: {'; '.join(errors[:3])}")
        raise ValueError(f"no QR payloads found in {source}")
    warnings: list[str] = []
    if errors:
        warnings.append(f"ignored {len(errors)} invalid scanned payload(s) from {source}")
    return frames, warnings


def _payload_text_from_scan_paths(paths: Sequence[str | Path]) -> tuple[str, list[str]]:
    try:
        payloads = scan_qr_payloads([str(path) for path in paths])
    except QrScanError as exc:
        raise ValueError(str(exc)) from exc
    frames, warnings = _frames_from_scanned_payloads(payloads, source="scan files")
    return "\n".join(payload_lines_from_frames(frames)) + "\n", warnings


def _payload_text_from_clipboard_image(*, allow_missing: bool) -> tuple[str, list[str]] | None:
    try:
        clipboard_object = ImageGrab.grabclipboard()
    except Exception as exc:
        raise ValueError(f"failed to read clipboard image: {exc}") from exc

    if clipboard_object is None:
        if allow_missing:
            return None
        raise ValueError("clipboard does not contain an image or dropped file list")

    if isinstance(clipboard_object, list):
        if not clipboard_object:
            if allow_missing:
                return None
            raise ValueError("clipboard file list is empty")
        return _payload_text_from_scan_paths([Path(path) for path in clipboard_object])

    if not hasattr(clipboard_object, "save"):
        if allow_missing:
            return None
        raise ValueError("clipboard does not contain an image")

    image_buffer = io.BytesIO()
    clipboard_object.save(image_buffer, format="PNG")
    decoder = _load_decoder()
    try:
        payloads = decoder.decode_image_bytes(image_buffer.getvalue())
    except OSError as exc:
        raise ValueError("failed to decode clipboard image") from exc
    if not payloads:
        raise ValueError("no QR codes found in clipboard image")
    frames, warnings = _frames_from_scanned_payloads(payloads, source="clipboard image")
    return "\n".join(payload_lines_from_frames(frames)) + "\n", warnings


def _collect_scan_files(paths: Sequence[str | Path]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            raise ValueError(f"scan path not found: {path}")
        if path.is_dir():
            matches = [
                item
                for item in sorted(path.rglob("*"))
                if item.is_file() and item.suffix.lower() in SCAN_SUFFIXES
            ]
            if not matches:
                raise ValueError(f"no supported scan files found in directory: {path}")
            files.extend(matches)
            continue
        if path.suffix.lower() not in SCAN_SUFFIXES:
            raise ValueError(f"unsupported scan file type: {path}")
        files.append(path)

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


__all__ = [
    "_collect_scan_files",
    "_frames_from_scanned_payloads",
    "_payload_text_from_clipboard_image",
    "_payload_text_from_scan_paths",
]
