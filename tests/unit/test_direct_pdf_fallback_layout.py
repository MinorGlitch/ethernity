from __future__ import annotations

import math
import unittest
from dataclasses import replace
from unittest import mock

import ethernity.render.direct_pdf.fallback_layout as fallback_layout_module
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType, encode_frame
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.render.direct_pdf.fallback_layout import (
    FallbackLineEntry,
    FallbackPage,
    FallbackSectionLines,
    FallbackTitleEntry,
    ResponsiveFallbackPageProfile,
    ResponsiveFallbackSpec,
    build_fallback_proof,
    fallback_entries,
    fallback_sections,
    paginate_fallback_entries,
    resolve_responsive_fallback_pagination,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.types import PdfRect, TextStyle
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage


class TestResponsiveFallbackPagination(unittest.TestCase):
    def setUp(self) -> None:
        self.surface = FpdfSurface(page_width_mm=260.0, page_height_mm=360.0)
        self.style = TextStyle(family="Courier", size_pt=7.0)
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x42" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"x" * 4_000,
        )
        self.sections = (FallbackSection(label="MAIN FRAME", frame=frame),)

    def test_measures_reflows_and_paginates_from_both_page_areas(self) -> None:
        spec = ResponsiveFallbackSpec(
            group_size=4,
            row_height_mm=4.0,
            body_style=self.style,
            number_style=self.style,
            content_left_inset_mm=2.0,
            content_right_inset_mm=2.0,
            vertical_reserved_mm=4.0,
            number_gap_mm=0.0,
            inline_number=True,
            safety_mm=0.2,
        )

        narrow = resolve_responsive_fallback_pagination(
            self.surface,
            self.sections,
            first_profile=ResponsiveFallbackPageProfile(
                area=PdfRect(10.0, 50.0, 140.0, 100.0),
                spec=spec,
            ),
            continuation_profile=ResponsiveFallbackPageProfile(
                area=PdfRect(10.0, 40.0, 140.0, 120.0),
                spec=spec,
            ),
        )
        wide = resolve_responsive_fallback_pagination(
            self.surface,
            self.sections,
            first_profile=ResponsiveFallbackPageProfile(
                area=PdfRect(10.0, 50.0, 220.0, 100.0),
                spec=spec,
            ),
            continuation_profile=ResponsiveFallbackPageProfile(
                area=PdfRect(10.0, 40.0, 220.0, 120.0),
                spec=spec,
            ),
        )

        self.assertEqual(narrow.first_capacity, math.floor((100.0 - 4.0) / 4.0))
        self.assertEqual(narrow.continuation_capacity, math.floor((120.0 - 4.0) / 4.0))
        self.assertAlmostEqual(
            narrow.first_payload_width_mm,
            narrow.continuation_payload_width_mm,
        )
        self.assertGreater(wide.first_line_length, narrow.first_line_length)
        self.assertGreater(wide.first_payload_width_mm, narrow.first_payload_width_mm)
        self.assertLessEqual(len(wide.pages), len(narrow.pages))
        self.assertTrue(
            any(
                len(line) == wide.first_line_length
                for section in wide.sections
                for line in section.lines
            )
        )

    def test_profiled_pagination_reflows_wider_continuations_without_data_loss(self) -> None:
        spec = ResponsiveFallbackSpec(
            group_size=4,
            row_height_mm=4.0,
            body_style=self.style,
            number_style=self.style,
            content_left_inset_mm=2.0,
            content_right_inset_mm=2.0,
            vertical_reserved_mm=0.0,
            number_gap_mm=0.0,
            inline_number=True,
            safety_mm=0.2,
        )

        pagination = resolve_responsive_fallback_pagination(
            self.surface,
            self.sections,
            first_profile=ResponsiveFallbackPageProfile(
                area=PdfRect(10.0, 50.0, 120.0, 60.0),
                spec=spec,
            ),
            continuation_profile=ResponsiveFallbackPageProfile(
                area=PdfRect(10.0, 40.0, 220.0, 80.0),
                spec=spec,
            ),
        )

        self.assertGreater(
            pagination.continuation_line_length,
            pagination.first_line_length,
        )
        self.assertGreater(
            pagination.continuation_payload_width_mm,
            pagination.first_payload_width_mm,
        )
        self.assertGreater(len(pagination.pages), 1)
        first_page_lengths = {
            len(entry.entry.text)
            for entry in pagination.pages[0].entries
            if isinstance(entry.entry, FallbackLineEntry)
        }
        continuation_lengths = {
            len(entry.entry.text)
            for page in pagination.pages[1:]
            for entry in page.entries
            if isinstance(entry.entry, FallbackLineEntry)
        }
        self.assertIn(pagination.first_line_length, first_page_lengths)
        self.assertIn(pagination.continuation_line_length, continuation_lengths)
        reconstructed = "".join(
            line.replace(" ", "") for section in pagination.sections for line in section.lines
        )
        self.assertEqual(
            reconstructed,
            "".join(encode_zbase32(encode_frame(section.frame)) for section in self.sections),
        )

    def test_profiled_pagination_uses_actual_gutter_and_shrinks_for_wider_numbers(self) -> None:
        spec = ResponsiveFallbackSpec(
            group_size=4,
            row_height_mm=4.0,
            body_style=self.style,
            number_style=self.style,
            content_left_inset_mm=2.0,
            content_right_inset_mm=2.0,
            vertical_reserved_mm=0.0,
            number_gap_mm=0.0,
            inline_number=True,
            safety_mm=0.2,
        )
        area = PdfRect(10.0, 40.0, 120.0, 480.0)
        profile = ResponsiveFallbackPageProfile(area=area, spec=spec)
        sparse_frame = replace(self.sections[0].frame, data=b"sparse")
        dense_frame = replace(self.sections[0].frame, data=b"dense" * 2_000)

        sparse = resolve_responsive_fallback_pagination(
            self.surface,
            (FallbackSection(label="MAIN FRAME", frame=sparse_frame),),
            first_profile=profile,
            continuation_profile=profile,
        )
        dense = resolve_responsive_fallback_pagination(
            self.surface,
            (FallbackSection(label="MAIN FRAME", frame=dense_frame),),
            first_profile=profile,
            continuation_profile=profile,
        )

        sparse_maximum = max(entry.display_line_number or 0 for entry in sparse.pages[0].entries)
        dense_maximum = max(entry.display_line_number or 0 for entry in dense.pages[0].entries)
        self.assertLess(sparse_maximum, 100)
        self.assertGreaterEqual(dense_maximum, 100)
        self.assertEqual(len(dense.pages[0].entries), dense.first_capacity)
        expected_sparse_width = (
            area.width_mm
            - spec.content_left_inset_mm
            - self.surface.measure_text_width(f"{sparse_maximum:02d}. ", self.style)
            - spec.content_right_inset_mm
        )
        expected_dense_width = (
            area.width_mm
            - spec.content_left_inset_mm
            - self.surface.measure_text_width(f"{dense_maximum:02d}. ", self.style)
            - spec.content_right_inset_mm
        )
        capacity_reserved_width = (
            area.width_mm
            - spec.content_left_inset_mm
            - self.surface.measure_text_width(f"{sparse.first_capacity:02d}. ", self.style)
            - spec.content_right_inset_mm
        )
        self.assertAlmostEqual(sparse.first_payload_width_mm, expected_sparse_width)
        self.assertAlmostEqual(dense.first_payload_width_mm, expected_dense_width)
        self.assertGreater(sparse.first_payload_width_mm, capacity_reserved_width)
        self.assertGreater(sparse.first_payload_width_mm, dense.first_payload_width_mm)
        self.assertGreater(sparse.first_line_length, dense.first_line_length)

    def test_profiled_pagination_enforces_fallback_line_bound(self) -> None:
        spec = ResponsiveFallbackSpec(
            group_size=4,
            row_height_mm=4.0,
            body_style=self.style,
            number_style=self.style,
            content_left_inset_mm=2.0,
            content_right_inset_mm=2.0,
            vertical_reserved_mm=0.0,
            number_gap_mm=0.0,
            inline_number=True,
        )
        profile = ResponsiveFallbackPageProfile(
            area=PdfRect(10.0, 40.0, 120.0, 80.0),
            spec=spec,
        )

        with mock.patch.object(fallback_layout_module, "MAX_FALLBACK_LINES", 1):
            with self.assertRaisesRegex(ValueError, "fallback text exceeds line_count"):
                resolve_responsive_fallback_pagination(
                    self.surface,
                    self.sections,
                    first_profile=profile,
                    continuation_profile=profile,
                )

    def test_profiled_pagination_keeps_titles_with_first_lines_and_resets_numbers(self) -> None:
        spec = ResponsiveFallbackSpec(
            group_size=4,
            row_height_mm=4.0,
            body_style=self.style,
            number_style=self.style,
            content_left_inset_mm=2.0,
            content_right_inset_mm=2.0,
            vertical_reserved_mm=0.0,
            number_gap_mm=0.0,
            inline_number=True,
            safety_mm=0.2,
        )
        first_frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x42" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"first",
        )
        second_frame = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=b"\x42" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"second",
        )
        sections = (
            FallbackSection(label="MAIN FRAME", frame=first_frame),
            FallbackSection(label="AUTH FRAME", frame=second_frame),
        )
        measuring_profile = ResponsiveFallbackPageProfile(
            area=PdfRect(10.0, 40.0, 240.0, 80.0),
            spec=spec,
        )
        first_section = resolve_responsive_fallback_pagination(
            self.surface,
            sections[:1],
            first_profile=measuring_profile,
            continuation_profile=measuring_profile,
        )
        self.assertEqual(len(first_section.pages), 1)
        first_section_entry_count = len(first_section.pages[0].entries)
        orphaning_capacity = first_section_entry_count + 1
        orphaning_profile = ResponsiveFallbackPageProfile(
            area=PdfRect(10.0, 40.0, 240.0, orphaning_capacity * spec.row_height_mm),
            spec=spec,
        )

        pagination = resolve_responsive_fallback_pagination(
            self.surface,
            sections,
            first_profile=orphaning_profile,
            continuation_profile=orphaning_profile,
        )

        self.assertGreater(len(pagination.pages), 1)
        self.assertEqual(len(pagination.pages[0].entries), first_section_entry_count)
        self.assertIsInstance(pagination.pages[1].entries[0].entry, FallbackTitleEntry)
        for page in pagination.pages:
            for index, page_entry in enumerate(page.entries):
                if isinstance(page_entry.entry, FallbackTitleEntry):
                    self.assertLess(index + 1, len(page.entries))
                    next_entry = page.entries[index + 1]
                    self.assertIsInstance(next_entry.entry, FallbackLineEntry)
                    self.assertEqual(next_entry.display_line_number, 1)


