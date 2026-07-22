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
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable, Sequence

from ethernity.config import AppConfig
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.formats.extension_envelope_constants import (
    EXTENSION_ENVELOPE_VERSION,
    EXTENSION_SCHEMA_VERSION,
)
from ethernity.qr.capacity import fits_qr_payload
from ethernity.qr.codec import QrConfig
from ethernity.render import render_frames_to_pdf
from ethernity.render.service import RenderService
from ethernity.render.types import RenderInputs, RenderLineage, RenderResult

DEFAULT_KIT_BUNDLE_NAME = "recovery_kit.bundle.html"
SCANNER_KIT_BUNDLE_NAME = "recovery_kit.scanner.bundle.html"
DEFAULT_KIT_CHUNK_SIZE = 1200
_MAX_QR_PROBE_BYTES = 4000
_JS_IDENTIFIER_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_KIT_CHUNK_ARRAY = "_k"
_BASE91_ALPHABET = (
    "!#$%&'()*+,-./0123456789:;=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abcdefghijklmnopqrstuvwxyz{|}~"
)
_SUPPORTED_KIT_BUNDLE_COMPRESSIONS = {"gzip", "brotli"}
_DEV_KIT_DIST_ROOT = Path(__file__).resolve().parents[4] / "kit" / "dist"


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


@dataclass(frozen=True)
class KitAnchor:
    """Authenticated chain identity and freshness claim embedded in a recovery kit."""

    root_document_hash: bytes
    root_signing_public_key: bytes
    expected_latest_head_hash: bytes

    def __post_init__(self) -> None:
        for label, value in (
            ("root_document_hash", self.root_document_hash),
            ("root_signing_public_key", self.root_signing_public_key),
            ("expected_latest_head_hash", self.expected_latest_head_hash),
        ):
            if not isinstance(value, bytes) or len(value) != 32:
                raise ValueError(f"{label} must be exactly 32 bytes")

    def as_json_object(self) -> dict[str, object]:
        return {
            "capability": "ethernity-chain-bound-recovery",
            "version": 1,
            "root_document_hash": self.root_document_hash.hex(),
            "root_signing_public_key_fingerprint": hashlib.sha256(
                self.root_signing_public_key
            ).hexdigest(),
            "expected_latest_head_hash": self.expected_latest_head_hash.hex(),
            "supported_extension_envelope_versions": [EXTENSION_ENVELOPE_VERSION],
            "supported_extension_schema_versions": [EXTENSION_SCHEMA_VERSION],
        }


