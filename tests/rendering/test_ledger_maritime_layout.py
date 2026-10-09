"""Shared layout corrections retain each design's artwork and recoverable content."""

from dataclasses import replace
from itertools import pairwise

import pytest
from pypdf import PdfReader
from scripts.render_visual_baselines import VisualBaselineCase, build_sample_inputs

from ethernity.formats.extension_mode import UpdateMode
from ethernity.page_sizes import resolve_paper_size
from ethernity.render import render_frames_to_pdf
from ethernity.render.design_style import load_page_template
from ethernity.render.types import DocumentOrigin
from ethernity.render.validation import validate_rendered_pdf_document

pytestmark = pytest.mark.usefixtures("reuse_qr_images")

DESIGNS = ("ledger", "maritime")
PAPERS = ("A4", "LETTER", "A5")


@pytest.fixture(scope="module", params=[(d, p) for d in DESIGNS for p in PAPERS])
def documents(request, tmp_path_factory):
    design, paper = request.param
    folder = tmp_path_factory.mktemp(f"{design}-{paper}")
    rendered = {}
    for kind in ("main", "recovery", "shard", "signing_key_shard", "kit"):
        inputs = build_sample_inputs(
            VisualBaselineCase(design, kind, paper), folder / f"{kind}.pdf"
        )
        result = render_frames_to_pdf(inputs)
        validate_rendered_pdf_document(inputs=inputs, result=result, document_label=kind)
        texts = [page.extract_text() or "" for page in PdfReader(inputs.output_path).pages]
        rendered[kind] = result, texts
    return design, paper, rendered


def images(page):
    return [c.rect for c in page.components if c.component_type == "image"]


def test_qr_pages_keep_large_sequential_slots_and_first_page_instructions(documents):
    _, paper, rendered = documents
    columns, rows = (2, 2) if paper == "A5" else (3, 4)
    for kind in ("main", "kit"):
        result, texts = rendered[kind]
        qr_pages = [page for page in result.layout_report.pages if images(page)]
        first = images(qr_pages[0])
        assert len(first) == columns * rows
        assert len({round(r.x_mm, 3) for r in first}) == columns
        assert len({round(r.y_mm, 3) for r in first}) == rows
        minimum = 59 if paper == "A5" else 49
        assert min(r.width_mm for r in first) >= minimum
        for page in qr_pages[1:]:
            actual = images(page)
            assert len(actual) <= len(first)
            # Continuation headers are shorter; retain every column and row offset.
            for slot, original in zip(actual, first, strict=False):
                assert slot.x_mm == pytest.approx(original.x_mm)
                assert slot.y_mm - actual[0].y_mm == pytest.approx(original.y_mm - first[0].y_mm)
        if kind == "main":
            assert "Scan every QR code" in texts[0]
            assert "Recovery Document's text fallback" in texts[0]
            assert all("Scan every QR code" not in text for text in texts[1:])


def test_shards_share_layout_identity_cards_and_centered_qrs(documents):
    design, paper, rendered = documents
    template = load_page_template(design, resolve_paper_size(paper))
    assert template.document("shard") is template.document("signing_key_shard")
    for kind in ("shard", "signing_key_shard"):
        result, texts = rendered[kind]
        assert len(texts) == 1
        assert texts[0].count("PAGE 1 / 1") == 1
        assert "1 / 3" in texts[0]
        assert "Shard 1 of 3" not in texts[0]
        assert "Signing key shard 1 of 3" not in texts[0]
        assert "MANUAL FALLBACK" not in texts[0]
        assert "RAW TEXT FALLBACK" not in texts[0]
        page = result.layout_report.pages[0]
        fallback = next(
            c.rect for c in page.components if c.component_id.endswith("fallback-0-panel")
        )
        assert "SHARD PAYLOAD" in texts[0]
        if paper != "A5":
            instruction_card = next(
                c.rect
                for c in page.components
                if c.component_type == "panel" and "instructions" in c.component_id
            )
            qr = next(c.rect for c in page.components if c.component_id.endswith("-qr-0-frame"))
            assert qr.y_mm - instruction_card.bottom_mm == pytest.approx(
                fallback.y_mm - qr.bottom_mm
            )


