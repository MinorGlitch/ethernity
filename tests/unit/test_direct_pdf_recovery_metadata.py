import unittest

from ethernity.render.direct_pdf.recovery_metadata import paginate_recovery_passphrase
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.types import TextStyle
from ethernity.render.recovery_meta import build_recovery_meta


class TestDirectPdfRecoveryMetadata(unittest.TestCase):
    def setUp(self) -> None:
        self.surface = FpdfSurface(page_width_mm=210.0, page_height_mm=297.0)
        self.style = TextStyle(family="Helvetica", size_pt=8.0)

    def test_normal_24_words_stay_in_the_original_four_lines(self) -> None:
        passphrase = " ".join(f"word{index:02d}" for index in range(24))
        meta = build_recovery_meta(
            passphrase=passphrase,
            quorum_threshold=None,
            quorum_shares=None,
            signing_pub=None,
        )

        pagination = paginate_recovery_passphrase(
            self.surface,
            meta,
            style=self.style,
            max_width_mm=100.0,
            inline_height_mm=20.0,
            continuation_height_mm=180.0,
        )

        self.assertFalse(pagination.uses_json_parts)
        self.assertEqual(pagination.inline_meta.passphrase_lines, meta.passphrase_lines)
        self.assertEqual(pagination.decoded_passphrase(), passphrase)

    def test_long_exact_value_round_trips_across_multiple_pages(self) -> None:
        passphrase = ("alpha  beta\tgamma\n" + "p\u00e4ss-") * 120
        meta = build_recovery_meta(
            passphrase=passphrase,
            quorum_threshold=None,
            quorum_shares=None,
            signing_pub=None,
        )

        pagination = paginate_recovery_passphrase(
            self.surface,
            meta,
            style=self.style,
            max_width_mm=58.0,
            inline_height_mm=24.0,
            continuation_height_mm=15.0,
        )

        self.assertTrue(pagination.uses_json_parts)
        self.assertGreater(len(pagination.continuation_pages), 1)
        self.assertEqual(pagination.decoded_passphrase(), passphrase)
        self.assertEqual(
            [part.part_number for part in pagination.all_parts],
            list(range(1, len(pagination.all_parts) + 1)),
        )
        self.assertTrue(
            all(
                self.surface.measure_text_width(part.line_text, self.style) <= 58.0
                for part in pagination.all_parts
            )
        )

    def test_zero_line_capacity_fails_fast(self) -> None:
        meta = build_recovery_meta(
            passphrase="x" * 512,
            quorum_threshold=None,
            quorum_shares=None,
            signing_pub=None,
        )

        with self.assertRaisesRegex(ValueError, "zero printable line capacity"):
            paginate_recovery_passphrase(
                self.surface,
                meta,
                style=self.style,
                max_width_mm=100.0,
                inline_height_mm=0.1,
                continuation_height_mm=180.0,
            )

    def test_one_line_capacity_fails_when_overflow_requires_guidance(self) -> None:
        line_height = self.surface.line_height(self.style, multiplier=1.15)
        cases = (
            " ".join(f"word{index:03d}" for index in range(100)),
            "alpha\tbeta" * 80,
        )
        for passphrase in cases:
            with self.subTest(passphrase=passphrase[:20]):
                meta = build_recovery_meta(
                    passphrase=passphrase,
                    quorum_threshold=None,
                    quorum_shares=None,
                    signing_pub=None,
                )
                with self.assertRaisesRegex(ValueError, "guidance"):
                    paginate_recovery_passphrase(
                        self.surface,
                        meta,
                        style=self.style,
                        max_width_mm=58.0,
                        inline_height_mm=line_height,
                        continuation_height_mm=180.0,
                    )

    def test_narrow_wrapped_guidance_is_measured_before_allocating_value_lines(self) -> None:
        passphrase = " ".join(f"word{index:03d}" for index in range(100))
        meta = build_recovery_meta(
            passphrase=passphrase,
            quorum_threshold=None,
            quorum_shares=None,
            signing_pub=None,
        )

        pagination = paginate_recovery_passphrase(
            self.surface,
            meta,
            style=self.style,
            max_width_mm=42.0,
            inline_height_mm=24.0,
            continuation_height_mm=30.0,
        )

        self.assertTrue(pagination.continuation_pages)
        self.assertEqual(pagination.decoded_passphrase(), passphrase)


if __name__ == "__main__":
    unittest.main()
