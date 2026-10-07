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

"""Adapter-neutral recovery-kit bundle, chunking, and rendering service."""

from __future__ import annotations

import ast
import hashlib
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from ethernity.config import AppConfig, apply_render_style, load_app_config
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.qr.capacity import fits_qr_payload
from ethernity.qr.codec import QrConfig
from ethernity.render import render_frames_to_pdf
from ethernity.render.service import RenderService
from ethernity.render.types import DocumentOrigin, RenderInputs, RenderResult
from ethernity.render.validation import validate_rendered_pdf_document
from ethernity.workflows.kit import printed
from ethernity.workflows.shared.events import emit_finalizing, emit_phase, report_render_page

DEFAULT_KIT_BUNDLE_NAME = "recovery_kit.bundle.html"
SCANNER_KIT_BUNDLE_NAME = "recovery_kit.scanner.bundle.html"
DEFAULT_KIT_OUTPUT = "recovery_kit_qr.pdf"
# Fill a version-29 alphanumeric symbol at M; custom QR settings are probed below.
DEFAULT_KIT_CHUNK_SIZE = 1839
_MAX_QR_PROBE_BYTES = 4000
_JS_IDENTIFIER_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_BASE91_ALPHABET = (
    "!#$%&'()*+,-./0123456789:;=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abcdefghijklmnopqrstuvwxyz{|}~"
)
_SUPPORTED_KIT_BUNDLE_COMPRESSIONS = {"gzip", "brotli"}
_DEV_KIT_DIST_ROOT = Path(__file__).resolve().parents[4] / "kit" / "dist"


@dataclass(frozen=True)
class KitRequest:
    output_path: Path
    config_path: Path | None
    paper_size: str
    design: str
    variant: Literal["lean", "scanner"]
    chunk_size: int | None


@dataclass(frozen=True)
class KitResult:
    output_path: Path
    chunk_count: int
    chunk_size: int
    bytes_total: int
    doc_id_hex: str


@dataclass(frozen=True)
class KitBundleLoaderMetadata:
    payload: str
    compression: str
    alphabet: str = _BASE91_ALPHABET


def create_kit(request: KitRequest) -> KitResult:
    """Resolve user-facing kit settings and create one kit PDF."""

    config = load_app_config(request.config_path, paper_size=request.paper_size)
    config = apply_render_style(config, request.design)
    return render_kit_qr_document(
        output_path=request.output_path,
        config=config,
        variant=request.variant,
        chunk_size=request.chunk_size,
    )


def render_kit_qr_document(
    *,
    output_path: Path,
    config: AppConfig,
    variant: str,
    chunk_size: int | None,
    render_pdf: Callable[[RenderInputs], RenderResult] | None = None,
    bundle_loader: Callable[..., bytes] | None = None,
    payload_builder: Callable[..., list[bytes]] | None = None,
    capacity_resolver: Callable[[bytes, QrConfig], int] | None = None,
    render_service_factory: Callable[[AppConfig], RenderService] | None = None,
) -> KitResult:
    """Render a recovery kit from already-resolved workflow inputs."""

    emit_phase(phase="prepare", label="Preparing recovery kit")
    normalized_variant = _normalize_kit_variant(variant)
    load_bundle = bundle_loader or _load_kit_bundle
    build_payloads = payload_builder or build_kit_qr_payloads
    resolve_capacity = capacity_resolver or _max_qr_payload_bytes
    bundle_bytes = load_bundle(variant=normalized_variant)
    qr_config = config.qr_config

    resolved_chunk_size = chunk_size
    if resolved_chunk_size is None:
        max_size = resolve_capacity(b"A" * _MAX_QR_PROBE_BYTES, qr_config)
        resolved_chunk_size = min(DEFAULT_KIT_CHUNK_SIZE, max_size)

    if resolved_chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    qr_payloads = build_payloads(
        bundle_bytes,
        resolved_chunk_size,
        qr_config,
    )
    doc_id = hashlib.blake2b(b"".join(qr_payloads), digest_size=DOC_ID_LEN).digest()
    frames = [
        Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=index,
            total=len(qr_payloads),
            data=b"",
        )
        for index in range(len(qr_payloads))
    ]

    create_render_service = render_service_factory or RenderService
    render_service = create_render_service(config)
    emit_phase(phase="output", label="Preparing recovery kit destination")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ethernity-kit-", dir=output_path.parent) as staging:
        staged_path = Path(staging) / output_path.name
        inputs = render_service.kit_inputs(
            frames,
            staged_path,
            qr_payloads=qr_payloads,
            context=render_service.base_context(),
            origin=DocumentOrigin(kind="recovery_kit"),
        )
        inputs = replace(inputs, on_page=report_render_page)
        emit_phase(phase="render", label="Creating recovery kit PDF")
        result = (render_pdf or render_frames_to_pdf)(inputs)
        emit_phase(phase="verify", label="Checking recovery kit PDF")
        validate_rendered_pdf_document(
            inputs=inputs, result=result, document_label="rendered recovery kit"
        )
        emit_finalizing()
        staged_path.replace(output_path)

    return KitResult(
        output_path=output_path,
        chunk_count=len(qr_payloads),
        chunk_size=resolved_chunk_size,
        bytes_total=len(bundle_bytes),
        doc_id_hex=doc_id.hex(),
    )


