"""Direct PDF renderer registry dispatch.

This boundary keeps the public `render_frames_to_pdf(inputs)` contract stable and prevents
direct-PDF support checks from spreading through caller code.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from ethernity.page_sizes import PaperSize
from ethernity.render.designs import load_design_manifest_by_name
from ethernity.render.direct_pdf.archive import (
    render_archive_kit_direct_pdf,
    render_archive_main_direct_pdf,
    render_archive_recovery_direct_pdf,
    render_archive_shard_direct_pdf,
    render_archive_signing_key_shard_direct_pdf,
)
from ethernity.render.direct_pdf.forge.kit import (
    render_forge_kit_direct_pdf,
    render_forge_kit_index_direct_pdf,
)
from ethernity.render.direct_pdf.forge.main import render_forge_main_direct_pdf
from ethernity.render.direct_pdf.forge.recovery import render_forge_recovery_direct_pdf
from ethernity.render.direct_pdf.forge.shard import render_forge_shard_direct_pdf
from ethernity.render.direct_pdf.forge.signing_key_shard import (
    render_forge_signing_key_shard_direct_pdf,
)
from ethernity.render.direct_pdf.ledger import (
    render_ledger_kit_direct_pdf,
    render_ledger_main_direct_pdf,
    render_ledger_recovery_direct_pdf,
    render_ledger_shard_direct_pdf,
    render_ledger_signing_key_shard_direct_pdf,
)
from ethernity.render.direct_pdf.maritime import (
    render_maritime_kit_direct_pdf,
    render_maritime_main_direct_pdf,
    render_maritime_recovery_direct_pdf,
    render_maritime_shard_direct_pdf,
    render_maritime_signing_key_shard_direct_pdf,
)
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.sentinel.kit import render_sentinel_kit_direct_pdf
from ethernity.render.direct_pdf.sentinel.kit_index import render_sentinel_kit_index_direct_pdf
from ethernity.render.direct_pdf.sentinel.main import render_sentinel_main_direct_pdf
from ethernity.render.direct_pdf.sentinel.recovery import render_sentinel_recovery_direct_pdf
from ethernity.render.direct_pdf.sentinel.shard import render_sentinel_shard_direct_pdf
from ethernity.render.direct_pdf.sentinel.signing_key_shard import (
    render_sentinel_signing_key_shard_direct_pdf,
)
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.types import RenderInputs, RenderResult

_DIRECT_DOC_TYPES: Final = frozenset(
    {
        DOC_TYPE_KIT,
        DOC_TYPE_KIT_INDEX,
        DOC_TYPE_MAIN,
        DOC_TYPE_RECOVERY,
        DOC_TYPE_SHARD,
        DOC_TYPE_SIGNING_KEY_SHARD,
    }
)

DirectPdfRenderer = Callable[[RenderInputs], RenderResult]


@dataclass(frozen=True)
class DirectPdfDesignRenderer:
    """Renderer registry entry for one direct-PDF design family."""

    style_name: str
    renderers: Mapping[str, DirectPdfRenderer]

    def renderer_for(self, doc_type: str) -> DirectPdfRenderer | None:
        """Return the renderer for a normalized document type."""

        return self.renderers.get(doc_type)


DIRECT_PDF_DESIGN_REGISTRY: Final[Mapping[str, DirectPdfDesignRenderer]] = {
    "archive": DirectPdfDesignRenderer(
        style_name="archive",
        renderers={
            DOC_TYPE_KIT: render_archive_kit_direct_pdf,
            DOC_TYPE_MAIN: render_archive_main_direct_pdf,
            DOC_TYPE_RECOVERY: render_archive_recovery_direct_pdf,
            DOC_TYPE_SHARD: render_archive_shard_direct_pdf,
            DOC_TYPE_SIGNING_KEY_SHARD: render_archive_signing_key_shard_direct_pdf,
        },
    ),
    "forge": DirectPdfDesignRenderer(
        style_name="forge",
        renderers={
            DOC_TYPE_KIT: render_forge_kit_direct_pdf,
            DOC_TYPE_KIT_INDEX: render_forge_kit_index_direct_pdf,
            DOC_TYPE_MAIN: render_forge_main_direct_pdf,
            DOC_TYPE_RECOVERY: render_forge_recovery_direct_pdf,
            DOC_TYPE_SHARD: render_forge_shard_direct_pdf,
            DOC_TYPE_SIGNING_KEY_SHARD: render_forge_signing_key_shard_direct_pdf,
        },
    ),
    "ledger": DirectPdfDesignRenderer(
        style_name="ledger",
        renderers={
            DOC_TYPE_KIT: render_ledger_kit_direct_pdf,
            DOC_TYPE_MAIN: render_ledger_main_direct_pdf,
            DOC_TYPE_RECOVERY: render_ledger_recovery_direct_pdf,
            DOC_TYPE_SHARD: render_ledger_shard_direct_pdf,
            DOC_TYPE_SIGNING_KEY_SHARD: render_ledger_signing_key_shard_direct_pdf,
        },
    ),
    "maritime": DirectPdfDesignRenderer(
        style_name="maritime",
        renderers={
            DOC_TYPE_KIT: render_maritime_kit_direct_pdf,
            DOC_TYPE_MAIN: render_maritime_main_direct_pdf,
            DOC_TYPE_RECOVERY: render_maritime_recovery_direct_pdf,
            DOC_TYPE_SHARD: render_maritime_shard_direct_pdf,
            DOC_TYPE_SIGNING_KEY_SHARD: render_maritime_signing_key_shard_direct_pdf,
        },
    ),
    "sentinel": DirectPdfDesignRenderer(
        style_name="sentinel",
        renderers={
            DOC_TYPE_KIT: render_sentinel_kit_direct_pdf,
            DOC_TYPE_KIT_INDEX: render_sentinel_kit_index_direct_pdf,
            DOC_TYPE_MAIN: render_sentinel_main_direct_pdf,
            DOC_TYPE_RECOVERY: render_sentinel_recovery_direct_pdf,
            DOC_TYPE_SHARD: render_sentinel_shard_direct_pdf,
            DOC_TYPE_SIGNING_KEY_SHARD: render_sentinel_signing_key_shard_direct_pdf,
        },
    ),
}


def render_frames_to_pdf(inputs: RenderInputs) -> RenderResult:
    """Render frames through the registered direct-PDF renderer for these inputs."""

    if not inputs.frames and (inputs.render_qr or inputs.render_fallback):
        raise ValueError("frames cannot be empty when QR or fallback rendering is enabled")

    renderer = _selected_direct_renderer(inputs)
    if renderer is not None:
        return renderer(inputs)
    raise ValueError(
        "direct PDF renderer does not support "
        f"doc_type={inputs.doc_type!r}, design_name={inputs.design_name!r}"
    )


def _selected_direct_renderer(inputs: RenderInputs) -> DirectPdfRenderer | None:
    normalized_doc_type = _normalized_doc_type(inputs)
    if not _input_shape_allows_direct(inputs, normalized_doc_type):
        return None
    design_name = inputs.design_name.strip().lower()
    manifest = load_design_manifest_by_name(design_name)
    if not manifest.supports_doc_type(normalized_doc_type):
        return None
    design = DIRECT_PDF_DESIGN_REGISTRY.get(manifest.name)
    if design is None:
        return None
    renderer = design.renderer_for(normalized_doc_type)
    if renderer is None:
        return None
    geometry = resolve_page_geometry(inputs)
    manifest.require_page_size(
        normalized_doc_type,
        PaperSize(
            name=geometry.paper_size,
            display_name=geometry.paper_size,
            width_mm=geometry.width_mm,
            height_mm=geometry.height_mm,
        ),
    )
    return renderer


def _normalized_doc_type(inputs: RenderInputs) -> str:
    return inputs.doc_type.strip().lower()


def _input_shape_allows_direct(inputs: RenderInputs, normalized_doc_type: str) -> bool:
    if normalized_doc_type not in _DIRECT_DOC_TYPES:
        return False
    if normalized_doc_type == DOC_TYPE_MAIN and (not inputs.render_qr or inputs.render_fallback):
        return False
    if normalized_doc_type == DOC_TYPE_KIT and (not inputs.render_qr or inputs.render_fallback):
        return False
    if normalized_doc_type == DOC_TYPE_KIT_INDEX and (inputs.render_qr or inputs.render_fallback):
        return False
    if normalized_doc_type == DOC_TYPE_RECOVERY and (
        inputs.render_qr or not inputs.render_fallback
    ):
        return False
    if normalized_doc_type == DOC_TYPE_SHARD and (
        not inputs.render_qr or not inputs.render_fallback or len(inputs.frames) != 1
    ):
        return False
    if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD and (
        not inputs.render_qr or not inputs.render_fallback or len(inputs.frames) != 1
    ):
        return False
    return True


__all__ = [
    "DIRECT_PDF_DESIGN_REGISTRY",
    "DirectPdfDesignRenderer",
    "render_frames_to_pdf",
]
