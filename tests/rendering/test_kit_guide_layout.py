"""The kit guide keeps the same usable instructions across designs and page sizes."""

import re

import pytest
from pypdf import PdfReader
from scripts.render_visual_baselines import VisualBaselineCase, build_sample_inputs

from ethernity.page_sizes import resolve_paper_size
from ethernity.render import render_frames_to_pdf
from ethernity.render.copy_catalog import build_copy_bundle, build_instruction_copy
from ethernity.render.design_style import load_page_template
from ethernity.render.validation import validate_rendered_pdf_document

pytestmark = pytest.mark.usefixtures("reuse_qr_images")


@pytest.mark.parametrize("design", ("archive", "ledger", "maritime"))
@pytest.mark.parametrize("paper", ("A4", "LETTER", "A5"))
def test_kit_guide_cards_preserve_instructions_and_contain_their_text(tmp_path, design, paper):
    inputs = build_sample_inputs(VisualBaselineCase(design, "kit", paper), tmp_path / "kit.pdf")
    result = render_frames_to_pdf(inputs)
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="kit guide")
    guide = result.layout_report.pages[-1]
    text = " ".join(PdfReader(inputs.output_path).pages[-1].extract_text().split())
    assert_guide_copy(text, design, paper)
    assert len(re.findall(r"\bPAGE \d+ / \d+\b", text.upper())) == 1
    assert "8888888888888888" not in text
    if paper != "A5":
        return
    assert_compact_cards_contain_their_text(guide)


def assert_guide_copy(text, design, paper):
    copy = build_copy_bundle(doc_type="kit", context={})
    if paper == "A5":
        for key, value in copy.items():
            if key.startswith("guide_") and isinstance(value, str):
                assert text.count(value) == 1
    else:
        for key in ("scan_steps", "open_steps", "help_steps", "verify", "storage", "security"):
            for value in copy[f"guide_{key}"]:
                assert value in text
        for index in (0, 1, 2, 3, 4, 5) if design == "archive" else (0, 2, 4, 5):
            assert copy["guide_checklist"][index] in text


@pytest.mark.parametrize("design", ("forge", "sentinel"))
@pytest.mark.parametrize("paper", ("A4", "LETTER", "A5"))
def test_kit_guide_other_designs_fit_the_same_reconstruction_steps(tmp_path, design, paper):
    inputs = build_sample_inputs(VisualBaselineCase(design, "kit", paper), tmp_path / "kit.pdf")
    result = render_frames_to_pdf(inputs)
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="kit guide")
    text = " ".join(PdfReader(inputs.output_path).pages[-1].extract_text().split())
    copy = build_copy_bundle(doc_type="kit", context={})
    if paper == "A5":
        for line in build_instruction_copy(doc_type="kit", context={}).lines:
            assert line in text
        assert copy["guide_help_parts"] in text
        return
    for key in ("scan_steps", "open_steps", "help_steps"):
        for line in copy[f"guide_{key}"]:
            assert line in text


def assert_compact_cards_contain_their_text(guide):
    panels = []
    for name in ("scan", "open", "help", "keep"):
        panel = next(
            c.rect for c in guide.components if c.component_id.endswith(f"-{name}-card-0-panel")
        )
        contents = [c for c in guide.components if f"-{name}-0-" in c.component_id]
        assert contents
        for content in contents:
            used = content.used_rect
            assert used is not None
            assert panel.x_mm < used.x_mm
            assert panel.y_mm < used.y_mm
            assert used.right_mm < panel.right_mm
            assert used.bottom_mm < panel.bottom_mm
        panels.append(panel)
    for index, panel in enumerate(panels):
        for other in panels[index + 1 :]:
            assert (
                panel.right_mm <= other.x_mm
                or other.right_mm <= panel.x_mm
                or panel.bottom_mm <= other.y_mm
                or other.bottom_mm <= panel.y_mm
            )
    footer = next(c.rect for c in guide.components if c.component_id.endswith("-footer-rule"))
    assert max(p.bottom_mm for p in panels) + 2 < footer.y_mm


def test_kit_guide_content_components_are_shared_across_designs_and_sizes():
    templates = [
        load_page_template(design, resolve_paper_size(paper))
        for design in ("archive", "ledger", "maritime")
        for paper in ("A4", "LETTER", "A5")
    ]
    for name in ("intro", "scan", "open", "help", "keep"):
        components = [template.components[f"kit-guide-{name}"] for template in templates]
        assert all(component == components[0] for component in components)