def _normalize_kit_variant(value: str | None) -> str:
    variant = (value or "lean").strip().lower()
    if variant not in {"lean", "scanner"}:
        raise ValueError("variant must be 'lean' or 'scanner'")
    return variant


def _default_kit_bundle_name(variant: str) -> str:
    normalized = _normalize_kit_variant(variant)
    if normalized == "scanner":
        return SCANNER_KIT_BUNDLE_NAME
    return DEFAULT_KIT_BUNDLE_NAME


def _load_kit_bundle(
    *,
    variant: str = "lean",
    resource_files: Callable[[str], Any] | None = None,
    dev_dist_root: Path | None = None,
) -> bytes:
    """Load the built-in recovery kit bundle from package or development build output."""

    bundle_name = _default_kit_bundle_name(variant)
    read_resources = resource_files or files
    try:
        return read_resources("ethernity.resources").joinpath("kit", bundle_name).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError):
        pass
    candidate = (dev_dist_root or _DEV_KIT_DIST_ROOT) / bundle_name
    if candidate.exists():
        return candidate.read_bytes()
    raise FileNotFoundError(
        "Recovery kit bundle not found. Reinstall the package or rebuild the bundled kit assets."
    )


def _skip_js_string(source: str, offset: int) -> int:
    quote = source[offset]
    index = offset + 1
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        index += 1
    return index


def _skip_js_space(source: str, offset: int) -> int:
    index = offset
    while index < len(source) and source[index].isspace():
        index += 1
    return index


def _extract_loader_string_literal(source: str, name: str) -> str | None:
    index = 0
    while index < len(source):
        char = source[index]
        if char in {'"', "'"}:
            index = _skip_js_string(source, index)
            continue
        if char == "/" and source[index : index + 2] == "//":
            newline = source.find("\n", index + 2)
            index = len(source) if newline < 0 else newline + 1
            continue
        if char == "/" and source[index : index + 2] == "/*":
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        match = _JS_IDENTIFIER_RE.match(source, index)
        if match is None:
            index += 1
            continue
        identifier = match.group(0)
        index = match.end()
        if identifier != name:
            continue
        assign_index = _skip_js_space(source, index)
        if assign_index >= len(source) or source[assign_index] != "=":
            continue
        value_index = _skip_js_space(source, assign_index + 1)
        if value_index < len(source) and source[value_index] in {'"', "'"}:
            return source[value_index : _skip_js_string(source, value_index)]
    return None


