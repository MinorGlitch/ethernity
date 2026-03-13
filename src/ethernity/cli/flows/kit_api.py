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

from pathlib import Path

from ..events import emit_artifact, emit_phase, emit_progress, emit_result
from ..ndjson import SCHEMA_VERSION, emit_started
from .kit import render_kit_qr_document


def _artifact_details(path: str) -> dict[str, object]:
    path_obj = Path(path)
    details: dict[str, object] = {"filename": path_obj.name}
    if path_obj.exists():
        details["size"] = path_obj.stat().st_size
    return details


def run_kit_api_command(
    *,
    bundle: Path | None,
    output: Path | None,
    config_value: str | None,
    paper_value: str | None,
    design_value: str | None,
    variant_value: str,
    qr_chunk_size: int | None,
) -> int:
    emit_started(
        command="kit",
        schema_version=SCHEMA_VERSION,
        args={
            "bundle": bundle,
            "output": output,
            "config": config_value,
            "paper": paper_value,
            "design": design_value,
            "variant": variant_value,
            "qr_chunk_size": qr_chunk_size,
        },
    )
    emit_phase(phase="plan", label="Resolving recovery kit configuration")
    emit_progress(phase="plan", current=1, total=1, unit="step")
    emit_phase(phase="render", label="Rendering recovery kit QR document")
    result = render_kit_qr_document(
        bundle_path=bundle,
        output_path=output,
        config_path=config_value,
        paper_size=paper_value,
        design=design_value,
        variant=variant_value,
        chunk_size=qr_chunk_size,
        quiet=True,
    )
    emit_progress(
        phase="render",
        current=1,
        total=1,
        unit="document",
        details={"chunk_count": result.chunk_count, "chunk_size": result.chunk_size},
    )
    emit_artifact(
        kind="recovery_kit_qr_document",
        path=str(result.output_path),
        details=_artifact_details(str(result.output_path)),
    )
    emit_result(
        command="kit",
        output_path=str(result.output_path),
        variant=variant_value,
        chunk_count=result.chunk_count,
        chunk_size=result.chunk_size,
        bytes_total=result.bytes_total,
        doc_id=result.doc_id_hex,
    )
    return 0


__all__ = ["run_kit_api_command"]
