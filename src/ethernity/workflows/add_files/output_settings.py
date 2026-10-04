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

"""Resolve Add Files rendering and publication settings."""

from __future__ import annotations

from pathlib import Path

from ethernity.config import apply_render_style, load_app_config
from ethernity.crypto.signing import derive_public_key
from ethernity.render.layout_debug import (
    ensure_layout_debug_dir_allowed,
    ensure_layout_debug_dir_ready,
    resolve_layout_debug_dir,
)
from ethernity.workflows.add_files.errors import AddFilesWorkflowError
from ethernity.workflows.shared import api_codes

from .models import (
    ExtensionOutputSettings,
    PreparedAddFilesRun,
)


def resolve_add_files_output_settings(
    prepared: PreparedAddFilesRun,
    *,
    create_layout_debug_dir: bool = True,
) -> ExtensionOutputSettings:
    """Resolve render and publication settings for an authenticated extension."""

    config = apply_render_style(
        load_app_config(prepared.request.config_path, paper_size=prepared.request.paper_size),
        prepared.request.design,
    )
    sign_pub = derive_public_key(prepared.signing_seed)
    qr_chunk_size = resolve_qr_chunk_size(
        requested=prepared.request.qr_chunk_size,
        default=config.qr_chunk_size,
    )

    return ExtensionOutputSettings(
        config=config,
        qr_chunk_size=qr_chunk_size,
        qr_payload_codec=config.cli_defaults.add_files.qr_payload_codec,
        layout_debug_dir=resolve_add_files_layout_debug_dir(
            prepared.request.layout_debug_directory,
            output_dir=prepared.request.output_dir,
            create=create_layout_debug_dir,
        ),
        sign_pub=sign_pub,
    )


def resolve_add_files_layout_debug_dir(
    path: str | None,
    *,
    output_dir: str | None,
    create: bool = True,
) -> str | None:
    if path is None or not path.strip():
        return None
    debug_dir = Path(path).expanduser().resolve()
    ensure_add_files_layout_debug_dir_allowed(debug_dir, output_dir=output_dir)
    if not create:
        try:
            ensure_layout_debug_dir_ready(debug_dir)
        except ValueError as exc:
            raise AddFilesWorkflowError(
                code=api_codes.ADD_FILES_RENDER_OPTIONS_INVALID,
                message=f"--layout-debug-dir is not usable: {exc}",
                details={"layout_debug_dir": str(debug_dir)},
            ) from exc
        return str(debug_dir)
    return resolve_layout_debug_dir(str(debug_dir))


def ensure_add_files_layout_debug_dir_allowed(
    path: str | Path,
    *,
    output_dir: str | None,
) -> None:
    debug_dir = Path(path).expanduser().resolve()
    if output_dir:
        output_path = Path(output_dir).expanduser().resolve()
        try:
            ensure_layout_debug_dir_allowed(
                debug_dir,
                forbidden_dirs={"extension output directory": output_path},
            )
        except ValueError as exc:
            raise AddFilesWorkflowError(
                code=api_codes.ADD_FILES_RENDER_OPTIONS_INVALID,
                message=(
                    "--layout-debug-dir must not be inside the extension output directory; "
                    "choose a separate diagnostics directory"
                ),
                details={
                    "layout_debug_dir": str(debug_dir),
                    "output_dir": str(output_path),
                },
            ) from exc


def resolve_qr_chunk_size(requested: int | None, default: int) -> int:
    qr_chunk_size = default if requested is None else requested
    if qr_chunk_size <= 0:
        raise AddFilesWorkflowError(
            code=api_codes.ADD_FILES_RENDER_OPTIONS_INVALID,
            message="Add Files QR chunk size must be a positive integer",
        )
    return qr_chunk_size
