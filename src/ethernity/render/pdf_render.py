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

"""Direct PDF entry point for framed render documents."""

from __future__ import annotations

from dataclasses import replace

from ethernity.render.backend_dispatch import render_with_direct_backend
from ethernity.render.doc_types import DOC_TYPE_MAIN
from ethernity.render.spec import DocumentSpec
from ethernity.render.template_style import TemplateCapabilities
from ethernity.render.types import RenderInputs, RenderResult


def render_frames_to_pdf(inputs: RenderInputs) -> RenderResult:
    """Render frames to a PDF through the direct PDF backend."""

    if not inputs.frames and (inputs.render_qr or inputs.render_fallback):
        raise ValueError("frames cannot be empty when QR or fallback rendering is enabled")

    return render_with_direct_backend(inputs)


def _uses_uniform_main_qr_capacity(
    *,
    doc_type: str,
    capabilities: TemplateCapabilities,
) -> bool:
    """Return whether main-document pages should use uniform QR capacity."""

    return doc_type.strip().lower() == DOC_TYPE_MAIN and capabilities.uniform_main_qr_capacity


def _apply_main_qr_grid_overrides(
    *,
    spec: DocumentSpec,
    doc_type: str,
    capabilities: TemplateCapabilities,
) -> DocumentSpec:
    """Apply main QR grid capability overrides to a document spec."""

    normalized_doc_type = doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_MAIN:
        return spec

    qr_grid = spec.qr_grid
    changed = False
    if capabilities.main_qr_grid_size_mm is not None:
        qr_grid = replace(qr_grid, qr_size_mm=float(capabilities.main_qr_grid_size_mm))
        changed = True
    if capabilities.main_qr_grid_max_cols is not None:
        qr_grid = replace(qr_grid, max_cols=int(capabilities.main_qr_grid_max_cols))
        changed = True
    if not changed:
        return spec
    return replace(spec, qr_grid=qr_grid)


__all__ = ["render_frames_to_pdf"]
