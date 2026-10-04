"""Select a direct-PDF document plan and execute the shared rendering lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from ethernity.page_sizes import PaperSize
from ethernity.render.designs import load_design_definition_by_name
from ethernity.render.direct_pdf import archive, document, ledger, maritime
from ethernity.render.direct_pdf.forge import (
    kit as forge_kit,
    main as forge_main,
    recovery as forge_recovery,
    shard as forge_shard,
    signing_key_shard as forge_signing_key_shard,
)
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.sentinel import (
    kit as sentinel_kit,
    kit_index as sentinel_kit_index,
    main as sentinel_main,
    recovery as sentinel_recovery,
    shard as sentinel_shard,
    signing_key_shard as sentinel_signing_key_shard,
)
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.types import RenderedDocumentSummary, RenderInputs, RenderResult


@dataclass(frozen=True)
class DirectPdfDesign:
    """Document builders and PDF metadata policy for one design family."""

    style_name: str
    builders: Mapping[str, document.DocumentPlanBuilder]
    explicit_creation_date_doc_types: frozenset[str] = frozenset()


DIRECT_PDF_DESIGN_REGISTRY: Final[Mapping[str, DirectPdfDesign]] = {
    "archive": DirectPdfDesign(
        style_name="archive",
        builders={
            DOC_TYPE_KIT: archive.build_archive_kit_direct_plan,
            DOC_TYPE_MAIN: archive.build_archive_main_direct_plan,
            DOC_TYPE_RECOVERY: archive.build_archive_recovery_direct_plan,
            DOC_TYPE_SHARD: archive.build_archive_shard_direct_plan,
            DOC_TYPE_SIGNING_KEY_SHARD: archive.build_archive_signing_key_shard_direct_plan,
        },
    ),
    "forge": DirectPdfDesign(
        style_name="forge",
        builders={
            DOC_TYPE_KIT: forge_kit.build_forge_kit_direct_plan,
            DOC_TYPE_KIT_INDEX: forge_kit.build_forge_kit_index_direct_plan,
            DOC_TYPE_MAIN: forge_main.build_forge_main_direct_plan,
            DOC_TYPE_RECOVERY: forge_recovery.build_forge_recovery_direct_plan,
            DOC_TYPE_SHARD: forge_shard.build_forge_shard_direct_plan,
            DOC_TYPE_SIGNING_KEY_SHARD: (
                forge_signing_key_shard.build_forge_signing_key_shard_direct_plan
            ),
        },
        explicit_creation_date_doc_types=frozenset({DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD}),
    ),
    "ledger": DirectPdfDesign(
        style_name="ledger",
        builders={
            DOC_TYPE_KIT: ledger.build_ledger_kit_direct_plan,
            DOC_TYPE_MAIN: ledger.build_ledger_main_direct_plan,
            DOC_TYPE_RECOVERY: ledger.build_ledger_recovery_direct_plan,
            DOC_TYPE_SHARD: ledger.build_ledger_shard_direct_plan,
            DOC_TYPE_SIGNING_KEY_SHARD: ledger.build_ledger_signing_key_shard_direct_plan,
        },
    ),
    "maritime": DirectPdfDesign(
        style_name="maritime",
        builders={
            DOC_TYPE_KIT: maritime.build_maritime_kit_direct_plan,
            DOC_TYPE_MAIN: maritime.build_maritime_main_direct_plan,
            DOC_TYPE_RECOVERY: maritime.build_maritime_recovery_direct_plan,
            DOC_TYPE_SHARD: maritime.build_maritime_shard_direct_plan,
            DOC_TYPE_SIGNING_KEY_SHARD: maritime.build_maritime_signing_key_shard_direct_plan,
        },
    ),
    "sentinel": DirectPdfDesign(
        style_name="sentinel",
        builders={
            DOC_TYPE_KIT: sentinel_kit.build_sentinel_kit_direct_plan,
            DOC_TYPE_KIT_INDEX: sentinel_kit_index.build_sentinel_kit_index_direct_plan,
            DOC_TYPE_MAIN: sentinel_main.build_sentinel_main_direct_plan,
            DOC_TYPE_RECOVERY: sentinel_recovery.build_sentinel_recovery_direct_plan,
            DOC_TYPE_SHARD: sentinel_shard.build_sentinel_shard_direct_plan,
            DOC_TYPE_SIGNING_KEY_SHARD: (
                sentinel_signing_key_shard.build_sentinel_signing_key_shard_direct_plan
            ),
        },
    ),
}


def render_frames_to_pdf(inputs: RenderInputs) -> RenderResult:
    """Render the selected document plan through the shared direct-PDF runner."""

    if not inputs.frames and (inputs.render_qr or inputs.render_fallback):
        raise ValueError("frames cannot be empty when QR or fallback rendering is enabled")
    selected = _selected_document_plan(inputs)
    if selected is None:
        raise ValueError(
            "direct PDF renderer does not support "
            f"doc_type={inputs.doc_type!r}, design_name={inputs.design_name!r}"
        )
    design, builder = selected
    creation_date = (
        document.explicit_creation_date(inputs)
        if inputs.doc_type.strip().lower() in design.explicit_creation_date_doc_types
        else None
    )
    return document.render_document_plan(
        inputs,
        style_name=design.style_name,
        builder=builder,
        creation_date=creation_date,
    )


def plan_document_summary(inputs: RenderInputs) -> RenderedDocumentSummary:
    """Measure a document through its renderer without painting or writing a PDF."""

    selected = _selected_document_plan(inputs)
    if selected is None:
        raise ValueError(
            "direct PDF renderer does not support "
            f"doc_type={inputs.doc_type!r}, design_name={inputs.design_name!r}"
        )
    _design, builder = selected
    surface = document.build_document_surface(inputs)
    return builder(surface, inputs).document_summary


def _selected_document_plan(
    inputs: RenderInputs,
) -> tuple[DirectPdfDesign, document.DocumentPlanBuilder] | None:
    doc_type = inputs.doc_type.strip().lower()
    definition = load_design_definition_by_name(inputs.design_name.strip().lower())
    if not definition.supports_doc_type(doc_type):
        return None
    design = DIRECT_PDF_DESIGN_REGISTRY.get(definition.name)
    if design is None:
        return None
    builder = design.builders.get(doc_type)
    if builder is None:
        return None
    geometry = resolve_page_geometry(inputs)
    definition.require_page_size(
        doc_type,
        PaperSize(
            name=geometry.paper_size,
            display_name=geometry.paper_size,
            width_mm=geometry.width_mm,
            height_mm=geometry.height_mm,
        ),
    )
    return design, builder


__all__ = [
    "DIRECT_PDF_DESIGN_REGISTRY",
    "DirectPdfDesign",
    "plan_document_summary",
    "render_frames_to_pdf",
]
