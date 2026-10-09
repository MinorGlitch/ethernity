"""Archive keeps QR positions stable and shares its header across paper sizes."""

from dataclasses import replace
from itertools import pairwise

import pytest
from pypdf import PdfReader
from scripts.render_visual_baselines import VisualBaselineCase, build_sample_inputs

from ethernity.formats.extension_mode import UpdateMode
from ethernity.page_sizes import resolve_paper_size
from ethernity.render import render_frames_to_pdf
from ethernity.render.backend_dispatch import plan_document_summary
from ethernity.render.design_style import load_page_template
from ethernity.render.types import DocumentOrigin, FallbackSection
from ethernity.render.validation import validate_rendered_pdf_document

pytestmark = pytest.mark.usefixtures("reuse_qr_images")


def qr_rects(page):
    return [c.rect for c in page.components if c.component_type == "image"]


def assert_instructions_above_divider(page):
    instructions = next(c for c in page.components if c.component_id.endswith("-instructions"))
    divider = next(c for c in page.components if c.component_id.endswith(("-qr-rule", "-divider")))
    assert instructions.rect.bottom_mm < divider.rect.y_mm


@pytest.mark.parametrize(
    "paper,capacity,columns,min_qr_mm",
    (
        ("A4", 12, 3, 53),
        ("LETTER", 12, 3, 49),
        ("A5", 4, 2, 60),
    ),
)
@pytest.mark.parametrize("kind", ("main", "kit"))
def test_archive_partial_pages_keep_full_grid_positions(
    tmp_path, paper, capacity, columns, min_qr_mm, kind
):
    inputs = build_sample_inputs(
        VisualBaselineCase("archive", kind, paper), tmp_path / "document.pdf"
    )
    count = capacity * 2 + columns + 1
    frames = tuple(replace(inputs.frames[0], index=i, total=count) for i in range(count))
    inputs = replace(inputs, frames=frames, qr_payloads=tuple(f"code-{i}" for i in range(count)))
    result = render_frames_to_pdf(inputs)
    assert plan_document_summary(inputs) == result.document_summary
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="Archive grid")
    first, full, partial = [qr_rects(page) for page in result.layout_report.pages[:3]]
    assert len(first) == len(full) == capacity
    assert partial == full[: columns + 1]
    assert len({round(rect.x_mm, 3) for rect in first}) == columns
    assert len({round(rect.y_mm, 3) for rect in first}) == capacity // columns
    assert all(rect.width_mm >= min_qr_mm - 0.01 for rect in (*first, *full, *partial))

    short = replace(
        inputs,
        output_path=tmp_path / "short.pdf",
        frames=frames[:2],
        qr_payloads=inputs.qr_payloads[:2],
    )
    short_result = render_frames_to_pdf(short)
    assert qr_rects(short_result.layout_report.pages[0]) == first[:2]
    if kind == "main":
        assert_instructions_above_divider(result.layout_report.pages[0])
        pages = [(p.extract_text() or "") for p in PdfReader(inputs.output_path).pages]
        assert "Scan every QR code" in pages[0]
        assert "Recovery Document's text fallback" in pages[0]
        assert all("Scan every QR code" not in text for text in pages[1:])


@pytest.mark.parametrize("kind", ("main", "recovery", "shard", "signing_key_shard", "kit"))
def test_archive_a5_metadata_and_shared_footer(tmp_path, kind):
    inputs = build_sample_inputs(VisualBaselineCase("archive", kind, "A5"), tmp_path / "doc.pdf")
    result = render_frames_to_pdf(inputs)
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="Archive A5")
    for page in result.layout_report.pages:
        metadata = [
            c
            for c in page.components
            if "-identity-" in c.component_id and c.component_id.endswith("meta-value-2")
        ]
        if kind == "kit":
            assert not metadata
        else:
            assert len(metadata) == 1
            assert metadata[0].rect.x_mm > 100
            assert metadata[0].rect.bottom_mm < 28
        footer = {
            name: next(c for c in page.components if c.component_id.endswith(f"-footer-{name}"))
            for name in ("rule", "dot", "left", "page")
        }
        assert footer["rule"].rect.x_mm == footer["dot"].rect.x_mm == 10
        assert footer["rule"].rect.right_mm == 138
        assert footer["dot"].component_type == "ellipse"
        assert footer["left"].font_size_pt == 6.1
        assert footer["left"].text_lines[0].text.startswith("ETHERNITY")
        assert footer["page"].font_size_pt == 6
        assert footer["page"].text_lines[0].text.startswith("PAGE ")
        assert footer["page"].text_lines[0].color == (107, 114, 128)
    for page in PdfReader(inputs.output_path).pages:
        assert (page.extract_text() or "").count("2026-07-06 12:00 UTC") == (kind != "kit")