def test_recovery_cards_are_separated_and_numbering_continues(documents):
    _, paper, rendered = documents
    result, texts = rendered["recovery"]
    assert "Keep it separate from the main document." in texts[0]
    assert all("Keep it separate from the main document." not in t for t in texts[1:])
    assert all(text.upper().count("PAGE ") == 1 for text in texts)
    number = total = 0
    for page, text in zip(result.layout_report.pages, texts, strict=True):
        for line in text.splitlines():
            if line.strip() in ("AUTH FRAME", "MAIN FRAME"):
                number = 0
            label, separator, _ = line.partition(". ")
            if separator and label.strip().isdigit():
                number += 1
                total += 1
                assert int(label) == number
        cards = [
            c.rect
            for c in page.components
            if "fallback-section" in c.component_id and c.component_type == "panel"
        ]
        assert cards
        assert all(b.y_mm - a.bottom_mm >= 4 for a, b in pairwise(cards))
        body = [
            c
            for c in page.components
            if "-fallback-" in c.component_id and c.component_type == "text"
        ]
        for c in body:
            assert c.font_size_pt >= 8
            assert any(
                card.x_mm < c.rect.x_mm
                and card.y_mm <= c.rect.y_mm
                and card.right_mm >= c.rect.right_mm
                and card.bottom_mm >= c.rect.bottom_mm
                for card in cards
            )
    assert total == result.document_summary.fallback_summary.emitted_line_count
    if paper == "A5":
        assert (
            len(
                [
                    c
                    for c in result.layout_report.pages[0].components
                    if "-meta-box-" in c.component_id
                ]
            )
            == 2
        )
    else:
        for page in result.layout_report.pages[1:]:
            identity = next(c.rect for c in page.components if c.component_id.endswith("-id"))
            created = next(c.rect for c in page.components if c.component_id.endswith("-created"))
            assert created.y_mm == pytest.approx(identity.y_mm)
            assert 0 < created.x_mm - identity.right_mm < 6


def test_kit_has_no_backup_metadata_and_every_document_uses_the_footer(documents):
    _, _, rendered = documents
    result, texts = rendered["kit"]
    assert all("8888888888888888" not in t and "CREATED" not in t.upper() for t in texts)
    assert all("Standalone offline HTML bundle" not in text for text in texts)
    assert "REBUILD THE RECOVERY KIT" in texts[-1]
    first = result.layout_report.pages[0]
    title = next(c.rect for c in first.components if c.component_id.endswith("-title"))
    divider = next(c.rect for c in first.components if c.component_id.endswith("-divider"))
    assert 0 < divider.y_mm - title.bottom_mm < 4
    assert 0 < min(r.y_mm for r in images(first)) - divider.bottom_mm < 10
    continuation = images(result.layout_report.pages[1])
    assert continuation == images(first)[: len(continuation)]
    assert all(
        not any("instructions" in c.component_id for c in page.components)
        for page in result.layout_report.pages
        if images(page)
    )
    for result, _ in rendered.values():
        for page in result.layout_report.pages:
            assert len([c for c in page.components if c.component_id.endswith("-footer-page")]) == 1
            assert (
                len(
                    [
                        c
                        for c in page.components
                        if c.component_id.endswith(("-footer-left", "-footer-kind"))
                    ]
                )
                == 1
            )


@pytest.mark.parametrize("design", DESIGNS)
@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("mode", (UpdateMode.CUMULATIVE, UpdateMode.INCREMENTAL))
def test_update_identity_and_dependencies_survive_compact_instructions(
    tmp_path, design, paper, mode
):
    inputs = build_sample_inputs(VisualBaselineCase(design, "main", paper), tmp_path / "update.pdf")
    inputs = replace(
        inputs,
        origin=DocumentOrigin(
            kind="extension", extension_index=2, update_mode=mode, root_doc_id="11" * 8
        ),
    )
    result = render_frames_to_pdf(inputs)
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="Update")
    text = PdfReader(inputs.output_path).pages[0].extract_text()
    assert "UPDATE 02" in text.upper()
    assert "original" in text.lower()
    assert (
        "every update through this one" in text.lower()
        if mode == UpdateMode.INCREMENTAL
        else "earlier updates are not required" in text.lower()
    )


@pytest.mark.parametrize("design", DESIGNS)
def test_dense_serif_sheet_heading_has_its_own_height(tmp_path, design):
    inputs = build_sample_inputs(VisualBaselineCase(design, "shard", "A5"), tmp_path / "dense.pdf")
    frame = replace(inputs.frames[0], data=b"s" * 2048)
    inputs = replace(
        inputs,
        frames=(frame,),
        fallback_sections=(replace(inputs.fallback_sections[0], frame=frame),),
    )
    result = render_frames_to_pdf(inputs)
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="Dense serif shard")
    assert result.document_summary.page_count == 1
    page = result.layout_report.pages[0]
    title = next(c for c in page.components if c.component_id.endswith("fallback-0-title-0-title"))
    row = next(c for c in page.components if c.component_id.endswith("fallback-1-row-0-line"))
    assert title.rect.height_mm == pytest.approx(2.5)
    assert title.rect.bottom_mm <= row.rect.y_mm + 1e-6
