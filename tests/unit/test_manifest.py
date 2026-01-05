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


if __name__ == "__main__":
    unittest.main()
