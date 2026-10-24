"""Template shards preserve their printed content and geometry."""

from __future__ import annotations

from dataclasses import replace
from functools import cache

import pytest
from pypdf import PdfReader
from scripts import render_visual_baselines as baselines

from ethernity.core.bounds import MAX_SHARD_CBOR_BYTES
from ethernity.encoding.framing import encode_frame
from ethernity.page_sizes import PaperSize
from ethernity.qr.scan import scan_qr_payloads
from ethernity.render.backend_dispatch import render_frames_to_pdf
from ethernity.render.checks import extract_pdf_text
from ethernity.render.design_style import load_page_template
from ethernity.render.designs import list_design_definitions
from ethernity.render.direct_pdf import engine
from ethernity.render.direct_pdf.document import build_document_surface
from ethernity.render.direct_pdf.engine import plan_document
from ethernity.render.types import DocumentOrigin, FallbackSection
from ethernity.render.validation import validate_rendered_pdf_document
from tests.support.template_samples import DESIGNS, SIZES, inputs_for

pytestmark = pytest.mark.usefixtures("reuse_qr_images")


@pytest.fixture(scope="module")
def rendered_shard(tmp_path_factory):
    """Share unchanged shard PDFs within this matrix; callers only inspect them."""
    directory = tmp_path_factory.mktemp("shard-matrix")

    @cache
    def render(design, kind, size, payload_size=900):
        case = baselines.VisualBaselineCase(design, kind, size.name, size)
        path = directory / f"{design}-{kind}-{size.name}-{payload_size}.pdf"
        inputs = baselines.build_sample_inputs(case, path)
        frame = replace(inputs.frames[0], data=b"s" * payload_size)
        inputs = replace(
            inputs, frames=(frame,), fallback_sections=(FallbackSection("SHARD PAYLOAD", frame),)
        )
        return inputs, render_frames_to_pdf(inputs)

    return render


def _shard_cases():
    for design in list_design_definitions().values():
        for kind in ("shard", "signing_key_shard"):
            support = design.page_support_for(kind)
            minimum = PaperSize(
                "DECLARED_MINIMUM",
                "Declared minimum",
                support.minimum_width_mm,
                support.minimum_height_mm,
            )
            seen = set()
            for size in (*SIZES[:3], SIZES[-1], minimum):
                geometry = (size.width_mm, size.height_mm)
                if geometry not in seen:
                    seen.add(geometry)
                    yield pytest.param(
                        design.name, kind, size, id=f"{size.name}-{kind}-{design.name}"
                    )


@pytest.mark.parametrize("design,kind,size", tuple(_shard_cases()))
def test_maximum_shard_is_one_page_with_one_decodable_qr(rendered_shard, design, kind, size):
    case = baselines.VisualBaselineCase(design, kind, size.name, size)
    inputs, result = rendered_shard(design, kind, size, MAX_SHARD_CBOR_BYTES)
    frame = inputs.frames[0]
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label=case.case_id)
    assert result.fallback_summary is not None
    assert result.fallback_summary == result.document_summary.fallback_summary
    assert result.document_summary.page_count == 1
    assert result.document_summary.physical_qr_count == 1
    reader = PdfReader(inputs.output_path)
    assert len(reader.pages) == 1
    assert result.layout_report is not None
    assert not result.layout_report.overflow
    components = tuple(c for page in result.layout_report.pages for c in page.components)
    constraints = tuple(
        c for page in result.layout_report.pages for c in page.separation_constraints
    )
    assert constraints and all(c.satisfied for c in constraints)
    complete, overlaps = baselines.find_content_overlaps(components)
    assert complete and not overlaps
    sizes = [c.font_size_pt for c in components if c.font_size_pt is not None]
    assert min(sizes) >= baselines.MINIMUM_TEXT_FONT_SIZE_PT
    if baselines.requires_manual_fallback_line_numbers(case):
        numbers = [
            c.font_size_pt
            for c in components
            if c.font_size_pt is not None
            and baselines.is_manual_fallback_line_number_component(case, c.component_id)
        ]
        assert (
            numbers and min(numbers) >= baselines.MINIMUM_MANUAL_FALLBACK_LINE_NUMBER_FONT_SIZE_PT
        )
    qr_sizes = [
        min(c.rect.width_mm, c.rect.height_mm)
        for c in components
        if c.component_type == "image"
        and "qr" in c.component_id.lower()
        and "image" in c.component_id.lower()
    ]
    assert qr_sizes and min(qr_sizes) >= baselines.MINIMUM_QR_IMAGE_SIZE_MM
    expected = encode_frame(frame)
    assert scan_qr_payloads((inputs.output_path,)) == [expected]
    composited, skipped = baselines.scan_composited_pdf_qr_payloads(inputs.output_path)
    if skipped is None:
        assert composited == (expected,)
    else:
        assert skipped == "pdftoppm not found"


