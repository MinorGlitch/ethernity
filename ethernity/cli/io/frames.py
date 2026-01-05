#!/usr/bin/env python3
from __future__ import annotations

import base64
import sys

from ..core.log import _warn
from ...chunking import ZBASE32_ALPHABET, fallback_lines_to_frame
from ...framing import Frame, FrameType, decode_frame
from ...qr_payloads import decode_qr_payload, normalize_qr_payload_encoding
from ...qr_scan import QrScanError, scan_qr_payloads


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


def _filter_fallback_lines(lines: list[str]) -> tuple[list[str], int]:
    allowed = set(ZBASE32_ALPHABET + " -")
    filtered: list[str] = []
    skipped = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if all(ch.lower() in allowed for ch in stripped):
            filtered.append(stripped)
        else:
            skipped += 1
    return filtered, skipped


def _frame_from_fallback(path: str) -> Frame:
    lines = _read_text_lines(path)
    return _frame_from_fallback_lines(lines, label="fallback")


def _frames_from_fallback(path: str, *, allow_invalid_auth: bool, quiet: bool) -> list[Frame]:
    lines = _read_text_lines(path)
    if not _contains_fallback_markers(lines):
        return [_frame_from_fallback_lines(lines, label="fallback")]

    sections = {"auth": [], "main": []}
    current: str | None = None
    for line in lines:
        section = _detect_fallback_section(line)
        if section:
            current = section
            continue
        if current:
            sections[current].append(line)

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

    sections = {"auth": [], "main": []}
    current: str | None = None
    for line in lines:
        section = _detect_fallback_section(line)
        if section:
            current = section
            continue
        if current:
            sections[current].append(line)

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
    filtered, skipped = _filter_fallback_lines(lines)
    if skipped:
        print(f"warning: skipped {skipped} non-fallback lines ({label})", file=sys.stderr)
    if not filtered:
        raise ValueError(
            f"no fallback lines found ({label}); check the z-base-32 fallback text"
        )
    return fallback_lines_to_frame(filtered)


def _contains_fallback_markers(lines: list[str]) -> bool:
    return any(_detect_fallback_section(line) for line in lines)


def _detect_fallback_section(line: str) -> str | None:
    normalized = line.strip().lower()
    if "auth frame" in normalized:
        return "auth"
    if "main frame" in normalized:
        return "main"
    return None


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
    encoding = normalize_qr_payload_encoding(encoding)
    for idx, payload in enumerate(payloads, start=1):
        try:
            decoded = decode_qr_payload(payload, encoding)
            frames.append(decode_frame(decoded))
        except ValueError as exc:
            raise ValueError(f"invalid QR payload #{idx}: {exc}") from exc
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
