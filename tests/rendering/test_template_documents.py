"""Template documents preserve their printed content and geometry."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace

import pytest

from ethernity.render.backend_dispatch import plan_document_summary, render_frames_to_pdf
from ethernity.render.design_style import load_design_style
from ethernity.render.designs import list_design_definitions
from ethernity.render.direct_pdf.document import build_document_surface
from ethernity.render.direct_pdf.engine import plan_document
from ethernity.render.template import Template
from ethernity.render.validation import validate_rendered_pdf_document
from tests.support.template_samples import SIZES, inputs_for

pytestmark = pytest.mark.usefixtures("reuse_qr_images")

ROUTES = tuple(
    (design.name, kind)
    for design in list_design_definitions().values()
    for kind in sorted(design.documents)
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
