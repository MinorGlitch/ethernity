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

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from ...config import apply_template_design, load_app_config
from ...config.installer import PACKAGE_ROOT
from ...encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ...qr.codec import QrConfig, make_qr
from ...render import render_frames_to_pdf
from ...render.service import RenderService
from ..api import status

DEFAULT_KIT_BUNDLE_NAME = "recovery_kit.bundle.html"
DEFAULT_KIT_OUTPUT = "recovery_kit_qr.pdf"
DEFAULT_KIT_CHUNK_SIZE = 1200
_MAX_QR_PROBE_BYTES = 4000
_BUNDLE_PAYLOAD_RE = re.compile(r'const p=("([^"\\]|\\.)*");')
_KIT_CHUNK_ARRAY = "_k"
_BASE91_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789" '!#$%&()*+,./:;<=>?@[]^_`{|}~"'
)


@dataclass(frozen=True)
class KitResult:
    output_path: Path
    chunk_count: int
    chunk_size: int
    bytes_total: int
    doc_id_hex: str


def render_kit_qr_document(
    *,
    bundle_path: str | Path | None,
    output_path: str | Path | None,
    config_path: str | Path | None,
    paper_size: str | None,
    design: str | None,
    chunk_size: int | None,
    quiet: bool,
) -> KitResult:
    config = load_app_config(config_path, paper_size=paper_size)
    config = apply_template_design(config, design)
    bundle_bytes = _load_kit_bundle(bundle_path)
    qr_config = config.qr_config

    if chunk_size is None:
        max_size = _max_qr_payload_bytes(b"x" * _MAX_QR_PROBE_BYTES, qr_config)
        chunk_size = min(DEFAULT_KIT_CHUNK_SIZE, max_size)
    else:
        _validate_qr_payload_bytes(chunk_size, b"x" * max(chunk_size, 1), qr_config)

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    qr_payloads = _build_kit_qr_payloads(bundle_bytes, chunk_size, qr_config)
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

    output = Path(output_path) if output_path else Path(DEFAULT_KIT_OUTPUT)
    render_service = RenderService(config)
    inputs = render_service.kit_inputs(
        frames,
        output,
        qr_payloads=qr_payloads,
        context=render_service.base_context(),
    )

    with status("Rendering recovery kit QR document...", quiet=quiet):
        render_frames_to_pdf(inputs)

    return KitResult(
        output_path=output,
        chunk_count=len(qr_payloads),
        chunk_size=chunk_size,
        bytes_total=len(bundle_bytes),
        doc_id_hex=doc_id.hex(),
    )


def _load_kit_bundle(bundle_path: str | Path | None) -> bytes:
    """Load the recovery kit bundle from the specified path or default locations."""
    if bundle_path:
        path = Path(bundle_path)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ValueError(
                f"bundle file not found: {path}. Check --bundle path or omit --bundle."
            ) from exc
        except OSError as exc:
            raise ValueError(
                f"unable to read bundle file: {path}. Check --bundle path and permissions."
            ) from exc
    # Primary: load from installed package (src/ethernity/kit/)
    try:
        return files("ethernity.kit").joinpath(DEFAULT_KIT_BUNDLE_NAME).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError):
        pass
    # Fallback: development build output (kit/dist/)
    candidate = PACKAGE_ROOT.parents[2] / "kit" / "dist" / DEFAULT_KIT_BUNDLE_NAME
    if candidate.exists():
        return candidate.read_bytes()
    raise FileNotFoundError(
        "Recovery kit bundle not found. Reinstall the package or specify "
        "a custom bundle with --bundle."
    )


def _split_bytes(data: bytes, chunk_size: int) -> list[bytes]:
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]


def _extract_kit_bundle_loader_payload(bundle_bytes: bytes) -> str:
    try:
        bundle_text = bundle_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("recovery kit bundle is not valid UTF-8 HTML") from exc
    match = _BUNDLE_PAYLOAD_RE.search(bundle_text)
    if match is None:
        raise ValueError(
            "unsupported recovery kit bundle format: embedded loader payload was not found"
        )
    payload = json.loads(match.group(1))
    if not isinstance(payload, str):
        raise ValueError("unsupported recovery kit bundle format: loader payload is not a string")
    return payload


