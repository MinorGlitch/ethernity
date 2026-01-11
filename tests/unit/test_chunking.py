import unittest

from ethernity.encoding.chunking import (
    chunk_payload,
    fallback_lines_to_frame,
    frame_to_fallback_lines,
    payload_to_fallback_lines,
    reassemble_payload,
)
from ethernity.encoding.fallback import (
    decode_fallback_lines,
    decode_zbase32,
    encode_fallback_lines,
    encode_zbase32,
)
from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType


class TestChunking(unittest.TestCase):
    def test_zbase32_roundtrip(self) -> None:
        payloads = [
            b"\x00",
            b"\x01\x02\x03\x04\x05",
            b"hello world",
            bytes(range(1, 32)),
        ]
        for payload in payloads:
            encoded = encode_zbase32(payload)
            decoded = decode_zbase32(encoded)
            self.assertEqual(decoded, payload)

    def test_fallback_roundtrip(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x10" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        lines = frame_to_fallback_lines(frame, line_count=10)
        recovered = fallback_lines_to_frame(lines)
        self.assertEqual(recovered, frame)

    def test_payload_fallback_roundtrip(self) -> None:
        payload = b"payload"
        doc_id = b"\x10" * DOC_ID_LEN
        lines = payload_to_fallback_lines(
            payload,
            doc_id=doc_id,
            frame_type=FrameType.MAIN_DOCUMENT,
            line_length=80,
        )
        frame = fallback_lines_to_frame(lines)
        self.assertEqual(frame.data, payload)

    def test_fallback_line_limit(self) -> None:
        data = b"A" * 200
        with self.assertRaises(ValueError):
            encode_fallback_lines(data, line_length=20, line_count=1)

    def test_decode_fallback_ignores_whitespace(self) -> None:
        data = b"abc123"
        encoded = encode_zbase32(data)
        spaced = " \n".join(encoded[i : i + 2] for i in range(0, len(encoded), 2))
        decoded = decode_fallback_lines([spaced])
        self.assertEqual(decoded, data)

    def test_chunk_reassemble_roundtrip(self) -> None:
        payload = b"0123456789" * 50
        doc_id = b"\x22" * DOC_ID_LEN
        frames = chunk_payload(
            payload, doc_id=doc_id, frame_type=FrameType.KEY_DOCUMENT, chunk_size=64
        )
        rebuilt = reassemble_payload(frames)
        self.assertEqual(rebuilt, payload)

    def test_chunk_reassemble_missing(self) -> None:
        payload = b"0123456789" * 20
        doc_id = b"\x33" * DOC_ID_LEN
        frames = chunk_payload(
            payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=32
        )
        with self.assertRaises(ValueError):
            reassemble_payload(frames[:-1])

    def test_chunk_payload_balanced(self) -> None:
        payload = b"A" * 10
        doc_id = b"\x55" * DOC_ID_LEN
        frames = chunk_payload(
            payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=6
        )
        sizes = [len(frame.data) for frame in frames]
        self.assertEqual(sum(sizes), len(payload))
        self.assertLessEqual(max(sizes) - min(sizes), 1)
        self.assertTrue(all(size <= 6 for size in sizes))

    def test_chunk_reassemble_mismatch(self) -> None:
        payload = b"0123456789" * 20
        doc_id = b"\x44" * DOC_ID_LEN
        frames = chunk_payload(
            payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=32
        )
        frames[0] = Frame(
            version=frames[0].version,
            frame_type=frames[0].frame_type,
            doc_id=b"\x99" * DOC_ID_LEN,
            index=frames[0].index,
            total=frames[0].total,
            data=frames[0].data,
        )
        with self.assertRaises(ValueError):
            reassemble_payload(frames)

    # ==========================================================================
    # Edge Case Tests
    # ==========================================================================

    def test_chunk_single_byte_payload(self) -> None:
        """Test chunking with smallest possible payload."""
        payload = b"X"
        doc_id = b"\x66" * DOC_ID_LEN
        frames = chunk_payload(
            payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=10
        )
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].data, payload)
        rebuilt = reassemble_payload(frames)
        self.assertEqual(rebuilt, payload)

    def test_chunk_size_equals_payload(self) -> None:
        """Test when chunk_size exactly equals payload size."""
        payload = b"exactly64b" * 6 + b"1234"  # 64 bytes
        doc_id = b"\x77" * DOC_ID_LEN
        frames = chunk_payload(
            payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=64
        )
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].data, payload)
        rebuilt = reassemble_payload(frames)
        self.assertEqual(rebuilt, payload)

    def test_chunk_size_larger_than_payload(self) -> None:
        """Test when chunk_size is larger than payload."""
        payload = b"small"
        doc_id = b"\x88" * DOC_ID_LEN
        frames = chunk_payload(
            payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=1000
        )
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].data, payload)
        rebuilt = reassemble_payload(frames)
        self.assertEqual(rebuilt, payload)

    def test_chunk_size_one(self) -> None:
        """Test with minimum chunk_size of 1."""
        payload = b"abc"
        doc_id = b"\x99" * DOC_ID_LEN
        frames = chunk_payload(
            payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=1
        )
        self.assertEqual(len(frames), 3)
        self.assertEqual([f.data for f in frames], [b"a", b"b", b"c"])
        rebuilt = reassemble_payload(frames)
        self.assertEqual(rebuilt, payload)

    def test_empty_payload_raises(self) -> None:
        """Test that empty payload raises ValueError."""
        doc_id = b"\xaa" * DOC_ID_LEN
        with self.assertRaises(ValueError) as ctx:
            chunk_payload(b"", doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=10)
        self.assertIn("empty", str(ctx.exception).lower())

    def test_invalid_chunk_size_zero(self) -> None:
        """Test that chunk_size=0 raises ValueError."""
        doc_id = b"\xbb" * DOC_ID_LEN
        with self.assertRaises(ValueError) as ctx:
            chunk_payload(b"data", doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=0)
        self.assertIn("positive", str(ctx.exception).lower())

    def test_invalid_chunk_size_negative(self) -> None:
        """Test that negative chunk_size raises ValueError."""
        doc_id = b"\xcc" * DOC_ID_LEN
        with self.assertRaises(ValueError) as ctx:
            chunk_payload(b"data", doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=-1)
        self.assertIn("positive", str(ctx.exception).lower())

    def test_invalid_doc_id_length(self) -> None:
        """Test that wrong doc_id length raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            chunk_payload(
                b"data", doc_id=b"\x00" * 8, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=10
            )
        self.assertIn("doc_id", str(ctx.exception).lower())

    def test_reassemble_reversed_order(self) -> None:
        """Test reassembly works with frames in reversed order."""
        payload = b"0123456789"
        doc_id = b"\xdd" * DOC_ID_LEN
        frames = chunk_payload(
            payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=3
        )
        reversed_frames = list(reversed(frames))
        rebuilt = reassemble_payload(reversed_frames)
        self.assertEqual(rebuilt, payload)

    def test_reassemble_shuffled_order(self) -> None:
        """Test reassembly works with frames in random order."""
        payload = b"ABCDEFGHIJ"
        doc_id = b"\xee" * DOC_ID_LEN
        frames = chunk_payload(
            payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=2
        )
        # Shuffle: [0,1,2,3,4] -> [2,4,0,3,1]
        shuffled = [frames[2], frames[4], frames[0], frames[3], frames[1]]
        rebuilt = reassemble_payload(shuffled)
        self.assertEqual(rebuilt, payload)

    def test_reassemble_empty_frames_raises(self) -> None:
        """Test reassembly with no frames raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            reassemble_payload([])
        self.assertIn("no frames", str(ctx.exception).lower())

    def test_reassemble_duplicate_index_raises(self) -> None:
        """Test reassembly with duplicate indices raises ValueError."""
        doc_id = b"\xff" * DOC_ID_LEN
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=doc_id,
                index=0,
                total=2,
                data=b"a",
            ),
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=doc_id,
                index=0,  # Duplicate!
                total=2,
                data=b"b",
            ),
        ]
        with self.assertRaises(ValueError) as ctx:
            reassemble_payload(frames)
        self.assertIn("duplicate", str(ctx.exception).lower())

    def test_reassemble_version_mismatch_raises(self) -> None:
        """Test reassembly with mismatched versions raises ValueError."""
        doc_id = b"\x12" * DOC_ID_LEN
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=doc_id,
                index=0,
                total=2,
                data=b"a",
            ),
            Frame(
                version=2,  # Different version!
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=doc_id,
                index=1,
                total=2,
                data=b"b",
            ),
        ]
        with self.assertRaises(ValueError) as ctx:
            reassemble_payload(frames)
        self.assertIn("version", str(ctx.exception).lower())

    def test_large_payload(self) -> None:
        """Test chunking with larger payload (1MB)."""
        payload = b"X" * (1024 * 1024)
        doc_id = b"\x34" * DOC_ID_LEN
        frames = chunk_payload(
            payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=65536
        )
        self.assertGreater(len(frames), 1)
        rebuilt = reassemble_payload(frames)
        self.assertEqual(rebuilt, payload)

    def test_fallback_empty_lines_handling(self) -> None:
        """Test fallback encoding handles various line configurations."""
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x45" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"test",
        )
        # Test with different line lengths
        for line_length in [40, 80, 120]:
            lines = frame_to_fallback_lines(frame, line_length=line_length, line_count=None)
            recovered = fallback_lines_to_frame(lines)
            self.assertEqual(recovered, frame)


if __name__ == "__main__":
    unittest.main()
