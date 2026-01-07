#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import files
from pathlib import Path

from ...config import load_app_config
from ...config.installer import PACKAGE_ROOT
from ...render import RenderInputs, render_frames_to_pdf
from ..ui import _status
from ...encoding.framing import Frame, FrameType, VERSION
from ...qr.codec import QrConfig, make_qr

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
    chunk_size: int | None,
    quiet: bool,
) -> KitResult:
    config = load_app_config(config_path, paper_size=paper_size)
    bundle_bytes = _load_kit_bundle(bundle_path)
    doc_id = hashlib.blake2b(bundle_bytes, digest_size=16).digest()
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

    context: dict[str, object] = {}

    output = Path(output_path) if output_path else Path(DEFAULT_KIT_OUTPUT)
    inputs = RenderInputs(
        frames=frames,
        template_path=config.kit_template_path,
        output_path=output,
        context=context,
        qr_config=qr_config,
        qr_payloads=chunks,
        render_fallback=False,
    )

    with _status("Rendering recovery kit QR document...", quiet=quiet):
        render_frames_to_pdf(inputs)

    return KitResult(
        output_path=output,
        chunk_count=len(chunks),
        chunk_size=chunk_size,
        bytes_total=len(bundle_bytes),
        doc_id_hex=doc_id.hex(),
    )


def _load_kit_bundle(bundle_path: str | Path | None) -> bytes:
    if bundle_path:
        return Path(bundle_path).read_bytes()
    try:
        print(files("ethernity.kit").joinpath(DEFAULT_KIT_BUNDLE_NAME))
        return files("ethernity.kit").joinpath(DEFAULT_KIT_BUNDLE_NAME).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError):
        candidate = PACKAGE_ROOT.parent / "kit" / "dist" / DEFAULT_KIT_BUNDLE_NAME
        if candidate.exists():
            return candidate.read_bytes()
        raise FileNotFoundError(
            f"{DEFAULT_KIT_BUNDLE_NAME} not found; build the kit or pass --bundle."
        )


def _split_bytes(data: bytes, chunk_size: int) -> list[bytes]:
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]


def _validate_qr_payload_bytes(size: int, data: bytes, config: QrConfig) -> None:
    if size <= 0:
        raise ValueError("chunk_size must be positive")
    if not _fits_qr_payload(data[:size], config):
        raise ValueError(
            "chunk_size is too large for the current QR settings; "
            "lower --chunk-size or increase the QR version / error level."
        )


def _max_qr_payload_bytes(data: bytes, config: QrConfig) -> int:
    upper = _MAX_QR_PROBE_BYTES
    while upper > 1 and not _fits_qr_payload(data[:upper], config):
        upper //= 2
    if upper <= 1 and not _fits_qr_payload(data[:1], config):
        raise ValueError("QR settings cannot encode any payload bytes")
    lower = 1
    while lower < upper:
        mid = (lower + upper + 1) // 2
        if _fits_qr_payload(data[:mid], config):
            lower = mid
        else:
            upper = mid - 1
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
    except Exception:
        return False
    return True