class TestFallbackProofValidation(unittest.TestCase):
    def _fixture(
        self,
    ) -> tuple[
        RenderInputs,
        tuple[FallbackSectionLines, ...],
        tuple[FallbackPage, ...],
    ]:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x51" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"fallback proof integrity" * 8,
        )
        source_sections = (FallbackSection(label="MAIN FRAME", frame=frame),)
        inputs = RenderInputs(
            frames=(frame,),
            output_path="fallback-proof.pdf",
            context={},
            doc_type="recovery",
            lineage=RenderLineage(kind="root_backup"),
            design_name="archive",
            render_qr=False,
            render_fallback=True,
            fallback_sections=source_sections,
        )
        sections = fallback_sections(source_sections, group_size=4, line_length=19)
        pages = paginate_fallback_entries(fallback_entries(sections), capacity=1_000)
        return inputs, sections, pages

    def test_build_fallback_proof_accepts_exact_page_entries(self) -> None:
        inputs, sections, pages = self._fixture()

        proof = build_fallback_proof(inputs, sections, pages)

        self.assertTrue(proof.fully_consumed)
        self.assertEqual(proof.consumed_section_count, 1)
        self.assertEqual(
            proof.emitted_fallback_lines,
            tuple(line for section in sections for line in section.lines),
        )

    def test_build_fallback_proof_rejects_omitted_entry(self) -> None:
        inputs, sections, pages = self._fixture()
        incomplete = (replace(pages[0], entries=pages[0].entries[:-1]),)

        with self.assertRaisesRegex(ValueError, "exactly consume section entries"):
            build_fallback_proof(inputs, sections, incomplete)

    def test_build_fallback_proof_rejects_duplicated_entry(self) -> None:
        inputs, sections, pages = self._fixture()
        duplicated = (
            replace(
                pages[0],
                entries=(*pages[0].entries, pages[0].entries[-1]),
            ),
        )

        with self.assertRaisesRegex(ValueError, "exactly consume section entries"):
            build_fallback_proof(inputs, sections, duplicated)

    def test_build_fallback_proof_rejects_mismatched_entry(self) -> None:
        inputs, sections, pages = self._fixture()
        final_page_entry = pages[0].entries[-1]
        self.assertIsInstance(final_page_entry.entry, FallbackLineEntry)
        assert isinstance(final_page_entry.entry, FallbackLineEntry)
        mismatched_entry = replace(
            final_page_entry,
            entry=replace(
                final_page_entry.entry,
                text=f"{final_page_entry.entry.text}y",
            ),
        )
        mismatched = (
            replace(
                pages[0],
                entries=(*pages[0].entries[:-1], mismatched_entry),
            ),
        )

        with self.assertRaisesRegex(ValueError, "exactly consume section entries"):
            build_fallback_proof(inputs, sections, mismatched)

    def test_build_fallback_proof_rejects_nonsequential_display_numbers(self) -> None:
        inputs, sections, pages = self._fixture()
        first_line_index = next(
            index
            for index, page_entry in enumerate(pages[0].entries)
            if isinstance(page_entry.entry, FallbackLineEntry)
        )
        misnumbered_entry = replace(
            pages[0].entries[first_line_index],
            display_line_number=2,
        )
        misnumbered = (
            replace(
                pages[0],
                entries=(
                    *pages[0].entries[:first_line_index],
                    misnumbered_entry,
                    *pages[0].entries[first_line_index + 1 :],
                ),
            ),
        )

        with self.assertRaisesRegex(ValueError, "display numbers are not sequential"):
            build_fallback_proof(inputs, sections, misnumbered)


if __name__ == "__main__":
    unittest.main()