def render_kit_qr_document(
    *,
    output_path: Path,
    config: AppConfig,
    variant: str,
    chunk_size: int | None,
    anchor: KitAnchor | None = None,
    render_pdf: Callable[[RenderInputs], RenderResult] | None = None,
    bundle_loader: Callable[..., bytes] | None = None,
    payload_builder: Callable[..., list[bytes]] | None = None,
    capacity_resolver: Callable[[bytes, QrConfig], int] | None = None,
    render_service_factory: Callable[[AppConfig], RenderService] | None = None,
) -> KitResult:
    """Render a recovery kit from already-resolved workflow inputs."""

    normalized_variant = _normalize_kit_variant(variant)
    load_bundle = bundle_loader or _load_kit_bundle
    build_payloads = payload_builder or _build_kit_qr_payloads
    resolve_capacity = capacity_resolver or _max_qr_payload_bytes
    bundle_bytes = load_bundle(variant=normalized_variant)
    qr_config = config.qr_config

    resolved_chunk_size = chunk_size
    if resolved_chunk_size is None:
        max_size = resolve_capacity(b"x" * _MAX_QR_PROBE_BYTES, qr_config)
        resolved_chunk_size = min(DEFAULT_KIT_CHUNK_SIZE, max_size)

    if resolved_chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    qr_payloads = build_payloads(
        bundle_bytes,
        resolved_chunk_size,
        qr_config,
        embedded_metadata=_kit_metadata(anchor),
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
    inputs = render_service.kit_inputs(
        frames,
        output_path,
        qr_payloads=qr_payloads,
        context=render_service.base_context(),
        lineage=RenderLineage(kind="recovery_kit"),
    )
    (render_pdf or render_frames_to_pdf)(inputs)

    return KitResult(
        output_path=output_path,
        chunk_count=len(qr_payloads),
        chunk_size=resolved_chunk_size,
        bytes_total=len(bundle_bytes),
        doc_id_hex=doc_id.hex(),
    )


def validate_chain_bound_kit_carrier(
    raw_qr_payloads: Sequence[bytes],
    *,
    config: AppConfig,
    anchor: KitAnchor,
    chunk_size: int | None = None,
    bundle_loader: Callable[..., bytes] | None = None,
) -> None:
    """Require a canonical, ordered chain-bound carrier for the packaged lean kit."""

    payloads = tuple(raw_qr_payloads)
    if not payloads:
        raise ValueError("chain-bound recovery kit carrier contains no QR payloads")
    if any(not isinstance(payload, bytes) for payload in payloads):
        raise ValueError("chain-bound recovery kit carrier payloads must be raw bytes")

    load_bundle = bundle_loader or _load_kit_bundle
    bundle_bytes = load_bundle(variant="lean")
    resolved_chunk_size = chunk_size
    if resolved_chunk_size is None:
        max_size = _max_qr_payload_bytes(b"x" * _MAX_QR_PROBE_BYTES, config.qr_config)
        resolved_chunk_size = min(DEFAULT_KIT_CHUNK_SIZE, max_size)
    if resolved_chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    expected_payloads = tuple(
        _build_kit_qr_payloads(
            bundle_bytes,
            resolved_chunk_size,
            config.qr_config,
            embedded_metadata=anchor.as_json_object(),
        )
    )
    if len(payloads) != len(expected_payloads):
        raise ValueError(
            "chain-bound recovery kit carrier QR count mismatch: "
            f"expected {len(expected_payloads)}, found {len(payloads)}"
        )
    if payloads[0] != expected_payloads[0]:
        raise ValueError(
            "chain-bound recovery kit shell is non-canonical or has mismatched anchor metadata"
        )
    for index, (payload, expected) in enumerate(
        zip(payloads[1:], expected_payloads[1:], strict=True),
        start=1,
    ):
        if payload != expected:
            raise ValueError(
                "chain-bound recovery kit payload chunks are non-canonical, reordered, or do not "
                f"reconstruct the packaged lean bundle (QR {index + 1})"
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
    return KitBundleLoaderMetadata(payload=payload, compression=compression)


def _extract_kit_bundle_loader_payload(bundle_bytes: bytes) -> str:
    return _extract_kit_bundle_loader_metadata(bundle_bytes).payload


def _kit_chunk_script(chunk: str) -> bytes:
    literal = json.dumps(chunk).replace("<", "\\u003c")
    return (
        f"<script>(globalThis.{_KIT_CHUNK_ARRAY}||(globalThis.{_KIT_CHUNK_ARRAY}=[])).push("
        f"{literal})</script>"
    ).encode("ascii")


def _split_kit_payload_chunks(payload: str, chunk_payload_size: int) -> list[bytes]:
    if chunk_payload_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not payload:
        return []
    chunks: list[bytes] = []
    offset = 0
    while offset < len(payload):
        remaining = payload[offset:]
        low = 1
        high = len(remaining)
        best = 0
        while low <= high:
            mid = (low + high) // 2
            candidate = _kit_chunk_script(remaining[:mid])
            if len(candidate) <= chunk_payload_size:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        if best <= 0:
            raise ValueError(
                "chunk_size is too small for the recovery kit payload wrapper; "
                "increase --qr-chunk-size."
            )
        part = remaining[:best]
        chunks.append(_kit_chunk_script(part))
        offset += best
    return chunks


def _kit_metadata(anchor: KitAnchor | None) -> dict[str, object]:
    if anchor is not None:
        return anchor.as_json_object()
    return {
        "capability": "ethernity-unanchored-rescue",
        "version": 1,
        "supported_extension_envelope_versions": [EXTENSION_ENVELOPE_VERSION],
        "supported_extension_schema_versions": [EXTENSION_SCHEMA_VERSION],
    }


def _kit_shell_payload(
    *,
    chunk_count: int,
    compression: str = "gzip",
    metadata: dict[str, object] | None = None,
) -> bytes:
    if compression not in _SUPPORTED_KIT_BUNDLE_COMPRESSIONS:
        raise ValueError("compression must be gzip or brotli")
    alphabet_json = json.dumps(_BASE91_ALPHABET)
    compression_json = json.dumps(compression)
    metadata_json = json.dumps(
        metadata or _kit_metadata(None), sort_keys=True, separators=(",", ":")
    )
    script = (
        "(function(){"
        f"globalThis.{_KIT_CHUNK_ARRAY}=globalThis.{_KIT_CHUNK_ARRAY}||[];"
        f"const f={compression_json};"
        "const m=t=>{if(document.body)document.body.textContent=t;else document.write(t)};"
        "addEventListener('load',async()=>{"
        f"const n={chunk_count};const k=globalThis.{_KIT_CHUNK_ARRAY};"
        "if(!Array.isArray(k)||k.length!==n){"
        "m(`Missing chunks ${Array.isArray(k)?k.length:0}/${n}`);return}"
        "for(let i=0;i<n;i++){"
        "if(typeof k[i]!=='string'){m(`Missing chunk ${i+1}/${n}`);return}}"
        "const p=k.join('');"
        "if(!('DecompressionStream'in window)){"
        "m('Browser lacks '+f+' support');return}"
        f"const a={alphabet_json};"
        "const d=t=>{let b=0,n=0,v=-1,o=[];"
        "for(let i=0;i<t.length;i++){const c=a.indexOf(t[i]);if(c===-1)continue;"
        "if(v<0){v=c;continue}v+=c*91;b|=v<<n;n+=(v&8191)>88?13:14;while(n>7){o.push(b&255);b>>=8;n-=8}v=-1}"
        "if(v>=0)o.push((b|v<<n)&255);return new Uint8Array(o)};"
        "const b=d(p);const ds=new DecompressionStream(f);"
        "const s=new Blob([b]).stream().pipeThrough(ds);let t=await new Response(s).text();"
        f"const q={json.dumps(metadata_json)};"
        "const x='<script>globalThis.__ETHERNITY_KIT_METADATA__='+q+'<\\/script>';"
        "t=t.replace(/<head([^>]*)>/i,'<head$1>'+x);"
        "document.open();document.write(t);document.close()"
        "});})();"
    )
    return (
        '<!doctype html><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>Ethernity Recovery Kit</title>'
        f"<script>{script}</script>"
    ).encode("ascii")


def _build_kit_qr_payloads(
    bundle_bytes: bytes,
    chunk_size: int,
    config: QrConfig,
    *,
    embedded_metadata: dict[str, object] | None = None,
    loader_metadata_extractor: Callable[[bytes], KitBundleLoaderMetadata] | None = None,
    payload_splitter: Callable[[str, int], list[bytes]] | None = None,
    shell_builder: Callable[..., bytes] | None = None,
    payload_fits: Callable[[bytes, QrConfig], bool] | None = None,
) -> list[bytes]:
    extract_metadata = loader_metadata_extractor or _extract_kit_bundle_loader_metadata
    split_payload = payload_splitter or _split_kit_payload_chunks
    build_shell = shell_builder or _kit_shell_payload
    fits_payload = payload_fits or fits_qr_payload
    loader_metadata = extract_metadata(bundle_bytes)
    payload_chunks = split_payload(loader_metadata.payload, chunk_size)
    shell = build_shell(
        chunk_count=len(payload_chunks),
        compression=loader_metadata.compression,
        metadata=embedded_metadata,
    )
    if not fits_payload(shell, config):
        raise ValueError(
            "QR settings cannot encode the recovery kit shell QR. "
            "Increase QR version / lower error level. "
            "--qr-chunk-size only affects payload QRs after the first shell QR."
        )
    for payload_chunk in payload_chunks:
        if not fits_payload(payload_chunk, config):
            raise ValueError(
                "chunk_size is too large for the current QR settings; "
                "lower --qr-chunk-size or increase the QR version / error level."
            )
    return [shell, *payload_chunks]


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
    "KitAnchor",
    "KitBundleLoaderMetadata",
    "KitResult",
    "SCANNER_KIT_BUNDLE_NAME",
    "render_kit_qr_document",
    "validate_chain_bound_kit_carrier",
]
