#!/usr/bin/env python3
from __future__ import annotations

import base64
import sys

from ...encoding.framing import Frame, FrameType, decode_frame
from ...encoding.qr_payloads import decode_qr_payload, normalize_qr_payload_encoding
from ...qr.scan import QrScanError, scan_qr_payloads
from ..core.log import _warn
from .fallback_parser import (
    contains_fallback_markers as _contains_fallback_markers,
    parse_fallback_frame as _parse_fallback_frame,
    split_fallback_sections as _split_fallback_sections,
)


def _read_text_lines(path: str) -> list[str]:
    if path == "-":
        text = sys.stdin.read()
    else:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except FileNotFoundError as exc:
            raise ValueError(f"file not found: {path}") from exc
        except OSError as exc:
            raise ValueError(f"unable to read file: {path}") from exc
    return text.splitlines()


def _frame_from_fallback(path: str) -> Frame:
    lines = _read_text_lines(path)
    return _frame_from_fallback_lines(lines, label="fallback")


def _frames_from_fallback(path: str, *, allow_invalid_auth: bool, quiet: bool) -> list[Frame]:
    lines = _read_text_lines(path)
    if not _contains_fallback_markers(lines):
        return [_frame_from_fallback_lines(lines, label="fallback")]
    sections = _split_fallback_sections(lines)

    if not sections["main"]:
        raise ValueError("missing MAIN fallback section; include the MAIN section from recovery")

    frames: list[Frame] = []
    frames.append(_frame_from_fallback_lines(sections["main"], label="main"))
    if sections["auth"]:
        try:
            frames.append(_frame_from_fallback_lines(sections["auth"], label="auth"))
        except ValueError as exc:
            if allow_invalid_auth:
                _warn(f"invalid auth fallback ignored: {exc}", quiet=quiet)
            else:
                raise
    return frames


def _auth_frames_from_fallback(path: str, *, allow_invalid_auth: bool, quiet: bool) -> list[Frame]:
    lines = _read_text_lines(path)
    if not _contains_fallback_markers(lines):
        return [_frame_from_fallback_lines(lines, label="auth")]
    sections = _split_fallback_sections(lines)

    if not sections["auth"]:
        raise ValueError("missing AUTH fallback section; include AUTH or use --allow-unsigned")

    try:
        return [_frame_from_fallback_lines(sections["auth"], label="auth")]
    except ValueError as exc:
        if allow_invalid_auth:
            _warn(f"invalid auth fallback ignored: {exc}", quiet=quiet)
            return []
        raise


def _frame_from_fallback_lines(lines: list[str], *, label: str) -> Frame:
    frame, skipped = _parse_fallback_frame(lines, label=label)
    if skipped:
        print(f"warning: skipped {skipped} non-fallback lines ({label})", file=sys.stderr)
    return frame


def _frames_from_payloads(path: str, encoding: str, *, label: str = "frame") -> list[Frame]:
    lines = _read_text_lines(path)
    frames: list[Frame] = []
    for idx, line in enumerate(lines, start=1):
        payload_text = line.strip()
        if not payload_text:
            continue
        try:
            payload = _decode_payload(payload_text, encoding)
            frames.append(decode_frame(payload))
        except ValueError as exc:
            raise ValueError(f"invalid frame payload on line {idx}: {exc}") from exc
    if not frames:
        raise ValueError(f"no {label} payloads found in {path}; check the file and encoding")
    return frames


def _auth_frames_from_payloads(path: str, encoding: str) -> list[Frame]:
    frames = _frames_from_payloads(path, encoding, label="auth frame")
    for frame in frames:
        if frame.frame_type != FrameType.AUTH:
            raise ValueError("auth frames file must contain AUTH frames only")
    return frames


def _frames_from_shard_inputs(
    fallback_files: list[str],
    frame_files: list[str],
    encoding: str,
) -> list[Frame]:
    frames: list[Frame] = []
    for path in fallback_files:
        frames.append(_frame_from_fallback(path))
    for path in frame_files:
        frames.extend(_frames_from_payloads(path, encoding, label="shard frame"))
    return frames


def _frames_from_scan(paths: list[str], encoding: str) -> list[Frame]:
    try:
        payloads = scan_qr_payloads(paths)
    except QrScanError as exc:
        raise ValueError(f"scan failed: {exc}") from exc
    if not payloads:
        raise ValueError("no QR payloads found; check the scan path and image quality")
    frames: list[Frame] = []
    errors: list[str] = []
    encoding = normalize_qr_payload_encoding(encoding)
    for idx, payload in enumerate(payloads, start=1):
        try:
            decoded = decode_qr_payload(payload, encoding)
            frames.append(decode_frame(decoded))
        except ValueError as exc:
            errors.append(f"#{idx}: {exc}")
            continue
    if not frames:
        if errors:
            detail = "; ".join(errors[:3])
            raise ValueError(f"invalid QR payloads ({len(errors)}): {detail}")
        raise ValueError("no QR payloads found; check the scan path and image quality")
    return frames


def _dedupe_frames(frames: list[Frame]) -> list[Frame]:
    seen: dict[tuple[int, int, bytes], Frame] = {}
    deduped: list[Frame] = []
    for frame in frames:
        key = (int(frame.frame_type), int(frame.index), frame.doc_id)
        existing = seen.get(key)
        if existing:
            if existing.data != frame.data or existing.total != frame.total:
                raise ValueError("conflicting duplicate frames detected")
            continue
        seen[key] = frame
        deduped.append(frame)
    return deduped


def _dedupe_auth_frames(frames: list[Frame]) -> list[Frame]:
    if not frames:
        return []
    deduped = _dedupe_frames(frames)
    for frame in deduped:
        if frame.frame_type != FrameType.AUTH:
            raise ValueError("auth frames must be AUTH type")
    return deduped


def _split_main_and_auth_frames(frames: list[Frame]) -> tuple[list[Frame], list[Frame]]:
    main_frames: list[Frame] = []
    auth_frames: list[Frame] = []
    for frame in frames:
        if frame.frame_type == FrameType.MAIN_DOCUMENT:
            main_frames.append(frame)
        elif frame.frame_type == FrameType.AUTH:
            auth_frames.append(frame)
        else:
            raise ValueError("unexpected frame type in main document payloads")
    if not main_frames:
        raise ValueError("no main document frames provided; check the MAIN frames/fallback")
    return main_frames, auth_frames


def _decode_payload(text: str, encoding: str) -> bytes:
    cleaned = "".join(text.split())
    if encoding == "hex":
        return bytes.fromhex(cleaned)
    if encoding == "base64":
        return base64.b64decode(_pad_base64(cleaned), validate=True)
    if encoding == "base64url":
        return base64.urlsafe_b64decode(_pad_base64(cleaned))
    if encoding != "auto":
        raise ValueError(f"unknown encoding: {encoding}")

    if _looks_like_hex(cleaned):
        return bytes.fromhex(cleaned)
    try:
        return base64.b64decode(_pad_base64(cleaned), validate=True)
    except ValueError:
        return base64.urlsafe_b64decode(_pad_base64(cleaned))


def _looks_like_hex(text: str) -> bool:
    if len(text) % 2 != 0 or not text:
        return False
    try:
        bytes.fromhex(text)
    except ValueError:
        return False
    return True


def _pad_base64(text: str) -> str:
    padding = (-len(text)) % 4
    return text + ("=" * padding)
