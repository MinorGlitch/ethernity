import unittest

from ethernity.encoding.framing import DOC_ID_LEN, FrameType
from ethernity.formats.frame_manifest import build_manifest_frame, parse_manifest_frame


class TestManifest(unittest.TestCase):
    def test_manifest_roundtrip(self) -> None:
        doc_id = b"\x11" * DOC_ID_LEN
        frame = build_manifest_frame(
            doc_id=doc_id,
            data_frame_type=FrameType.MAIN_DOCUMENT,
            data_frame_total=3,
            payload_len=123,
            chunk_size=64,
        )
        manifest = parse_manifest_frame(frame)
        self.assertEqual(manifest.doc_id, doc_id)
        self.assertEqual(manifest.data_frame_type, FrameType.MAIN_DOCUMENT)
        self.assertEqual(manifest.data_frame_total, 3)
        self.assertEqual(manifest.payload_len, 123)
        self.assertEqual(manifest.chunk_size, 64)

    # ==========================================================================
    # Edge Case Tests
    # ==========================================================================

    def test_manifest_with_zero_payload_len_raises(self) -> None:
        """Test manifest with zero payload length raises error."""
        doc_id = b"\x22" * DOC_ID_LEN
        frame = build_manifest_frame(
            doc_id=doc_id,
            data_frame_type=FrameType.MAIN_DOCUMENT,
            data_frame_total=1,
            payload_len=0,
            chunk_size=64,
        )
        with self.assertRaises(ValueError) as ctx:
            parse_manifest_frame(frame)
        self.assertIn("positive", str(ctx.exception).lower())

    def test_manifest_with_large_values(self) -> None:
        """Test manifest with large payload_len and chunk_size."""
        doc_id = b"\x33" * DOC_ID_LEN
        frame = build_manifest_frame(
            doc_id=doc_id,
            data_frame_type=FrameType.MAIN_DOCUMENT,
            data_frame_total=1000,
            payload_len=1024 * 1024 * 100,  # 100MB
            chunk_size=65536,
        )
        manifest = parse_manifest_frame(frame)
        self.assertEqual(manifest.payload_len, 1024 * 1024 * 100)
        self.assertEqual(manifest.chunk_size, 65536)
        self.assertEqual(manifest.data_frame_total, 1000)

    def test_manifest_all_frame_types(self) -> None:
        """Test manifest with different data frame types."""
        doc_id = b"\x44" * DOC_ID_LEN
        for frame_type in [FrameType.MAIN_DOCUMENT, FrameType.KEY_DOCUMENT]:
            frame = build_manifest_frame(
                doc_id=doc_id,
                data_frame_type=frame_type,
                data_frame_total=1,
                payload_len=100,
                chunk_size=64,
            )
            manifest = parse_manifest_frame(frame)
            self.assertEqual(manifest.data_frame_type, frame_type)

    def test_manifest_with_single_frame(self) -> None:
        """Test manifest with data_frame_total=1."""
        doc_id = b"\x55" * DOC_ID_LEN
        frame = build_manifest_frame(
            doc_id=doc_id,
            data_frame_type=FrameType.MAIN_DOCUMENT,
            data_frame_total=1,
            payload_len=64,
            chunk_size=64,
        )
        manifest = parse_manifest_frame(frame)
        self.assertEqual(manifest.data_frame_total, 1)

    def test_manifest_with_many_frames(self) -> None:
        """Test manifest with many data frames."""
        doc_id = b"\x66" * DOC_ID_LEN
        frame = build_manifest_frame(
            doc_id=doc_id,
            data_frame_type=FrameType.MAIN_DOCUMENT,
            data_frame_total=10000,
            payload_len=10000 * 1024,
            chunk_size=1024,
        )
        manifest = parse_manifest_frame(frame)
        self.assertEqual(manifest.data_frame_total, 10000)

    def test_manifest_preserves_doc_id_bytes(self) -> None:
        """Test manifest preserves all doc_id byte patterns."""
        for pattern in [b"\x00", b"\xff", b"\xaa", b"\x55"]:
            doc_id = pattern * DOC_ID_LEN
            frame = build_manifest_frame(
                doc_id=doc_id,
                data_frame_type=FrameType.MAIN_DOCUMENT,
                data_frame_total=1,
                payload_len=10,
                chunk_size=10,
            )
            manifest = parse_manifest_frame(frame)
            self.assertEqual(manifest.doc_id, doc_id)


if __name__ == "__main__":
    unittest.main()
