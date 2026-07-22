"""Direct PDF rendering for storage-envelope helper layouts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ethernity.render.direct_pdf.components import ImageBox, Panel
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan, build_page_plan
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
from ethernity.render.direct_pdf.types import BLACK, PdfColor, PdfRect
from ethernity.render.storage_paths import (
    DEFAULT_LOGO_PATH,
    EnvelopeKind,
    EnvelopeOrientation,
    envelope_page_size_mm,
)

_WHITE = PdfColor(255, 255, 255)
_FRAME_INSET_MM = 7.0
_FRAME_LINE_WIDTH_MM = 0.35
_FRAME_RADIUS_MM = 3.0
_LOGO_WIDTH_MM = 100.0
_LOGO_EDGE_CLEARANCE_MM = 9.0


@dataclass(frozen=True)
class EnvelopeDirectPlan:
    """Measured direct-PDF page for one storage envelope."""

    page_plan: DirectPdfPagePlan
    logo_rect: PdfRect


def render_envelope_pdf(
    output_path: str | Path,
    *,
    kind: EnvelopeKind,
    logo_path: str | Path | None = None,
    orientation: EnvelopeOrientation = "portrait",
) -> Path:
    """Render a storage-envelope helper PDF without a browser backend."""

    output_path = Path(output_path)
    page_width_mm, page_height_mm = envelope_page_size_mm(kind, orientation)
    surface = FpdfSurface(page_width_mm=page_width_mm, page_height_mm=page_height_mm)
    plan = build_envelope_direct_plan(
        surface,
        kind=kind,
        logo_path=logo_path,
        orientation=orientation,
    )
    plan.page_plan.paint(surface)
    surface.output(output_path)
    return output_path


def build_envelope_direct_plan(
    surface: PdfSurface,
    *,
    kind: EnvelopeKind,
    logo_path: str | Path | None = None,
    orientation: EnvelopeOrientation = "portrait",
) -> EnvelopeDirectPlan:
    """Build measured storage-envelope page geometry."""

    page_width_mm, page_height_mm = envelope_page_size_mm(kind, orientation)
    page_rect = PdfRect(0.0, 0.0, page_width_mm, page_height_mm)
    resolved_logo_path = _resolve_logo_path(logo_path)
    logo_image = resolved_logo_path.read_bytes()
    logo_rect = _centered_logo_rect(
        page_rect,
        natural_size_px=_image_size_px(resolved_logo_path),
    )
    plans: list[PaintPlan] = [
        Panel(
            component_id="envelope-background",
            fill=_WHITE,
        ).plan(surface, page_rect),
        Panel(
            component_id="envelope-frame",
            stroke=BLACK,
            line_width_mm=_FRAME_LINE_WIDTH_MM,
            corner_radius_mm=_FRAME_RADIUS_MM,
        ).plan(
            surface,
            PdfRect(
                _FRAME_INSET_MM,
                _FRAME_INSET_MM,
                page_width_mm - 2.0 * _FRAME_INSET_MM,
                page_height_mm - 2.0 * _FRAME_INSET_MM,
            ),
        ),
        ImageBox(
            component_id="envelope-logo",
            image=logo_image,
            image_type=_image_type_for_path(resolved_logo_path),
        ).plan(surface, logo_rect),
    ]
    page_plan = build_page_plan(page_number=1, rect=page_rect, plans=plans)
    return EnvelopeDirectPlan(page_plan=page_plan, logo_rect=logo_rect)


def _resolve_logo_path(logo_path: str | Path | None) -> Path:
    resolved = Path(logo_path) if logo_path is not None else DEFAULT_LOGO_PATH
    resolved = resolved.expanduser()
    if not resolved.is_file():
        raise FileNotFoundError(f"logo file not found: {resolved}")
    return resolved


def _image_size_px(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _centered_logo_rect(
    page_rect: PdfRect,
    *,
    natural_size_px: tuple[int, int],
) -> PdfRect:
    natural_width_px, natural_height_px = natural_size_px
    if natural_width_px <= 0 or natural_height_px <= 0:
        raise ValueError("logo image dimensions must be positive")

    natural_ratio = natural_height_px / natural_width_px
    max_width_mm = max(1.0, page_rect.width_mm - 2.0 * _LOGO_EDGE_CLEARANCE_MM)
    max_height_mm = max(1.0, page_rect.height_mm - 2.0 * _LOGO_EDGE_CLEARANCE_MM)
    width_mm = min(_LOGO_WIDTH_MM, max_width_mm)
    height_mm = width_mm * natural_ratio
    if height_mm > max_height_mm:
        height_mm = max_height_mm
        width_mm = height_mm / natural_ratio

    return PdfRect(
        page_rect.x_mm + (page_rect.width_mm - width_mm) / 2.0,
        page_rect.y_mm + (page_rect.height_mm - height_mm) / 2.0,
        width_mm,
        height_mm,
    )


def _image_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "PNG"
    if suffix in {".jpg", ".jpeg"}:
        return "JPEG"
    return ""


__all__ = [
    "EnvelopeDirectPlan",
    "build_envelope_direct_plan",
    "render_envelope_pdf",
]
