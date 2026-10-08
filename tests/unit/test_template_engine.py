from __future__ import annotations

import json
import re
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfReader

from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.page_sizes import PaperSize
from ethernity.render import render_frames_to_pdf
from ethernity.render.backend_dispatch import plan_document_summary
from ethernity.render.checks import extract_pdf_text
from ethernity.render.design_style import load_design_style, load_page_template
from ethernity.render.designs import list_design_definitions
from ethernity.render.direct_pdf import engine, fallback_layout
from ethernity.render.direct_pdf.artwork import Artwork
from ethernity.render.direct_pdf.artwork_recovery import fallback_plans
from ethernity.render.direct_pdf.components import TextBoxPlan
from ethernity.render.direct_pdf.document import build_document_surface
from ethernity.render.direct_pdf.engine import plan_document
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.template import Template
from ethernity.render.types import DocumentOrigin, FallbackSection, RenderInputs
from ethernity.render.validation import validate_rendered_pdf_document

pytestmark = pytest.mark.usefixtures("reuse_qr_images")

DESIGNS = tuple(list_design_definitions())
ROUTES = tuple(
    (design.name, kind)
    for design in list_design_definitions().values()
    for kind in sorted(design.documents)
)
SIZES = (
    PaperSize("A4", "A4", 210, 297),
    PaperSize("LETTER", "Letter", 215.9, 279.4),
    PaperSize("MINIMUM", "Minimum", 210, 279.4),
    PaperSize("CUSTOM", "Custom", 260, 360),
    PaperSize("A5", "A5", 148, 210),
)


def inputs_for(
    tmp_path: Path,
    design: str,
    kind: str,
    *,
    size: PaperSize = SIZES[0],
    payload_size: int = 400,
    phrase: str = "alpha bravo charlie",
) -> RenderInputs:
    shard = kind in ("shard", "signing_key_shard")
    frame = Frame(
        VERSION,
        FrameType.KEY_DOCUMENT if shard else FrameType.MAIN_DOCUMENT,
        b"\x88" * 8,
        0,
        1,
        b"s" * payload_size,
    )
    return RenderInputs(
        frames=() if kind == "kit_index" else (frame,),
        output_path=tmp_path / "document.pdf",
        design_name=design,
        doc_type=kind,
        page_size=size,
        origin=DocumentOrigin(kind="root_backup"),
        context={
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
            "doc_id": "88" * 8,
            "shard_index": 1,
            "shard_total": 3,
            "shard_threshold": 2,
        },
        render_qr=kind in ("main", "kit", "shard", "signing_key_shard"),
        render_fallback=kind == "recovery" or shard,
        recovery_meta=build_recovery_meta(
            passphrase=phrase, quorum_threshold=2, quorum_shares=3, signing_pub=b"\x31" * 32
        )
        if kind == "recovery"
        else None,
        fallback_sections=(FallbackSection("SHARD PAYLOAD" if shard else "MAIN FRAME", frame),)
        if kind == "recovery" or shard
        else (),
    )


@pytest.mark.parametrize("design,kind", ROUTES)
@pytest.mark.parametrize("size", SIZES, ids=lambda size: size.name)
def test_every_template_document_and_geometry_preserves_content(tmp_path, design, kind, size):
    inputs = inputs_for(tmp_path, design, kind, size=size)
    result = render_frames_to_pdf(inputs)
    validate_rendered_pdf_document(
        inputs=inputs, result=result, document_label=f"{design}/{kind}/{size.name}"
    )
    assert plan_document_summary(inputs) == result.document_summary


@pytest.mark.parametrize("design", DESIGNS)
@pytest.mark.parametrize("kind", ("shard", "signing_key_shard"))
@pytest.mark.parametrize("size", (*SIZES[:3], SIZES[-1]), ids=lambda size: size.name)
def test_maximum_shard_is_one_page_with_one_decodable_qr(tmp_path, design, kind, size):
    inputs = inputs_for(tmp_path, design, kind, size=size, payload_size=2048)
    result = render_frames_to_pdf(inputs)
    assert result.document_summary.page_count == 1
    assert result.document_summary.physical_qr_count == 1
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="maximum sheet")


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


