import unittest
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import ethernity.render.direct_pdf.sentinel.shard as sentinel_shard_module
import ethernity.render.direct_pdf.sentinel.signing_key_shard as sentinel_signing_key_shard_module
from ethernity.core.bounds import MAX_SHARD_CBOR_BYTES
from ethernity.page_sizes import PaperSize, resolve_paper_size
from ethernity.qr.codec import QrConfig
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.sentinel.common import (
    build_sentinel_page_layout,
    build_sentinel_shell_context,
    build_sentinel_surface,
)
from ethernity.render.direct_pdf.sentinel.kit import render_sentinel_kit_direct_pdf
from ethernity.render.direct_pdf.sentinel.kit_index import render_sentinel_kit_index_direct_pdf
from ethernity.render.direct_pdf.sentinel.main import render_sentinel_main_direct_pdf
from ethernity.render.direct_pdf.sentinel.recovery import render_sentinel_recovery_direct_pdf
from ethernity.render.direct_pdf.sentinel.shard import render_sentinel_shard_direct_pdf
from ethernity.render.direct_pdf.sentinel.signing_key_shard import (
    render_sentinel_signing_key_shard_direct_pdf,
)
from ethernity.render.direct_pdf.sentinel.theme import SENTINEL_THEME
from ethernity.render.proofs import validate_fallback_text_in_pdf, validate_pdf_has_pages
from ethernity.render.types import RenderInputs, RenderPageLayoutProof
from tests.unit.render.direct_pdf.sentinel.test_kit import _inputs as kit_inputs
from tests.unit.render.direct_pdf.sentinel.test_kit_index import _inputs as kit_index_inputs
from tests.unit.render.direct_pdf.sentinel.test_main import _inputs as main_inputs
from tests.unit.render.direct_pdf.sentinel.test_recovery import _inputs as recovery_inputs
from tests.unit.render.direct_pdf.sentinel.test_shard import _inputs as shard_inputs
from tests.unit.render.direct_pdf.sentinel.test_signing_key_shard import _inputs as signing_inputs

_POINT_TO_MM = 25.4 / 72.0
_MINIMUM_TEXT_FONT_SIZE_PT = 6.0
_MINIMUM_MANUAL_LINE_NUMBER_FONT_SIZE_PT = 6.5


def _with_paper(
    inputs: RenderInputs,
    paper_size: str,
    dimensions_mm: tuple[float, float] | None = None,
) -> RenderInputs:
    context = dict(inputs.context)
    context["paper_size"] = paper_size
    if dimensions_mm is None:
        return replace(inputs, context=context, page_size=resolve_paper_size(paper_size))
    width_mm, height_mm = dimensions_mm
    return replace(
        inputs,
        context=context,
        page_size=PaperSize(
            name=paper_size,
            display_name=paper_size.replace("_", " ").title(),
            width_mm=width_mm,
            height_mm=height_mm,
        ),
    )


