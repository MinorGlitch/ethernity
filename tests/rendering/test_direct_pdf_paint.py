"""Check the emitted page, including drawing operations that a blank PDF would pass."""

from pathlib import Path

import pypdfium2 as pdfium
import zxingcpp
from pypdf import PdfReader

from ethernity.qr.codec import qr_bytes
from ethernity.render.direct_pdf import components
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle

ICON_FONT = (
    Path(__file__).parents[2]
    / "src/ethernity/resources/designs/_shared/assets/material-symbols-outlined.ttf"
)


def test_painted_components_are_visible_and_qr_is_decodable(tmp_path) -> None:
    surface = FpdfSurface(page_width_mm=100, page_height_mm=100)
    surface.add_page()
    surface.register_ttf_font("Material Symbols Outlined", ICON_FONT)
    black = PdfColor(0, 0, 0)
    components.Panel(component_id="border", stroke=black, line_width_mm=1, corner_radius_mm=3).plan(
        surface, PdfRect(5, 5, 90, 90)
    ).paint(surface)
    components.Ellipse(component_id="dot", fill=PdfColor(200, 0, 0)).plan(
        surface, PdfRect(10, 10, 6, 6)
    ).paint(surface)
    components.Rule(component_id="rule", color=PdfColor(0, 0, 200)).plan(
        surface, PdfRect(25, 12, 60, 1)
    ).paint(surface)
    components.Line(component_id="line", color=black, line_width_mm=1).plan(
        surface, start_x_mm=10, start_y_mm=25, end_x_mm=20, end_y_mm=35
    ).paint(surface)
    components.TextBox(
        component_id="text",
        text="Printed text",
        style=TextStyle("Helvetica", 14),
        policy=TextFitPolicy.FAIL,
    ).plan(surface, PdfRect(30, 20, 60, 10)).paint(surface)
    components.TextBox(
        component_id="icon",
        text="hub",
        style=TextStyle("Material Symbols Outlined", 18),
        policy=TextFitPolicy.FAIL,
    ).plan(surface, PdfRect(60, 75, 30, 15)).paint(surface)
    components.ImageBox(component_id="qr", image=qr_bytes("painted-qr"), image_type="PNG").plan(
        surface, PdfRect(30, 40, 30, 30)
    ).paint(surface)
    output = tmp_path / "components.pdf"
    surface.output(output)

    reader = PdfReader(output)
    assert len(reader.pages) == 1
    assert "Printed text" in reader.pages[0].extract_text()
    with pdfium.PdfDocument(output) as document:
        # Four pixels per millimetre keeps the samples inside solid shapes, away from edges.
        bitmap = document[0].render(scale=4 * 25.4 / 72).to_pil().convert("RGB")
    assert bitmap.getpixel((5 * 4, 50 * 4)) == (0, 0, 0), "missing panel border"
    assert bitmap.getpixel((13 * 4, 13 * 4)) == (200, 0, 0), "missing ellipse"
    assert bitmap.getpixel((50 * 4, 50)) == (0, 0, 200), "missing rule"
    assert bitmap.getpixel((15 * 4, 30 * 4)) == (0, 0, 0), "missing diagonal line"
    assert bitmap.crop((30 * 4, 20 * 4, 90 * 4, 30 * 4)).getextrema()[0][0] < 100
    assert bitmap.crop((60 * 4, 75 * 4, 90 * 4, 90 * 4)).getextrema()[0][0] < 100
    assert [hit.text for hit in zxingcpp.read_barcodes(bitmap)] == ["painted-qr"]