@pytest.mark.parametrize("paper", ("A4", "LETTER", "A5"))
def test_archive_kit_keeps_instructions_on_the_final_page(tmp_path, paper):
    inputs = build_sample_inputs(VisualBaselineCase("archive", "kit", paper), tmp_path / "kit.pdf")
    result = render_frames_to_pdf(inputs)
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="Archive kit")
    texts = [page.extract_text() or "" for page in PdfReader(inputs.output_path).pages]
    for text in texts:
        assert "Standalone offline HTML bundle" not in text
        assert "DOC ID" not in text
        assert "DOCUMENT ID" not in text
        assert "CREATED" not in text
        assert "8888888888888888" not in text
        assert text.count("PAGE ") == 1
    for page in result.layout_report.pages:
        assert not any("meta-" in c.component_id for c in page.components)
        if paper == "A5" or qr_rects(page):
            assert any(c.component_id.endswith("-footer-dot") for c in page.components)
    first = result.layout_report.pages[0]
    title = next(c for c in first.components if c.component_id.endswith("-title"))
    divider = next(c for c in first.components if c.component_id.endswith("-divider"))
    assert 0 < divider.rect.y_mm - title.rect.bottom_mm <= 4
    assert 0 < min(q.y_mm for q in qr_rects(first)) - divider.rect.bottom_mm <= 10
    continuation = qr_rects(result.layout_report.pages[1])
    assert continuation == qr_rects(first)[: len(continuation)]
    assert all(
        not any("instructions" in c.component_id for c in page.components)
        for page in result.layout_report.pages
        if qr_rects(page)
    )
    guide = texts[-1]
    assert "REBUILD THE RECOVERY KIT" in guide
    if paper == "A5":
        assert "IF IT DOES NOT OPEN" in guide
        assert "1. SCAN AND SAVE" in guide
        assert "2. OPEN AND RECOVER" in guide
    else:
        assert "TROUBLESHOOTING" in guide
        assert "SCAN + ASSEMBLE" in guide
        assert "OPEN THE KIT" in guide


@pytest.mark.parametrize("paper,min_qr_mm", (("A4", 60), ("LETTER", 56), ("A5", 50)))
@pytest.mark.parametrize("kind", ("shard", "signing_key_shard"))
@pytest.mark.parametrize("payload_size", (256, 1024))
def test_archive_sheets_use_the_available_qr_area(tmp_path, paper, min_qr_mm, kind, payload_size):
    inputs = build_sample_inputs(VisualBaselineCase("archive", kind, paper), tmp_path / "doc.pdf")
    frame = replace(inputs.frames[0], data=b"s" * payload_size)
    inputs = replace(
        inputs, frames=(frame,), fallback_sections=(FallbackSection("SHARD PAYLOAD", frame),)
    )
    result = render_frames_to_pdf(inputs)
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="Archive sheet")
    assert len(result.layout_report.pages) == 1
    qr = qr_rects(result.layout_report.pages[0])
    assert len(qr) == 1
    assert qr[0].width_mm >= min_qr_mm
    text = PdfReader(inputs.output_path).pages[0].extract_text() or ""
    assert "Shard 1 of 3" not in text
    assert "Signing key shard 1 of 3" not in text
    assert "RAW TEXT FALLBACK" not in text
    assert "MANUAL FALLBACK" not in text
    assert "SHARD PAYLOAD" in text
    assert "This shard alone cannot recover" in text
    components = result.layout_report.pages[0].components
    fallback = next(c.rect for c in components if c.component_id.endswith("fallback-0-panel"))
    contents = [
        c for c in components if "-fallback-" in c.component_id and c.component_type == "text"
    ]
    assert contents
    for content in contents:
        assert content.rect.x_mm - fallback.x_mm >= 2.8
        assert fallback.y_mm < content.rect.y_mm
        assert content.rect.right_mm < fallback.right_mm
        assert content.rect.bottom_mm < fallback.bottom_mm
    assert any(c.text_lines[0].text == "SHARD PAYLOAD" for c in contents)
    assert all(
        c.text_lines[0].text.split(". ", 1)[0].isdigit()
        for c in contents
        if c.text_lines[0].text != "SHARD PAYLOAD"
    )
    if paper == "A5":
        assert text.count("PAGE 1 / 1") == 1
        assert "SHARD" in text
        assert "1 / 3" in text
    else:
        instructions = next(
            c.rect
            for c in components
            if c.component_type == "panel" and "instructions" in c.component_id
        )
        frame = next(c.rect for c in components if c.component_id.endswith("qr-0-0-frame"))
        assert frame.y_mm - instructions.bottom_mm == pytest.approx(fallback.y_mm - frame.bottom_mm)
        assert qr[0].y_mm + qr[0].height_mm / 2 == pytest.approx(
            (instructions.bottom_mm + fallback.y_mm) / 2
        )


@pytest.mark.parametrize("paper", ("A4", "LETTER", "A5"))
@pytest.mark.parametrize("mode", (UpdateMode.CUMULATIVE, UpdateMode.INCREMENTAL))
def test_archive_short_instructions_keep_update_dependencies(tmp_path, paper, mode):
    inputs = build_sample_inputs(VisualBaselineCase("archive", "main", paper), tmp_path / "doc.pdf")
    inputs = replace(
        inputs,
        origin=DocumentOrigin(
            kind="extension",
            extension_index=2,
            update_mode=mode,
            root_doc_id="11" * 8,
        ),
    )
    result = render_frames_to_pdf(inputs)
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="Archive update")
    assert_instructions_above_divider(result.layout_report.pages[0])
    text = " ".join((PdfReader(inputs.output_path).pages[0].extract_text() or "").split())
    expected = (
        "Keep the original backup and this update; earlier updates are not required."
        if mode is UpdateMode.CUMULATIVE
        else "Keep the original backup and every update through this one."
    )
    assert expected in text
    assert "Scan every QR code" in text
    assert "Recovery Document's text fallback" in text