def _kit_chunk_script(chunk: str) -> bytes:
    # Prevent accidental </script> termination when a base91 chunk contains '<'.
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


def _kit_shell_payload(*, chunk_count: int) -> bytes:
    alphabet_json = json.dumps(_BASE91_ALPHABET)
    script = (
        "(function(){"
        f"globalThis.{_KIT_CHUNK_ARRAY}=globalThis.{_KIT_CHUNK_ARRAY}||[];"
        "const m=t=>{if(document.body)document.body.textContent=t;else document.write(t)};"
        "addEventListener('load',async()=>{"
        f"const n={chunk_count};const k=globalThis.{_KIT_CHUNK_ARRAY};"
        "if(!Array.isArray(k)||k.length!==n){"
        "m(`Missing chunks ${Array.isArray(k)?k.length:0}/${n}`);return}"
        "for(let i=0;i<n;i++){"
        "if(typeof k[i]!=='string'){m(`Missing chunk ${i+1}/${n}`);return}}"
        "const p=k.join('');"
        "if(!('DecompressionStream'in window)){"
        "m('Browser lacks gzip support');return}"
        f"const a={alphabet_json};"
        "const d=t=>{let b=0,n=0,v=-1,o=[];"
        "for(let i=0;i<t.length;i++){const c=a.indexOf(t[i]);if(c===-1)continue;"
        "if(v<0){v=c;continue}v+=c*91;b|=v<<n;n+=(v&8191)>88?13:14;while(n>7){o.push(b&255);b>>=8;n-=8}v=-1}"
        "if(v>=0)o.push((b|v<<n)&255);return new Uint8Array(o)};"
        "const b=d(p);const ds=new DecompressionStream('gzip');"
        "const s=new Blob([b]).stream().pipeThrough(ds);const t=await new Response(s).text();"
        "document.open();document.write(t);document.close()"
        "});})();"
    )
    return (
        '<!doctype html><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>Ethernity Recovery Kit</title>'
        f"<script>{script}</script>"
    ).encode("ascii")


def _build_kit_qr_payloads(bundle_bytes: bytes, chunk_size: int, config: QrConfig) -> list[bytes]:
    payload = _extract_kit_bundle_loader_payload(bundle_bytes)
    payload_chunks = _split_kit_payload_chunks(payload, chunk_size)
    shell = _kit_shell_payload(chunk_count=len(payload_chunks))
    if not _fits_qr_payload(shell, config):
        raise ValueError(
            "QR settings cannot encode the recovery kit shell QR. "
            "Increase QR version / lower error level. "
            "--qr-chunk-size only affects payload QRs after the first shell QR."
        )
    return [shell, *payload_chunks]


def _validate_qr_payload_bytes(size: int, data: bytes, config: QrConfig) -> None:
    if size <= 0:
        raise ValueError("chunk_size must be positive")
    if not _fits_qr_payload(data[:size], config):
        raise ValueError(
            "chunk_size is too large for the current QR settings; "
            "lower --qr-chunk-size or increase the QR version / error level."
        )


def _max_qr_payload_bytes(data: bytes, config: QrConfig) -> int:
    max_probe = max(1, min(len(data), _MAX_QR_PROBE_BYTES))
    if not _fits_qr_payload(data[:1], config):
        raise ValueError("QR settings cannot encode any payload bytes")
    if _fits_qr_payload(data[:max_probe], config):
        return max_probe
    lower = 1
    upper = max_probe
    while lower + 1 < upper:
        mid = (lower + upper) // 2
        if _fits_qr_payload(data[:mid], config):
            lower = mid
        else:
            upper = mid
    return lower


def _fits_qr_payload(payload: bytes, config: QrConfig) -> bool:
    try:
        make_qr(
            payload,
            error=config.error,
            version=config.version,
            mask=config.mask,
            micro=config.micro,
            boost_error=config.boost_error,
        )
    except (ValueError, TypeError):
        return False
    return True
