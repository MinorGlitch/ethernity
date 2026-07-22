"""Portrait paper geometry for direct PDF renderers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping

from ethernity.page_sizes import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    DEFAULT_PAPER_SIZE_NAME,
    LETTER_HEIGHT_MM,
    LETTER_WIDTH_MM,
    PAPER_SIZES,
    resolve_paper_size,
)
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.types import RenderInputs

PAPER_DIMENSIONS_MM: Final[Mapping[str, tuple[float, float]]] = MappingProxyType(
    {name.lower(): (paper.width_mm, paper.height_mm) for name, paper in PAPER_SIZES.items()}
)


@dataclass(frozen=True)
class PageGeometry:
    """Resolved portrait page name and dimensions."""

    paper_size: str
    width_mm: float
    height_mm: float

    def __post_init__(self) -> None:
        if not self.paper_size.strip():
            raise ValueError("paper_size must be non-empty")
        for field_name, value in (("width_mm", self.width_mm), ("height_mm", self.height_mm)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{field_name} must be finite and positive")
        if self.height_mm <= self.width_mm:
            raise ValueError("page geometry must use portrait orientation")

    @property
    def rect(self) -> PdfRect:
        return PdfRect(0.0, 0.0, self.width_mm, self.height_mm)


def normalized_paper_size(inputs: RenderInputs) -> str:
    """Return the normalized configured paper-size name."""

    if inputs.page_size is not None:
        return inputs.page_size.name.lower()
    return str(inputs.context.get("paper_size") or DEFAULT_PAPER_SIZE_NAME).strip().lower()


def registered_paper_sizes() -> frozenset[str]:
    """Return normalized names for every registered physical paper size."""

    return frozenset(PAPER_DIMENSIONS_MM)


def page_geometry(paper_size: str) -> PageGeometry:
    """Resolve one registered paper name without requiring render inputs."""

    paper = resolve_paper_size(paper_size)
    return PageGeometry(
        paper_size=paper.name,
        width_mm=paper.width_mm,
        height_mm=paper.height_mm,
    )


def resolve_page_geometry(
    inputs: RenderInputs,
    *,
    supported_paper_sizes: frozenset[str] | None = None,
) -> PageGeometry:
    """Resolve supported portrait page dimensions from render inputs."""

    paper_size = normalized_paper_size(inputs)
    supported = (
        registered_paper_sizes()
        if supported_paper_sizes is None
        else frozenset(name.strip().lower() for name in supported_paper_sizes)
    )
    if inputs.page_size is not None:
        if supported_paper_sizes is not None and paper_size not in supported:
            supported_label = ", ".join(sorted(name.upper() for name in supported))
            raise ValueError(f"direct PDF renderer supports paper sizes: {supported_label}")
        registered_dimensions = PAPER_DIMENSIONS_MM.get(paper_size)
        if registered_dimensions is not None and (
            not math.isclose(
                inputs.page_size.width_mm,
                registered_dimensions[0],
                abs_tol=0.01,
            )
            or not math.isclose(
                inputs.page_size.height_mm,
                registered_dimensions[1],
                abs_tol=0.01,
            )
        ):
            registered = page_geometry(paper_size)
            raise ValueError(
                f"typed dimensions for registered paper size {registered.paper_size} do not "
                f"match {registered.width_mm:.3f}x{registered.height_mm:.3f} mm"
            )
        return PageGeometry(
            paper_size=inputs.page_size.name,
            width_mm=inputs.page_size.width_mm,
            height_mm=inputs.page_size.height_mm,
        )

    if paper_size not in supported or paper_size not in PAPER_DIMENSIONS_MM:
        supported_label = ", ".join(sorted(name.upper() for name in supported))
        raise ValueError(f"direct PDF renderer supports paper sizes: {supported_label}")
    return page_geometry(paper_size)


__all__ = [
    "A4_HEIGHT_MM",
    "A4_WIDTH_MM",
    "LETTER_HEIGHT_MM",
    "LETTER_WIDTH_MM",
    "PAPER_DIMENSIONS_MM",
    "PageGeometry",
    "normalized_paper_size",
    "page_geometry",
    "registered_paper_sizes",
    "resolve_page_geometry",
]