@pytest.mark.parametrize("paper", ("A4", "LETTER", "A5"))
def test_archive_recovery_reclaims_space_and_preserves_numbered_content(tmp_path, paper):
    inputs = build_sample_inputs(
        VisualBaselineCase("archive", "recovery", paper), tmp_path / "recovery.pdf"
    )
    result = render_frames_to_pdf(inputs)
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="Archive recovery")
    texts = [p.extract_text() or "" for p in PdfReader(inputs.output_path).pages]
    assert len(texts) >= 2
    assert "Keep it separate from the main document." in texts[0]
    assert all("Keep it separate from the main document." not in t for t in texts[1:])
    assert all("FALLBACK BLOCKS" not in t and "SECURITY INSTRUCTIONS" not in t for t in texts)
    assert all("Verified by:" not in t for t in texts)
    assert all(text.upper().count("PAGE ") == 1 for text in texts)

    number = 0
    total = 0
    for page, text in zip(result.layout_report.pages, texts, strict=True):
        for line in text.splitlines():
            if line.strip() in {"AUTH FRAME", "MAIN FRAME"}:
                number = 0
            label, separator, _ = line.partition(". ")
            if separator and label.strip().isdigit():
                number += 1
                total += 1
                assert int(label) == number
        cards = [c for c in page.components if "fallback-section" in c.component_id]
        body = [
            c
            for c in page.components
            if "-fallback-" in c.component_id and c.component_type == "text"
        ]
        assert cards
        assert all(
            current.rect.y_mm - previous.rect.bottom_mm >= 4
            for previous, current in pairwise(cards)
        )
        for component in body:
            assert component.font_size_pt >= 7.5
            assert any(
                card.rect.x_mm <= component.rect.x_mm
                and card.rect.y_mm <= component.rect.y_mm
                and card.rect.right_mm >= component.rect.right_mm
                and card.rect.bottom_mm >= component.rect.bottom_mm
                for card in cards
            )

    assert total == result.document_summary.fallback_summary.emitted_line_count

    if paper != "A5":
        phrase = next(
            c
            for c in result.layout_report.pages[0].components
            if c.text_metadata and c.text_metadata.role == "recovery_passphrase"
        )
        assert len(phrase.text_lines) <= 4
        assert phrase.rect.bottom_mm < 42
        for page in result.layout_report.pages[1:]:
            identity = next(c.rect for c in page.components if c.component_id.endswith("-id"))
            created = next(c.rect for c in page.components if c.component_id.endswith("-created"))
            assert created.y_mm == pytest.approx(identity.y_mm)
            assert 0 < created.x_mm - identity.right_mm < 6

    if paper == "A5":
        first = result.layout_report.pages[0]
        cards = [c for c in first.components if "-meta-box-" in c.component_id]
        fields = [c for c in first.components if c.text_metadata is not None]
        assert len(cards) == len(fields) == 2
        assert all(card.rect.y_mm > 40 for card in cards)
        for field in fields:
            assert any(
                card.rect.x_mm < field.rect.x_mm
                and card.rect.y_mm < field.rect.y_mm
                and card.rect.right_mm > field.rect.right_mm
                and card.rect.bottom_mm >= field.rect.bottom_mm
                for card in cards
            )


@pytest.mark.parametrize("paper", ("A4", "LETTER", "A5"))
def test_archive_shard_types_share_the_document_layout(paper):
    template = load_page_template("archive", resolve_paper_size(paper))
    assert template.document("signing_key_shard") is template.document("shard")


@pytest.mark.parametrize("paper", ("A4", "LETTER", "A5"))
def test_archive_instruction_cards_keep_consistent_text_insets(tmp_path, paper):
    kinds = (
        ("main", "recovery")
        if paper == "A5"
        else ("main", "recovery", "shard", "signing_key_shard")
    )
    insets = []
    for kind in kinds:
        inputs = build_sample_inputs(
            VisualBaselineCase("archive", kind, paper), tmp_path / f"{kind}.pdf"
        )
        result = render_frames_to_pdf(inputs)
        page = result.layout_report.pages[0]
        card = next(
            c
            for c in page.components
            if c.component_type == "panel" and "instructions" in c.component_id
        )
        body = next(
            c
            for c in page.components
            if c.component_id.endswith(("-instructions", "-instruction-line-0"))
        )
        insets.append(
            (
                body.rect.x_mm - card.rect.x_mm,
                body.rect.y_mm - card.rect.y_mm,
                body.font_size_pt,
            )
        )
        assert body.rect.bottom_mm <= card.rect.bottom_mm
        assert body.rect.right_mm <= card.rect.right_mm
    for actual in insets[1:]:
        assert actual == pytest.approx(insets[0])