def _parse_loader_string_literal(literal: str, field: str) -> str:
    try:
        value = ast.literal_eval(literal)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(
            f"unsupported recovery kit bundle format: {field} is not a string"
        ) from exc
    if not isinstance(value, str):
        raise ValueError(f"unsupported recovery kit bundle format: {field} is not a string")
    return value


def _extract_kit_bundle_loader_metadata(bundle_bytes: bytes) -> KitBundleLoaderMetadata:
    try:
        bundle_text = bundle_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("recovery kit bundle is not valid UTF-8 HTML") from exc
    payload_literal = _extract_loader_string_literal(bundle_text, "p")
    if payload_literal is None:
        raise ValueError(
            "unsupported recovery kit bundle format: embedded loader payload was not found"
        )
    payload = _parse_loader_string_literal(payload_literal, "loader payload")
    compression = "gzip"
    compression_literal = _extract_loader_string_literal(bundle_text, "f")
    if compression_literal is not None:
        compression = _parse_loader_string_literal(
            compression_literal, "loader compression"
        ).lower()
    if compression not in _SUPPORTED_KIT_BUNDLE_COMPRESSIONS:
        raise ValueError(
            "unsupported recovery kit bundle format: loader compression must be gzip or brotli"
        )
    alphabet_literal = _extract_loader_string_literal(bundle_text, "a")
    alphabet = (
        _parse_loader_string_literal(alphabet_literal, "loader alphabet")
        if alphabet_literal is not None
        else _BASE91_ALPHABET
    )
    if len(alphabet) != 91 or len(set(alphabet)) != 91:
        raise ValueError("unsupported recovery kit bundle format: invalid Base91 alphabet")
    return KitBundleLoaderMetadata(payload=payload, compression=compression, alphabet=alphabet)


def _decode_base91(payload: str, alphabet: str) -> bytes:
    digits = {char: index for index, char in enumerate(alphabet)}
    output = bytearray()
    buffer = bits = 0
    value = -1
    for char in payload:
        if char not in digits:
            raise ValueError("invalid Base91 character in recovery kit bundle")
        digit = digits[char]
        if value < 0:
            value = digit
            continue
        value += digit * 91
        buffer |= value << bits
        bits += 13 if value & 8191 > 88 else 14
        while bits > 7:
            output.append(buffer & 255)
            buffer >>= 8
            bits -= 8
        value = -1
    if value >= 0:
        output.append((buffer | value << bits) & 255)
    return bytes(output)


def build_kit_qr_payloads(
    bundle_bytes: bytes,
    chunk_size: int,
    config: QrConfig,
) -> list[bytes]:
    loader_metadata = _extract_kit_bundle_loader_metadata(bundle_bytes)
    compressed = _decode_base91(loader_metadata.payload, loader_metadata.alphabet)
    if not compressed:
        raise ValueError("recovery kit bundle payload is empty")
    return printed.build_payloads(compressed, loader_metadata.compression, chunk_size, config)


def _max_qr_payload_bytes(
    data: bytes,
    config: QrConfig,
    *,
    payload_fits: Callable[[bytes, QrConfig], bool] | None = None,
) -> int:
    fits_payload = payload_fits or fits_qr_payload
    max_probe = max(1, min(len(data), _MAX_QR_PROBE_BYTES))
    if not fits_payload(data[:1], config):
        raise ValueError("QR settings cannot encode any payload bytes")
    if fits_payload(data[:max_probe], config):
        return max_probe
    lower = 1
    upper = max_probe
    while lower + 1 < upper:
        mid = (lower + upper) // 2
        if fits_payload(data[:mid], config):
            lower = mid
        else:
            upper = mid
    return lower


__all__ = [
    "DEFAULT_KIT_BUNDLE_NAME",
    "DEFAULT_KIT_CHUNK_SIZE",
    "DEFAULT_KIT_OUTPUT",
    "KitBundleLoaderMetadata",
    "KitRequest",
    "KitResult",
    "SCANNER_KIT_BUNDLE_NAME",
    "create_kit",
    "build_kit_qr_payloads",
    "render_kit_qr_document",
]
