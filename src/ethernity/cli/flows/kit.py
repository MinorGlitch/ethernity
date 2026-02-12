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
    doc_id = hashlib.blake2b(bundle_bytes, digest_size=DOC_ID_LEN).digest()
    qr_config = config.qr_config

    if chunk_size is None:
        max_size = _max_qr_payload_bytes(bundle_bytes, qr_config)
        chunk_size = min(DEFAULT_KIT_CHUNK_SIZE, max_size)
    else:
        _validate_qr_payload_bytes(chunk_size, bundle_bytes, qr_config)

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    chunks = _split_bytes(bundle_bytes, chunk_size)
    frames = [
        Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=index,
            total=len(chunks),
            data=b"",
        )
        for index in range(len(chunks))
    ]

    output = Path(output_path) if output_path else Path(DEFAULT_KIT_OUTPUT)
    render_service = RenderService(config)
    inputs = render_service.kit_inputs(
        frames,
        output,
        qr_payloads=chunks,
        context=render_service.base_context(),
    )

    with status("Rendering recovery kit QR document...", quiet=quiet):
        render_frames_to_pdf(inputs)

    return KitResult(
        output_path=output,
        chunk_count=len(chunks),
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