@pytest.mark.parametrize("design", DESIGNS)
@pytest.mark.parametrize("kind", ("shard", "signing_key_shard"))
@pytest.mark.parametrize("size", (SIZES[0], SIZES[1], SIZES[3]), ids=lambda size: size.name)
def test_shard_fallback_panel_is_full_width_and_bottom_anchored(rendered_shard, design, kind, size):
    case = baselines.VisualBaselineCase(design, kind, size.name, size)

    def fallback_container(result):
        assert result.layout_report is not None
        assert len(result.layout_report.pages) == 1
        page = result.layout_report.pages[0]
        interior = [
            c.rect.width_mm
            for c in page.components
            if c.component_type in {"panel", "rule"} and c.rect.width_mm < page.rect.width_mm - 2.0
        ]
        assert interior
        panels = [
            c.rect
            for c in page.components
            if c.component_type == "panel"
            and baselines.is_fallback_component(case, c.component_id, "panel")
        ]
        assert len(panels) == 1
        panel = panels[0]
        assert panel.width_mm >= max(interior) - 1.0
        assert panel.x_mm - page.rect.x_mm == pytest.approx(
            page.rect.right_mm - panel.right_mm, abs=1.0
        )
        assert panel.bottom_mm >= page.rect.y_mm + page.rect.height_mm * 0.8
        return panel

    _, normal = rendered_shard(design, kind, size)
    _, maximum = rendered_shard(design, kind, size, MAX_SHARD_CBOR_BYTES)
    normal_panel, maximum_panel = fallback_container(normal), fallback_container(maximum)
    assert normal_panel.x_mm == pytest.approx(maximum_panel.x_mm, abs=0.1)
    assert normal_panel.width_mm == pytest.approx(maximum_panel.width_mm, abs=0.1)
    assert normal_panel.bottom_mm == pytest.approx(maximum_panel.bottom_mm, abs=0.1)
    assert normal_panel.height_mm <= maximum_panel.height_mm


@pytest.mark.parametrize("design", DESIGNS)
@pytest.mark.parametrize("kind", ("shard", "signing_key_shard"))
@pytest.mark.parametrize("origin", ("rebuilt_backup", "replacement_recovery"))
@pytest.mark.parametrize("size", (SIZES[0], SIZES[-1]), ids=lambda size: size.name)
def test_reissued_shard_captions_fit_and_preserve_origin(tmp_path, design, kind, origin, size):
    inputs = inputs_for(tmp_path, design, kind, size=size)
    inputs = replace(inputs, origin=DocumentOrigin(kind=origin))
    result = render_frames_to_pdf(inputs)
    assert result.document_summary.page_count == 1
    validate_rendered_pdf_document(
        inputs=inputs,
        result=result,
        document_label="reissued sheet",
    )
    text = extract_pdf_text(PdfReader(inputs.output_path)).lower()
    assert ("rebuilt backup" if origin == "rebuilt_backup" else "replacement") in text
    assert "shard" in text


@pytest.mark.parametrize("index,total,threshold", ((4, 5, 3), (2, 2, 1)))
@pytest.mark.parametrize("size", (SIZES[0], SIZES[-1]), ids=lambda size: size.name)
def test_signing_sheet_instructions_and_specs_use_actual_quorum(
    tmp_path, index, total, threshold, size
):
    inputs = inputs_for(tmp_path, "forge", "signing_key_shard", size=size)
    inputs = replace(
        inputs,
        context={
            **inputs.context,
            "shard_index": index,
            "shard_total": total,
            "shard_threshold": threshold,
        },
    )
    render_frames_to_pdf(inputs)
    text = " ".join(extract_pdf_text(PdfReader(inputs.output_path)).lower().split())
    assert f"shard {index} of {total}" in text
    assert f"recovery requires {threshold}/{total} shards" in text
    assert "shard 1 of 3" not in text
    assert "threshold: 2 of 3" not in text
    if threshold == 1:
        assert "this shard alone can recover the signing key" in text
        assert "this shard alone cannot recover" not in text


@pytest.mark.parametrize("missing_qr", (False, True))
def test_sheet_qr_centering_rejects_impossible_layout(tmp_path, monkeypatch, missing_qr):
    inputs = inputs_for(tmp_path, "archive", "shard")
    template = load_page_template("archive", inputs.page_size)
    document = template.document("shard")
    if missing_qr:
        document = document.model_copy(
            update={"first": document.first.model_copy(update={"elements": ()})}
        )
        error = "requires a QR group"
    else:
        document = document.model_copy(
            update={"sheet": document.sheet.model_copy(update={"qr_area_top": 270})}
        )
        error = "does not fit above the fallback card"
    template = template.model_copy(update={"documents": {"shard": document}})
    monkeypatch.setattr(engine, "load_page_template", lambda *_: template)
    with pytest.raises(ValueError, match=error):
        plan_document(build_document_surface(inputs), inputs)