class TestDirectPdfSentinelResponsive(unittest.TestCase):
    def test_every_document_type_renders_registered_and_custom_boundary_cases(self) -> None:
        cases = (
            (
                "main",
                lambda path: main_inputs(path, count=20),
                render_sentinel_main_direct_pdf,
                "qr-image",
                True,
            ),
            (
                "kit",
                lambda path: kit_inputs(path, count=14),
                render_sentinel_kit_direct_pdf,
                "qr-image",
                True,
            ),
            (
                "kit-index",
                lambda path: kit_index_inputs(path, row_count=7),
                render_sentinel_kit_index_direct_pdf,
                "inventory-component",
                True,
            ),
            (
                "recovery",
                lambda path: recovery_inputs(path, main_data=b"x" * 2250),
                render_sentinel_recovery_direct_pdf,
                "fallback-line-text",
                True,
            ),
            (
                "shard",
                lambda path: shard_inputs(path, data=b"x" * 900),
                render_sentinel_shard_direct_pdf,
                "fallback-line-",
                False,
            ),
            (
                "signing-key-shard",
                lambda path: signing_inputs(path, data=b"x" * 900),
                render_sentinel_signing_key_shard_direct_pdf,
                "fallback-line-",
                False,
            ),
        )
        paper_cases = (
            ("A4", None),
            ("LETTER", None),
            ("FUTURE_PORTRAIT", (200.0, 320.0)),
        )
        qr_widths_by_case: dict[tuple[str, str], tuple[float, ...]] = {}
        with TemporaryDirectory() as tmp:
            for paper_size, dimensions_mm in paper_cases:
                for name, input_factory, renderer, partial_marker, expects_multiple in cases:
                    with self.subTest(paper_size=paper_size, doc_type=name):
                        output_path = Path(tmp) / f"{name}-{paper_size.lower()}.pdf"
                        inputs = _with_paper(
                            input_factory(output_path),
                            paper_size,
                            dimensions_mm,
                        )

                        result = renderer(inputs)
                        reader = validate_pdf_has_pages(output_path)
                        geometry = resolve_page_geometry(inputs)
                        artifact_proof = result.artifact_proof
                        layout_proof = result.layout_proof
                        assert artifact_proof is not None
                        assert layout_proof is not None

                        if expects_multiple:
                            self.assertGreater(artifact_proof.page_count, 1)
                        else:
                            self.assertEqual(artifact_proof.page_count, 1)
                            self.assertEqual(artifact_proof.physical_qr_count, 1)
                        self.assertEqual(artifact_proof.page_count, len(reader.pages))
                        self.assertFalse(layout_proof.overflow)
                        self._assert_page_geometry(
                            reader.pages, geometry.width_mm, geometry.height_mm
                        )
                        self._assert_page_labels(reader.pages)
                        self._assert_readable_font_floor(layout_proof.pages)
                        self._assert_footer_constraints(layout_proof.pages)
                        qr_widths = tuple(
                            sorted(
                                {
                                    round(component.rect.width_mm, 3)
                                    for page in layout_proof.pages
                                    for component in page.components
                                    if "qr-image" in component.component_id
                                }
                            )
                        )
                        if qr_widths:
                            qr_widths_by_case[(name, paper_size)] = qr_widths
                        if expects_multiple:
                            self._assert_partial_final_page(
                                layout_proof.pages,
                                marker=partial_marker,
                            )
        for name in ("main", "kit", "shard", "signing-key-shard"):
            a4_qr_widths = qr_widths_by_case[(name, "A4")]
            for paper_size, _ in paper_cases[1:]:
                self.assertEqual(a4_qr_widths, qr_widths_by_case[(name, paper_size)])

    def test_qr_compounds_preserve_caption_and_marker_clearance_for_every_page_height(
        self,
    ) -> None:
        cases = (
            (
                "main",
                lambda path: main_inputs(path, count=20),
                render_sentinel_main_direct_pdf,
                True,
            ),
            (
                "shard",
                lambda path: shard_inputs(path, data=b"x" * 900),
                render_sentinel_shard_direct_pdf,
                False,
            ),
            (
                "signing-key-shard",
                lambda path: signing_inputs(path, data=b"x" * 900),
                render_sentinel_signing_key_shard_direct_pdf,
                True,
            ),
        )
        paper_cases = (
            ("A4", None),
            ("LETTER", None),
            ("FUTURE_PORTRAIT", (200.0, 320.0)),
        )
        with TemporaryDirectory() as tmp:
            for paper_size, dimensions_mm in paper_cases:
                for name, input_factory, renderer, has_caption in cases:
                    with self.subTest(paper_size=paper_size, doc_type=name):
                        output_path = Path(tmp) / f"compound-{name}-{paper_size.lower()}.pdf"
                        inputs = _with_paper(
                            input_factory(output_path),
                            paper_size,
                            dimensions_mm,
                        )

                        result = renderer(inputs)
                        layout_proof = result.layout_proof
                        assert layout_proof is not None
                        for page in layout_proof.pages:
                            qr_images = tuple(
                                component
                                for component in page.components
                                if "qr-image" in component.component_id
                                and "frame" not in component.component_id
                            )
                            marker_constraints = tuple(
                                constraint
                                for constraint in page.separation_constraints
                                if "qr-marker-clearance" in constraint.constraint_id
                            )
                            caption_constraints = tuple(
                                constraint
                                for constraint in page.separation_constraints
                                if "qr-caption" in constraint.constraint_id
                            )

                            self.assertEqual(len(marker_constraints), len(qr_images))
                            self.assertTrue(
                                all(constraint.satisfied for constraint in marker_constraints)
                            )
                            self.assertTrue(
                                all(
                                    constraint.measured_clearance_mm
                                    >= constraint.minimum_clearance_mm - 0.01
                                    for constraint in marker_constraints
                                )
                            )
                            expected_caption_count = (
                                1
                                if has_caption and (name != "main" or page.page_number == 1)
                                else 0
                            )
                            self.assertEqual(
                                len(caption_constraints),
                                expected_caption_count,
                            )
                            self.assertTrue(
                                all(constraint.satisfied for constraint in caption_constraints)
                            )
                            self.assertTrue(
                                all(
                                    constraint.measured_clearance_mm >= 2.0 - 0.01
                                    for constraint in caption_constraints
                                )
                            )

    def test_shard_large_custom_pages_place_fallback_rows_in_physical_space(self) -> None:
        paper_cases = (
            ("TALL_SENTINEL", (220.0, 800.0)),
            ("WIDE_SENTINEL", (500.0, 600.0)),
        )
        with TemporaryDirectory() as tmp:
            for paper_size, dimensions_mm in paper_cases:
                with self.subTest(paper_size=paper_size):
                    output_path = Path(tmp) / f"shard-{paper_size.lower()}.pdf"
                    inputs = _with_paper(
                        shard_inputs(output_path, data=b"x" * 900),
                        paper_size,
                        dimensions_mm,
                    )

                    result = render_sentinel_shard_direct_pdf(inputs)
                    layout_proof = result.layout_proof
                    assert layout_proof is not None

                    self.assertEqual(len(layout_proof.pages), 1)
                    self.assertFalse(layout_proof.overflow)
                    for page in layout_proof.pages:
                        fallback_panel = next(
                            component
                            for component in page.components
                            if component.component_id.endswith("-fallback-panel")
                        )
                        fallback_rows = tuple(
                            component
                            for component in page.components
                            if "-fallback-title-" in component.component_id
                            or "-fallback-line-" in component.component_id
                        )
                        self.assertTrue(fallback_rows)
                        self.assertTrue(
                            all(
                                row.rect.y_mm >= fallback_panel.rect.y_mm - 0.01
                                and row.rect.bottom_mm <= fallback_panel.rect.bottom_mm + 0.01
                                for row in fallback_rows
                            )
                        )
                        self.assertTrue(
                            all(abs(row.rect.height_mm - 2.5) <= 0.01 for row in fallback_rows)
                        )
                        ordered_y_positions = sorted(
                            {round(row.rect.y_mm, 3) for row in fallback_rows}
                        )
                        self.assertTrue(
                            all(
                                second - first >= 2.65 - 0.01
                                for first, second in zip(
                                    ordered_y_positions,
                                    ordered_y_positions[1:],
                                    strict=False,
                                )
                            )
                        )
                        self._assert_footer_constraints((page,))

    def test_shard_fallback_panels_stay_full_width_and_bottom_anchored(self) -> None:
        document_cases = (
            (
                "shard",
                shard_inputs,
                render_sentinel_shard_direct_pdf,
                "-fallback-panel",
            ),
            (
                "signing-key-shard",
                signing_inputs,
                render_sentinel_signing_key_shard_direct_pdf,
                "-payload-panel",
            ),
        )
        paper_cases = (
            ("A4", None),
            ("LETTER", None),
            ("FUTURE_PORTRAIT", (260.0, 360.0)),
        )
        with TemporaryDirectory() as tmp:
            for paper_name, dimensions_mm in paper_cases:
                for document_name, input_factory, renderer, panel_suffix in document_cases:
                    with self.subTest(paper_name=paper_name, document_name=document_name):
                        panels = []
                        for payload_name, data in (
                            ("normal", b"normal shard payload"),
                            ("maximum", b"x" * MAX_SHARD_CBOR_BYTES),
                        ):
                            output_path = (
                                Path(tmp)
                                / f"{document_name}-{paper_name.lower()}-{payload_name}.pdf"
                            )
                            inputs = _with_paper(
                                input_factory(output_path, data=data),
                                paper_name,
                                dimensions_mm,
                            )
                            result = renderer(inputs)
                            artifact_proof = result.artifact_proof
                            layout_proof = result.layout_proof
                            assert artifact_proof is not None
                            assert layout_proof is not None
                            reader = validate_pdf_has_pages(output_path)
                            validate_fallback_text_in_pdf(
                                artifact_label=f"direct Sentinel {document_name} document",
                                reader=reader,
                                fallback_sections=inputs.fallback_sections or (),
                                fallback_proof=result.fallback_proof,
                            )
                            self.assertEqual(artifact_proof.page_count, 1)
                            self.assertEqual(artifact_proof.physical_qr_count, 1)
                            self.assertTrue(result.fallback_proof.fully_consumed)
                            self.assertEqual(len(layout_proof.pages), 1)
                            panels.append(
                                next(
                                    component
                                    for component in layout_proof.pages[0].components
                                    if component.component_id.endswith(panel_suffix)
                                ).rect
                            )

                        normal_panel, maximum_panel = panels
                        geometry = resolve_page_geometry(
                            _with_paper(
                                input_factory(Path(tmp) / "geometry.pdf"),
                                paper_name,
                                dimensions_mm,
                            )
                        )
                        safe_width_mm = SENTINEL_THEME.layout.content_width_mm
                        expected_x_mm = (geometry.width_mm - safe_width_mm) / 2.0
                        for panel in panels:
                            self.assertAlmostEqual(panel.x_mm, expected_x_mm, places=2)
                            self.assertAlmostEqual(panel.width_mm, safe_width_mm, places=2)
                        self.assertAlmostEqual(
                            normal_panel.bottom_mm,
                            maximum_panel.bottom_mm,
                            places=2,
                        )
                        self.assertGreater(maximum_panel.height_mm, normal_panel.height_mm)

    def test_shard_fallback_text_expands_to_each_resolved_panel_width(self) -> None:
        document_cases = (
            (
                "shard",
                shard_inputs,
                render_sentinel_shard_direct_pdf,
                "-fallback-panel",
            ),
            (
                "signing-key-shard",
                signing_inputs,
                render_sentinel_signing_key_shard_direct_pdf,
                "-payload-panel",
            ),
        )
        paper_cases = (
            ("A4", None),
            ("LETTER", None),
            ("FUTURE_PORTRAIT", (260.0, 360.0)),
        )
        payload_cases = (
            ("normal", b"x" * 512),
            ("maximum", b"x" * MAX_SHARD_CBOR_BYTES),
        )
        with TemporaryDirectory() as tmp:
            for paper_name, dimensions_mm in paper_cases:
                for document_name, input_factory, renderer, panel_suffix in document_cases:
                    for payload_name, data in payload_cases:
                        with self.subTest(
                            paper_name=paper_name,
                            document_name=document_name,
                            payload_name=payload_name,
                        ):
                            output_path = Path(tmp) / (
                                f"adaptive-{document_name}-{paper_name.lower()}-{payload_name}.pdf"
                            )
                            result = renderer(
                                _with_paper(
                                    input_factory(output_path, data=data),
                                    paper_name,
                                    dimensions_mm,
                                )
                            )
                            layout_proof = result.layout_proof
                            assert layout_proof is not None
                            page = layout_proof.pages[0]
                            panel = next(
                                component
                                for component in page.components
                                if component.component_id.endswith(panel_suffix)
                            )
                            lines = tuple(
                                component
                                for component in page.components
                                if "-fallback-line-" in component.component_id
                            )

                            self.assertTrue(lines)
                            expected_inner_width_mm = panel.rect.width_mm - 9.0
                            self.assertTrue(
                                all(
                                    abs(line.rect.width_mm - expected_inner_width_mm) <= 0.01
                                    for line in lines
                                )
                            )
                            widest_used_line_mm = max(
                                line.used_rect.width_mm
                                for line in lines
                                if line.used_rect is not None
                            )
                            self.assertGreaterEqual(
                                widest_used_line_mm,
                                expected_inner_width_mm * 0.95,
                            )
                            self.assertLessEqual(
                                widest_used_line_mm,
                                expected_inner_width_mm + 0.01,
                            )
                            self.assertGreaterEqual(
                                max(map(len, result.fallback_proof.emitted_fallback_lines)),
                                130,
                            )

    def test_shard_fallback_uses_two_column_rescue_before_failing_fast(self) -> None:
        document_cases = (
            ("shard", sentinel_shard_module, shard_inputs),
            (
                "signing-key-shard",
                sentinel_signing_key_shard_module,
                signing_inputs,
            ),
        )
        with TemporaryDirectory() as tmp:
            for document_name, module, input_factory in document_cases:
                with self.subTest(document_name=document_name):
                    inputs = input_factory(
                        Path(tmp) / f"{document_name}.pdf",
                        data=b"x" * MAX_SHARD_CBOR_BYTES,
                    )
                    surface = build_sentinel_surface(inputs)
                    packaged_direct_pdf_assets().register_fonts(surface)
                    page_layout = build_sentinel_page_layout(inputs)
                    sections = inputs.fallback_sections or ()

                    _, preferred_pages = module._resolve_fallback_layout(
                        surface,
                        sections,
                        page_layout=page_layout,
                    )
                    self.assertEqual(preferred_pages[0].layout_profile.columns, 1)

                    candidate_tops = []
                    for profile in module._FALLBACK_LAYOUT_PROFILES:
                        _, pages = module._build_fallback_candidate(
                            surface,
                            sections,
                            page_layout=page_layout,
                            layout_profile=profile,
                        )
                        candidate_tops.append(pages[0].panel_rect.y_mm)

                    preferred_top_y_mm, rescue_top_y_mm = candidate_tops
                    preferred_profile, rescue_profile = module._FALLBACK_LAYOUT_PROFILES
                    self.assertGreater(rescue_top_y_mm, preferred_top_y_mm)
                    self.assertGreaterEqual(rescue_profile.text_size_pt, 6.0)
                    self.assertGreaterEqual(rescue_profile.title_size_pt, 6.0)
                    self.assertLess(
                        rescue_profile.row_height_mm + rescue_profile.row_gap_mm,
                        preferred_profile.row_height_mm + preferred_profile.row_gap_mm,
                    )
                    constrained_top_y_mm = (preferred_top_y_mm + rescue_top_y_mm) / 2.0

                    _, rescue_pages = module._select_fallback_layout(
                        surface,
                        sections,
                        page_layout=page_layout,
                        minimum_top_y_mm=constrained_top_y_mm,
                    )
                    rescue_page = rescue_pages[0]
                    self.assertEqual(rescue_page.layout_profile.columns, 2)
                    self.assertTrue(
                        all(
                            abs(entry.rect.height_mm - rescue_page.layout_profile.row_height_mm)
                            <= 0.01
                            for entry in rescue_page.entries
                        )
                    )
                    context = build_sentinel_shell_context(inputs, doc_type=inputs.doc_type)
                    qr_image = module.qr_image(
                        module._resolved_qr_payload(inputs),
                        config=inputs.qr_config or QrConfig(),
                    )
                    rescue_plan = module._build_page(
                        surface,
                        context,
                        rescue_page,
                        qr_image=qr_image,
                        total_pages=1,
                    )
                    rescue_plan.paint(surface)
                    self.assertFalse(rescue_plan.proof.overflow)
                    rescue_titles = tuple(
                        plan.proof
                        for plan in rescue_plan.plans
                        if "-fallback-title-" in plan.component_id
                    )
                    self.assertTrue(rescue_titles)
                    self.assertTrue(
                        all(
                            getattr(component, "font_size_pt", None) == rescue_profile.title_size_pt
                            for component in rescue_titles
                        )
                    )

                    with self.assertRaisesRegex(ValueError, "cannot fit"):
                        module._select_fallback_layout(
                            surface,
                            sections,
                            page_layout=page_layout,
                            minimum_top_y_mm=rescue_top_y_mm + 0.01,
                        )

    def test_shards_are_single_page_on_minimum_and_larger_future_sizes(self) -> None:
        document_cases = (
            ("shard", shard_inputs, render_sentinel_shard_direct_pdf),
            (
                "signing-key-shard",
                signing_inputs,
                render_sentinel_signing_key_shard_direct_pdf,
            ),
        )
        paper_cases = (
            ("A4", None),
            ("LETTER", None),
            ("MINIMUM", (200.0, 279.4)),
            ("LEGAL", (215.9, 355.6)),
            ("A3", (297.0, 420.0)),
        )
        with TemporaryDirectory() as tmp:
            for paper_name, dimensions_mm in paper_cases:
                for document_name, input_factory, renderer in document_cases:
                    with self.subTest(paper_name=paper_name, document_name=document_name):
                        output_path = Path(tmp) / f"{document_name}-{paper_name.lower()}.pdf"
                        inputs = _with_paper(
                            input_factory(output_path, data=b"x" * MAX_SHARD_CBOR_BYTES),
                            paper_name,
                            dimensions_mm,
                        )

                        result = renderer(inputs)
                        artifact_proof = result.artifact_proof
                        layout_proof = result.layout_proof
                        assert artifact_proof is not None
                        assert layout_proof is not None

                        self.assertEqual(artifact_proof.page_count, 1)
                        self.assertEqual(artifact_proof.physical_qr_count, 1)
                        self.assertEqual(len(layout_proof.pages), 1)
                        self.assertFalse(layout_proof.overflow)
                        self._assert_readable_font_floor(layout_proof.pages)
                        self._assert_footer_constraints(layout_proof.pages)

    def _assert_page_geometry(
        self,
        pages: Sequence[Any],
        width_mm: float,
        height_mm: float,
    ) -> None:
        for page in pages:
            rendered_width_mm = float(page.mediabox.width) * _POINT_TO_MM
            rendered_height_mm = float(page.mediabox.height) * _POINT_TO_MM
            self.assertAlmostEqual(rendered_width_mm, width_mm, places=2)
            self.assertAlmostEqual(rendered_height_mm, height_mm, places=2)

    def _assert_page_labels(self, pages: Sequence[Any]) -> None:
        total_pages = len(pages)
        for page_number, page in enumerate(pages, start=1):
            text = " ".join((page.extract_text() or "").upper().split())
            self.assertIn(f"PAGE {page_number} / {total_pages}", text)

    def _assert_readable_font_floor(self, pages: Sequence[RenderPageLayoutProof]) -> None:
        font_sizes = tuple(
            component.font_size_pt
            for page in pages
            for component in page.components
            if component.font_size_pt is not None
        )
        self.assertTrue(font_sizes)
        self.assertGreaterEqual(min(font_sizes), _MINIMUM_TEXT_FONT_SIZE_PT)
        manual_line_number_sizes = tuple(
            component.font_size_pt
            for page in pages
            for component in page.components
            if "fallback-line-number" in component.component_id
            and component.font_size_pt is not None
        )
        if manual_line_number_sizes:
            self.assertGreaterEqual(
                min(manual_line_number_sizes),
                _MINIMUM_MANUAL_LINE_NUMBER_FONT_SIZE_PT,
            )

    def _assert_footer_constraints(self, pages: Sequence[RenderPageLayoutProof]) -> None:
        for page in pages:
            body_constraints = tuple(
                constraint
                for constraint in page.separation_constraints
                if "body-footer" in constraint.constraint_id
            )
            self.assertEqual(len(body_constraints), 1)
            self.assertTrue(body_constraints[0].satisfied)
            self.assertGreaterEqual(body_constraints[0].measured_clearance_mm, 1.0)
            qr_components = tuple(
                component for component in page.components if "qr-image" in component.component_id
            )
            qr_constraints = tuple(
                constraint
                for constraint in page.separation_constraints
                if "qr-footer" in constraint.constraint_id
            )
            self.assertEqual(len(qr_constraints), 1 if qr_components else 0)
            if qr_constraints:
                self.assertTrue(qr_constraints[0].satisfied)
                self.assertGreaterEqual(qr_constraints[0].measured_clearance_mm, 2.0)
                self.assertGreaterEqual(
                    min(component.rect.width_mm for component in qr_components),
                    44.0,
                )

    def _assert_partial_final_page(
        self,
        pages: Sequence[RenderPageLayoutProof],
        *,
        marker: str,
    ) -> None:
        item_counts = tuple(
            sum(marker in component.component_id for component in page.components) for page in pages
        )
        non_empty_counts = tuple(count for count in item_counts if count > 0)
        self.assertGreater(len(non_empty_counts), 1)
        self.assertLess(non_empty_counts[-1], max(non_empty_counts))


if __name__ == "__main__":
    unittest.main()
