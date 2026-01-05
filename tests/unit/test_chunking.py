import unittest

from ethernity.chunking import (
    decode_fallback_lines,
    decode_zbase32,
    encode_fallback_lines,
    encode_zbase32,
    fallback_lines_to_frame,
    frame_to_fallback_lines,
    payload_to_fallback_lines,
    reassemble_payload,
    chunk_payload,
)
from ethernity.framing import DOC_ID_LEN, Frame, FrameType


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
        frames = chunk_payload(payload, doc_id=doc_id, frame_type=FrameType.KEY_DOCUMENT, chunk_size=64)
        rebuilt = reassemble_payload(frames)
        self.assertEqual(rebuilt, payload)

    def test_chunk_reassemble_missing(self) -> None:
        payload = b"0123456789" * 20
        doc_id = b"\x33" * DOC_ID_LEN
        frames = chunk_payload(payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=32)
        with self.assertRaises(ValueError):
            reassemble_payload(frames[:-1])

    def test_chunk_payload_balanced(self) -> None:
        payload = b"A" * 10
        doc_id = b"\x55" * DOC_ID_LEN
        frames = chunk_payload(payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=6)
        sizes = [len(frame.data) for frame in frames]
        self.assertEqual(sum(sizes), len(payload))
        self.assertLessEqual(max(sizes) - min(sizes), 1)
        self.assertTrue(all(size <= 6 for size in sizes))

    def test_chunk_reassemble_mismatch(self) -> None:
        payload = b"0123456789" * 20
        doc_id = b"\x44" * DOC_ID_LEN
        frames = chunk_payload(payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT, chunk_size=32)
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


if __name__ == "__main__":
    unittest.main()