def test_add_template_without_registering_code(tmp_path):
    directory = tmp_path / "new-template"
    shutil.copytree(list_design_definitions()["forge"].directory, directory)
    definition = json.loads((directory / "design.json").read_text())
    definition["name"] = "new-template"
    (directory / "design.json").write_text(json.dumps(definition))
    style = json.loads((directory / "style.json").read_text())
    style["name"] = "new-template"
    for text_style in style["template"]["styles"].values():
        text_style["color"] = "#642486"
    (directory / "style.json").write_text(json.dumps(style))
    for kind in definition["documents"]:
        inputs = inputs_for(tmp_path, str(directory), kind)
        result = render_frames_to_pdf(inputs)
        validate_rendered_pdf_document(inputs=inputs, result=result, document_label="new template")


@pytest.mark.parametrize("size", (SIZES[0], SIZES[-1]), ids=lambda size: size.name)
def test_kit_keeps_every_qr_in_reading_order_and_includes_instructions(tmp_path, size):
    inputs = inputs_for(tmp_path, "forge", "kit", size=size)
    frames = tuple(replace(inputs.frames[0], index=i, total=19) for i in range(19))
    inputs = replace(inputs, frames=frames, qr_payloads=tuple(f"kit-{i:02d}" for i in range(19)))
    result = render_frames_to_pdf(inputs)
    assert result.document_summary.physical_qr_payload_indexes == tuple(range(19))
    validate_rendered_pdf_document(
        inputs=inputs,
        result=result,
        document_label="kit",
        expected_text=("HOW TO REBUILD THE RECOVERY KIT", "TROUBLESHOOTING"),
    )


@pytest.mark.parametrize("size", (SIZES[0], SIZES[-1]), ids=lambda size: size.name)
def test_inventory_wraps_long_rows_and_paginates_without_loss(tmp_path, size):
    inputs = inputs_for(tmp_path, "forge", "kit_index", size=size)
    rows = [{"component_id": f"ROW-{i:04d}", "detail": "Long description " * 12} for i in range(30)]
    inputs = replace(inputs, context={**inputs.context, "inventory_rows": rows})
    result = render_frames_to_pdf(inputs)
    assert result.document_summary.page_count > 1
    validate_rendered_pdf_document(
        inputs=inputs,
        result=result,
        document_label="inventory",
        expected_text=(*(row["component_id"] for row in rows), "Long description"),
    )


@pytest.mark.parametrize(
    "change",
    (
        {"page": {"margin_mm": float("nan")}},
        {"main": {"columns": 0}},
        {"palette": {"paper": "blue"}},
        {"typography": {"mono_pt": 2}},
        {"page": {"header": "forge"}},
        {"unknown": True},
    ),
)
def test_invalid_templates_fail_before_drawing(change):
    with pytest.raises(ValueError):
        Template.model_validate(change)


def test_impossible_inventory_row_fails_instead_of_looping(tmp_path):
    inputs = inputs_for(tmp_path, "forge", "kit_index")
    inputs = replace(
        inputs,
        context={
            **inputs.context,
            "inventory_rows": [
                {"component_id": "too-tall", "detail": "word " * 5000},
            ],
        },
    )
    with pytest.raises(ValueError, match="inventory row cannot fit"):
        plan_document(build_document_surface(inputs), inputs)


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


def test_templates_contain_no_python_implementation():
    for definition in list_design_definitions().values():
        assert not tuple(definition.directory.rglob("*.py"))
        assert load_design_style(definition.directory).template


def test_output_with_explicit_timestamp_is_deterministic(tmp_path):
    inputs = inputs_for(tmp_path, "forge", "shard")
    render_frames_to_pdf(inputs)
    first = inputs.output_path.read_bytes()
    render_frames_to_pdf(inputs)
    assert inputs.output_path.read_bytes() == first
