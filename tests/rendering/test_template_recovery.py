"""Recovery text wraps and paginates without losing words or fallback data."""

from __future__ import annotations

import re

import pytest
from pypdf import PdfReader

from ethernity.render.backend_dispatch import render_frames_to_pdf
from ethernity.render.design_style import load_page_template
from ethernity.render.direct_pdf import fallback_layout
from ethernity.render.direct_pdf.artwork import Artwork
from ethernity.render.direct_pdf.artwork_recovery import fallback_plans
from ethernity.render.direct_pdf.components import TextBoxPlan
from ethernity.render.direct_pdf.document import build_document_surface
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.validation import validate_rendered_pdf_document
from tests.support.template_samples import DESIGNS, SIZES, inputs_for

pytestmark = pytest.mark.usefixtures("reuse_qr_images")


@pytest.mark.parametrize("design", DESIGNS)
@pytest.mark.parametrize("size", (SIZES[1], SIZES[-1]), ids=lambda size: size.name)
@pytest.mark.parametrize(
    "phrase",
    (
        " ".join(f"word{index}" for index in range(24)),
        '  leading spaces\tquotes " and unicode \u00e9\n' * 40,
        "x" * 1500,
    ),
)
def test_passphrase_wrapping_and_continuations_are_lossless(tmp_path, design, phrase, size):
    inputs = inputs_for(tmp_path, design, "recovery", phrase=phrase, size=size)
    result = render_frames_to_pdf(inputs)
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="passphrase")
    if design in {"archive", "ledger", "maritime"}:
        for page in PdfReader(inputs.output_path).pages:
            assert len(re.findall(r"\bPAGE \d+ / \d+\b", page.extract_text().upper())) == 1


@pytest.mark.parametrize("design", DESIGNS)
@pytest.mark.parametrize("size", (SIZES[0], SIZES[-1]), ids=lambda size: size.name)
def test_large_fallback_has_no_missing_or_repeated_data(tmp_path, design, size):
    inputs = inputs_for(tmp_path, design, "recovery", payload_size=16000, size=size)
    result = render_frames_to_pdf(inputs)
    assert result.document_summary.page_count > 1
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="large fallback")


@pytest.mark.parametrize("design", DESIGNS)
@pytest.mark.parametrize("size", (SIZES[0], SIZES[-1]), ids=lambda size: size.name)
def test_five_digit_fallback_number_fits_without_overlapping_payload(tmp_path, design, size):
    inputs = inputs_for(tmp_path, design, "recovery", size=size)
    template = load_page_template(design, size)
    painter = Artwork(
        build_document_surface(inputs), template, PdfRect(0, 0, size.width_mm, size.height_mm)
    )
    row = fallback_layout.FallbackPageEntry(
        fallback_layout.FallbackLineEntry(0, 50000, "ybnd rfgh jkmn"), 0, 50000
    )
    page = fallback_layout.FallbackPage(2, (row,))
    recovery = template.document("recovery").recovery
    assert recovery is not None
    for profile in (recovery.first, recovery.continuation):
        plans = fallback_plans(painter, profile, page)
        texts = [p for p in plans if isinstance(p, TextBoxPlan)]
        assert any(p.lines[0].text.startswith("50000.") for p in texts)
        assert all(not p.layout.overflow for p in texts)
        if not profile.inline_number:
            number = next(p for p in texts if p.lines[0].text == "50000.")
            payload = next(p for p in texts if p.lines[0].text == "ybnd rfgh jkmn")
            assert number.rect.right_mm < payload.rect.x_mm
