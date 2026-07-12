import unittest

from ethernity.core.bounds import MAX_FALLBACK_LINES, MAX_MAIN_FRAME_DATA_BYTES
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType, encode_frame
from ethernity.render.direct_pdf import archive, forge_recovery, ledger, maritime, sentinel_recovery
from ethernity.render.direct_pdf.structured_common import (
    FallbackSectionLines,
    fallback_entries,
    paginate_fallback_entries,
)

_FALLBACK_GROUP_SIZE = 4


def _maximum_main_frame() -> Frame:
    return Frame(
        version=VERSION,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=b"\x00" * DOC_ID_LEN,
        index=0,
        total=1,
        data=b"\x00" * MAX_MAIN_FRAME_DATA_BYTES,
    )


def _zbase32_char_count(byte_count: int) -> int:
    return (byte_count * 8 + 4) // 5


def _payload_chars_per_line(line_length: int) -> int:
    groups_per_line = (line_length + 1) // (_FALLBACK_GROUP_SIZE + 1)
    return groups_per_line * _FALLBACK_GROUP_SIZE


class TestFallbackRenderBounds(unittest.TestCase):
    def test_every_recovery_renderer_fits_maximum_main_frame_under_line_cap(self) -> None:
        encoded_char_count = _zbase32_char_count(len(encode_frame(_maximum_main_frame())))
        line_lengths = {
            "archive": archive._FALLBACK_LINE_LENGTH,
            "forge": forge_recovery._FALLBACK_LINE_LENGTH,
            "ledger": ledger._FALLBACK_LINE_LENGTH,
            "maritime": maritime._FALLBACK_LINE_LENGTH,
            "sentinel": sentinel_recovery._FALLBACK_LINE_LENGTH,
        }

        self.assertEqual(line_lengths["forge"], 44)
        for renderer, line_length in line_lengths.items():
            with self.subTest(renderer=renderer):
                payload_chars = _payload_chars_per_line(line_length)
                required_lines = (encoded_char_count + payload_chars - 1) // payload_chars
                self.assertLessEqual(required_lines, MAX_FALLBACK_LINES)

    def test_structured_display_numbers_reset_per_page_and_section_block(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=b"\x01" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"auth",
        )
        sections = (
            FallbackSectionLines(
                section_index=0,
                title="AUTH FRAME",
                lines=("a", "b", "c"),
                frame=frame,
            ),
            FallbackSectionLines(
                section_index=1,
                title="MAIN FRAME",
                lines=("d", "e"),
                frame=frame,
            ),
        )

        pages = paginate_fallback_entries(fallback_entries(sections), capacity=3)

        self.assertEqual(
            tuple(entry.display_line_number for entry in pages[0].entries),
            (None, 1, 2),
        )
        self.assertEqual(
            tuple(entry.display_line_number for entry in pages[1].entries),
            (1, None, 1),
        )
        self.assertEqual(
            tuple(entry.display_line_number for entry in pages[2].entries),
            (1,),
        )


if __name__ == "__main__":
    unittest.main()
