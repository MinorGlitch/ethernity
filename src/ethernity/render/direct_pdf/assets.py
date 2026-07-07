"""Bundled asset registry for direct PDF rendering."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ethernity.config.paths import TEMPLATES_RESOURCE_ROOT
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.types import FontStyle

_SHARED_ASSET_DIR = TEMPLATES_RESOURCE_ROOT / "_shared" / "assets"

MATERIAL_SYMBOLS_FAMILY = "Material Symbols Outlined"
MATERIAL_SYMBOLS_FONT_NAME = "material-symbols-outlined.ttf"
PUBLIC_SANS_FAMILY = "Public Sans"
PUBLIC_SANS_REGULAR_FONT_NAME = "fonts/PublicSans-Regular.otf"
PUBLIC_SANS_BLACK_FONT_NAME = "fonts/PublicSans-Black.otf"
ROBOTO_MONO_FAMILY = "Roboto Mono"
ROBOTO_MONO_REGULAR_FONT_NAME = "fonts/RobotoMono-Regular.ttf"
ROBOTO_MONO_BOLD_FONT_NAME = "fonts/RobotoMono-Bold.ttf"


@dataclass(frozen=True)
class BundledFont:
    """A font file that can be registered with a PDF surface."""

    family: str
    path: Path
    style: FontStyle = ""

    def require_file(self) -> None:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)


@dataclass(frozen=True)
class DirectPdfAssets:
    """Resolved packaged assets needed by the direct PDF renderer."""

    fonts: tuple[BundledFont, ...]

    def register_fonts(self, surface: PdfSurface) -> None:
        for font in self.fonts:
            font.require_file()
            surface.register_ttf_font(font.family, font.path, style=font.style)


def packaged_direct_pdf_assets() -> DirectPdfAssets:
    """Return packaged assets currently required by direct PDF rendering."""

    return DirectPdfAssets(
        fonts=(
            BundledFont(
                family=MATERIAL_SYMBOLS_FAMILY,
                path=_SHARED_ASSET_DIR / MATERIAL_SYMBOLS_FONT_NAME,
            ),
            BundledFont(
                family=PUBLIC_SANS_FAMILY,
                path=_SHARED_ASSET_DIR / PUBLIC_SANS_REGULAR_FONT_NAME,
            ),
            BundledFont(
                family=PUBLIC_SANS_FAMILY,
                path=_SHARED_ASSET_DIR / PUBLIC_SANS_BLACK_FONT_NAME,
                style="B",
            ),
            BundledFont(
                family=ROBOTO_MONO_FAMILY,
                path=_SHARED_ASSET_DIR / ROBOTO_MONO_REGULAR_FONT_NAME,
            ),
            BundledFont(
                family=ROBOTO_MONO_FAMILY,
                path=_SHARED_ASSET_DIR / ROBOTO_MONO_BOLD_FONT_NAME,
                style="B",
            ),
        )
    )


__all__ = [
    "BundledFont",
    "DirectPdfAssets",
    "MATERIAL_SYMBOLS_FAMILY",
    "MATERIAL_SYMBOLS_FONT_NAME",
    "PUBLIC_SANS_BLACK_FONT_NAME",
    "PUBLIC_SANS_FAMILY",
    "PUBLIC_SANS_REGULAR_FONT_NAME",
    "ROBOTO_MONO_BOLD_FONT_NAME",
    "ROBOTO_MONO_FAMILY",
    "ROBOTO_MONO_REGULAR_FONT_NAME",
    "packaged_direct_pdf_assets",
]
