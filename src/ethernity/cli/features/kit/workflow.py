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

"""CLI compatibility adapter for the recovery-kit workflow service."""

from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path
from typing import Callable

from rich.console import Console

from ethernity.cli.shared.paths import expanduser_cli_path
from ethernity.cli.shared.ui.runtime import plain_status
from ethernity.cli.shared.ui.state import isatty
from ethernity.config import AppConfig, apply_render_style, load_app_config
from ethernity.qr.capacity import fits_qr_payload
from ethernity.qr.codec import QrConfig
from ethernity.render import render_frames_to_pdf
from ethernity.render.service import RenderService
from ethernity.render.types import RenderInputs, RenderResult
from ethernity.workflows.kit import service as kit_service

DEFAULT_KIT_BUNDLE_NAME = kit_service.DEFAULT_KIT_BUNDLE_NAME
SCANNER_KIT_BUNDLE_NAME = kit_service.SCANNER_KIT_BUNDLE_NAME
DEFAULT_KIT_OUTPUT = "recovery_kit_qr.pdf"
DEFAULT_KIT_CHUNK_SIZE = kit_service.DEFAULT_KIT_CHUNK_SIZE
_MAX_QR_PROBE_BYTES = kit_service._MAX_QR_PROBE_BYTES
_JS_IDENTIFIER_RE = kit_service._JS_IDENTIFIER_RE
_KIT_CHUNK_ARRAY = kit_service._KIT_CHUNK_ARRAY
_BASE91_ALPHABET = kit_service._BASE91_ALPHABET
_SUPPORTED_KIT_BUNDLE_COMPRESSIONS = kit_service._SUPPORTED_KIT_BUNDLE_COMPRESSIONS
_DEV_KIT_DIST_ROOT = kit_service._DEV_KIT_DIST_ROOT

KitAnchor = kit_service.KitAnchor
KitBundleLoaderMetadata = kit_service.KitBundleLoaderMetadata
KitResult = kit_service.KitResult

_CONSOLE = Console(force_terminal=isatty(sys.__stdout__, sys.stdout))


def render_kit_qr_document(
    *,
    output_path: str | Path | None,
    config_path: str | Path | None,
    paper_size: str | None,
    design: str | None,
    variant: str,
    chunk_size: int | None,
    quiet: bool,
    app_config: AppConfig | None = None,
    anchor: KitAnchor | None = None,
    render_pdf: Callable[[RenderInputs], RenderResult] | None = None,
) -> KitResult:
    """Preserve the established CLI signature and status behavior."""

    normalized_variant = _normalize_kit_variant(variant)
    config = app_config or load_app_config(config_path, paper_size=paper_size)
    if app_config is None:
        config = apply_render_style(config, design)
    output = Path(expanduser_cli_path(output_path, preserve_stdin=False) or DEFAULT_KIT_OUTPUT)
    selected_renderer = render_pdf or render_frames_to_pdf

    def _render_with_status(inputs: RenderInputs) -> RenderResult:
        with plain_status(
            "Rendering recovery kit QR document...",
            quiet=quiet,
            console=_CONSOLE,
        ):
            return selected_renderer(inputs)

    return kit_service.render_kit_qr_document(
        output_path=output,
        config=config,
        variant=normalized_variant,
        chunk_size=chunk_size,
        anchor=anchor,
        render_pdf=_render_with_status,
        bundle_loader=_load_kit_bundle,
        payload_builder=_build_kit_qr_payloads,
        capacity_resolver=_max_qr_payload_bytes,
        render_service_factory=RenderService,
    )


# Compatibility helpers below intentionally keep the old private patch points used by tests.
_normalize_kit_variant = kit_service._normalize_kit_variant
_default_kit_bundle_name = kit_service._default_kit_bundle_name
_skip_js_string = kit_service._skip_js_string
_skip_js_space = kit_service._skip_js_space
_extract_loader_string_literal = kit_service._extract_loader_string_literal
_parse_loader_string_literal = kit_service._parse_loader_string_literal
_extract_kit_bundle_loader_metadata = kit_service._extract_kit_bundle_loader_metadata
_extract_kit_bundle_loader_payload = kit_service._extract_kit_bundle_loader_payload
_kit_chunk_script = kit_service._kit_chunk_script
_split_kit_payload_chunks = kit_service._split_kit_payload_chunks
_kit_metadata = kit_service._kit_metadata
_kit_shell_payload = kit_service._kit_shell_payload


def _load_kit_bundle(*, variant: str = "lean") -> bytes:
    return kit_service._load_kit_bundle(
        variant=variant,
        resource_files=files,
        dev_dist_root=_DEV_KIT_DIST_ROOT,
    )


def _build_kit_qr_payloads(
    bundle_bytes: bytes,
    chunk_size: int,
    config: QrConfig,
    *,
    embedded_metadata: dict[str, object] | None = None,
) -> list[bytes]:
    return kit_service._build_kit_qr_payloads(
        bundle_bytes,
        chunk_size,
        config,
        embedded_metadata=embedded_metadata,
        loader_metadata_extractor=_extract_kit_bundle_loader_metadata,
        payload_splitter=_split_kit_payload_chunks,
        shell_builder=_kit_shell_payload,
        payload_fits=fits_qr_payload,
    )


def _max_qr_payload_bytes(data: bytes, config: QrConfig) -> int:
    return kit_service._max_qr_payload_bytes(
        data,
        config,
        payload_fits=fits_qr_payload,
    )


__all__ = [
    "DEFAULT_KIT_BUNDLE_NAME",
    "DEFAULT_KIT_CHUNK_SIZE",
    "DEFAULT_KIT_OUTPUT",
    "KitAnchor",
    "KitResult",
    "SCANNER_KIT_BUNDLE_NAME",
    "render_kit_qr_document",
]
