"""Layout-debug JSON support for direct PDF page plans."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import DirectPdfPagePlan
from ethernity.render.types import (
    RenderComponentLayoutProof,
    RenderInputs,
    RenderLayoutProof,
    RenderPageLayoutProof,
    RenderRectProof,
    RenderSeparationConstraintProof,
)


def write_direct_layout_debug_json(
    *,
    inputs: RenderInputs,
    page_plans: Sequence[DirectPdfPagePlan],
    style_name: str,
    layout_proof: RenderLayoutProof | None = None,
) -> None:
    """Write a direct-renderer layout sidecar when requested by render inputs."""

    debug_path = inputs.layout_debug_json_path
    if debug_path is None:
        return

    resolved = Path(debug_path).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    proof = layout_proof or build_direct_layout_proof(page_plans)
    payload = {
        "backend": proof.backend,
        "doc_type": inputs.doc_type,
        "design_name": inputs.design_name,
        "layout_first": True,
        "style_name": style_name,
        "output_path": str(inputs.output_path),
        "page_count": proof.page_count,
        "pages": [_page_payload(page) for page in proof.pages],
    }
    resolved.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _page_payload(page: RenderPageLayoutProof) -> dict[str, object]:
    qr_count = sum(
        1
        for component in page.components
        if component.component_type == "image" and _looks_like_qr_component(component.component_id)
    )
    return {
        "page_num": page.page_number,
        "rect": _rect_payload(page.rect),
        "qr_count": qr_count,
        "component_count": len(page.component_ids),
        "component_ids": page.component_ids,
        "overflow": page.overflow,
        "overflow_component_ids": page.overflow_component_ids,
        "out_of_bounds_component_ids": page.out_of_bounds_component_ids,
        "separation_constraints": [
            _separation_constraint_payload(constraint) for constraint in page.separation_constraints
        ],
        "components": [_component_payload(component) for component in page.components],
    }


def _looks_like_qr_component(component_id: str) -> bool:
    lowered = component_id.lower()
    return "qr" in lowered and ("image" in lowered or lowered.endswith("-qr"))


def _component_payload(component: RenderComponentLayoutProof) -> dict[str, object]:
    payload: dict[str, object] = {
        "component_id": component.component_id,
        "rect": _rect_payload(component.rect),
        "overflow": component.overflow,
    }
    if component.used_rect is not None:
        payload["used_rect"] = _rect_payload(component.used_rect)
    for field_name in (
        "component_type",
        "policy",
        "line_count",
        "overflow_line_count",
        "font_size_pt",
    ):
        value = getattr(component, field_name)
        if value is not None:
            payload[field_name] = value
    return payload


def _separation_constraint_payload(
    constraint: RenderSeparationConstraintProof,
) -> dict[str, object]:
    return {
        "constraint_id": constraint.constraint_id,
        "first_region_id": constraint.first_region_id,
        "second_region_id": constraint.second_region_id,
        "minimum_clearance_mm": constraint.minimum_clearance_mm,
        "measured_clearance_mm": constraint.measured_clearance_mm,
        "checked_pair_count": constraint.checked_pair_count,
        "satisfied": constraint.satisfied,
    }


def _rect_payload(rect: RenderRectProof) -> dict[str, float]:
    return {
        "x_mm": rect.x_mm,
        "y_mm": rect.y_mm,
        "width_mm": rect.width_mm,
        "height_mm": rect.height_mm,
        "right_mm": rect.right_mm,
        "bottom_mm": rect.bottom_mm,
    }


__all__ = ["write_direct_layout_debug_json"]
