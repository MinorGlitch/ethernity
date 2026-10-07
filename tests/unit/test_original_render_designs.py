"""Preserve original artwork except for explicitly revised design cases."""

import json
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageChops
from scripts.render_visual_baselines import VisualBaselineCase, build_sample_inputs

from ethernity.render import render_frames_to_pdf

REFERENCE = Path(__file__).parents[1] / "fixtures" / "render" / "original-designs"
MANIFEST = json.loads((REFERENCE / "manifest.json").read_text())
REVISED = REFERENCE.parent / "revised-designs"
REVISIONS = json.loads((REVISED / "manifest.json").read_text())
CASES = {
    f"{case}-{MANIFEST['paper']}": (REFERENCE, case, page_count, MANIFEST["scale"])
    for case, page_count in MANIFEST["cases"].items()
}
CASES.update(
    {
        case: (REVISED, case, page_count, REVISIONS["scale"])
        for case, page_count in REVISIONS["cases"].items()
    }
)


@pytest.mark.parametrize("case", CASES)
def test_original_artwork_is_preserved(tmp_path, case):
    design, kind, paper = case.split("-")
    reference_root, stem, page_count, scale = CASES[case]
    inputs = build_sample_inputs(VisualBaselineCase(design, kind, paper), tmp_path / "document.pdf")
    render_frames_to_pdf(inputs)
    with pdfium.PdfDocument(str(inputs.output_path)) as pdf:
        assert len(pdf) == page_count
        for index, page in enumerate(pdf, 1):
            actual = page.render(scale=scale).to_pil().convert("RGB")
            with Image.open(reference_root / f"{stem}-{index}.webp") as reference:
                assert actual.size == reference.size
                diff = ImageChops.difference(actual, reference.convert("RGB"))
            channels = diff.split()
            changed = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
            # A component translation can round six border-edge pixels differently in PDFium.
            # This permits subpixel arithmetic noise, not a moved line, glyph, or missing element.
            changed_pixels = actual.width * actual.height - changed.histogram()[0]
            if changed_pixels > 16:
                actual.save(tmp_path / f"{case}-{index}-actual.png")
                diff.save(tmp_path / f"{case}-{index}-diff.png")
            assert changed_pixels <= 16, f"{case} page {index}: {changed_pixels} pixels changed"
