"""Preserve PDF raster colors, alpha, and ownership after native buffers close."""

from contextlib import closing

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
import pytest
from fpdf import FPDF
from PIL import Image

from ethernity.render.pdf_appearance import _render_page


@pytest.mark.parametrize("transparent", (False, True), ids=("rgb", "rgba"))
def test_raster_pixels_match_reference_and_outlive_native_buffers(tmp_path, transparent):
    path = tmp_path / "colors.pdf"
    pdf = FPDF(format=(51, 47))
    pdf.add_page()
    for x, color in ((5, (240, 32, 16)), (20, (16, 32, 240))):
        pdf.set_fill_color(*color)
        pdf.rect(x, 5, 10, 10, style="F")
    with Image.new("RGBA", (8, 8), (32, 128, 240, 85)) as translucent:
        pdf.image(translucent, x=5, y=20, w=25, h=10)
    pdf.set_font("Helvetica", size=12)
    pdf.text(5, 40, "Thin ink _ 0123")
    pdf.output(path)

    with pdfium.PdfDocument(path) as document, closing(document[0]) as page:
        # The original BGR conversion is an independent reference for every pixel,
        # including translucent paint and antialiased glyph edges at print resolution.
        with closing(
            page.render(
                scale=300 / 72,
                fill_color=(0, 0, 0, 0) if transparent else (255, 255, 255, 255),
            )
        ) as bitmap:
            reference = bitmap.to_pil().convert("RGBA" if transparent else "RGB")
        actual = _render_page(page, transparent=transparent)

    with reference, actual:
        assert actual.mode == reference.mode == ("RGBA" if transparent else "RGB")
        assert actual.size == reference.size
        # Allocate and overwrite another native bitmap after both PDF and raster
        # handles close. Returned pixels must remain independently owned by PIL.
        with closing(
            pdfium.PdfBitmap.new_native(
                *actual.size,
                format=pdfium_raw.FPDFBitmap_BGRA if transparent else pdfium_raw.FPDFBitmap_BGR,
                rev_byteorder=True,
            )
        ) as reused:
            reused.fill_rect((0, 255, 0, 255), 0, 0, *actual.size)
            assert actual.tobytes() == reference.tobytes()
        scale = 300 / 25.4
        assert actual.getpixel((round(10 * scale), round(10 * scale)))[:3] == (240, 32, 16)
        assert actual.getpixel((round(25 * scale), round(10 * scale)))[:3] == (16, 32, 240)
        if transparent:
            with actual.getchannel("A") as alpha:
                assert alpha.getextrema() == (0, 255)
                assert any(alpha.histogram()[1:255]), "partial opacity must survive the copy"
        else:
            assert actual.getpixel((0, 0)) == (255, 255, 255)
