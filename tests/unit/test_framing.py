import unittest

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType, decode_frame, encode_frame


class TestFraming(unittest.TestCase):
    def test_roundtrip(self) -> None:
        doc_id = b"\x01" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"payload",
        )

        encoded = encode_frame(frame)
        decoded = decode_frame(encoded)

        self.assertEqual(decoded.version, frame.version)
        self.assertEqual(decoded.frame_type, frame.frame_type)
        self.assertEqual(decoded.doc_id, frame.doc_id)
        self.assertEqual(decoded.index, frame.index)
        self.assertEqual(decoded.total, frame.total)
        self.assertEqual(decoded.data, frame.data)

    def test_invalid_doc_id_length(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x01",
            index=0,
            total=1,
            data=b"payload",
        )
        with self.assertRaises(ValueError):
            encode_frame(frame)

    def test_crc_mismatch(self) -> None:
        doc_id = b"\x02" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"payload",
        )
        encoded = bytearray(encode_frame(frame))
        encoded[-1] ^= 0xFF
        with self.assertRaises(ValueError):
            decode_frame(bytes(encoded))

    def test_bad_magic(self) -> None:
        doc_id = b"\x03" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.CHECKSUM,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"payload",
        )
        encoded = bytearray(encode_frame(frame))
        encoded[0] = 0x00
        with self.assertRaises(ValueError):
            decode_frame(bytes(encoded))

    def test_index_out_of_range(self) -> None:
        doc_id = b"\x04" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=2,
            total=2,
            data=b"payload",
        )
        with self.assertRaises(ValueError):
            encode_frame(frame)

    # ==========================================================================
    # Edge Case Tests
    # ==========================================================================

    def test_all_frame_types(self) -> None:
        """Test encoding/decoding works for all frame types."""
        doc_id = b"\x10" * DOC_ID_LEN
        for frame_type in FrameType:
            frame = Frame(
                version=1,
                frame_type=frame_type,
                doc_id=doc_id,
                index=0,
                total=1,
                data=b"test",
            )
            encoded = encode_frame(frame)
            decoded = decode_frame(encoded)
            self.assertEqual(decoded.frame_type, frame_type)

    def test_large_data(self) -> None:
        """Test frame with large data payload (64KB)."""
        doc_id = b"\x20" * DOC_ID_LEN
        large_data = b"X" * 65536
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=large_data,
        )
        encoded = encode_frame(frame)
        decoded = decode_frame(encoded)
        self.assertEqual(decoded.data, large_data)

    def test_max_index_and_total(self) -> None:
        """Test frame with large index and total values."""
        doc_id = b"\x30" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=999,
            total=1000,
            data=b"data",
        )
        encoded = encode_frame(frame)
        decoded = decode_frame(encoded)
        self.assertEqual(decoded.index, 999)
        self.assertEqual(decoded.total, 1000)

    def test_negative_version_raises(self) -> None:
        """Test that negative version raises ValueError."""
        doc_id = b"\x40" * DOC_ID_LEN
        frame = Frame(
            version=-1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"data",
        )
        with self.assertRaises(ValueError) as ctx:
            encode_frame(frame)
        self.assertIn("version", str(ctx.exception).lower())

    def test_negative_index_raises(self) -> None:
        """Test that negative index raises ValueError."""
        doc_id = b"\x50" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=-1,
            total=1,
            data=b"data",
        )
        with self.assertRaises(ValueError) as ctx:
            encode_frame(frame)
        self.assertIn("index", str(ctx.exception).lower())

    def test_negative_total_raises(self) -> None:
        """Test that negative total raises ValueError."""
        doc_id = b"\x60" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=-1,
            data=b"data",
        )
        with self.assertRaises(ValueError) as ctx:
            encode_frame(frame)
        self.assertIn("total", str(ctx.exception).lower())

    def test_decode_truncated_frame(self) -> None:
        """Test decoding truncated frame raises ValueError."""
        doc_id = b"\x70" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"payload",
        )
        encoded = encode_frame(frame)
        # Truncate at various points
        for length in [1, 5, 10, len(encoded) // 2]:
            with self.assertRaises(ValueError):
                decode_frame(encoded[:length])

    def test_decode_empty_data_raises(self) -> None:
        """Test decoding frame with empty payload (too short)."""
        with self.assertRaises(ValueError) as ctx:
            decode_frame(b"")
        self.assertIn("short", str(ctx.exception).lower())

    def test_decode_just_magic_raises(self) -> None:
        """Test decoding just magic bytes raises ValueError."""
        with self.assertRaises(ValueError):
            decode_frame(b"AP")

    def test_binary_data_roundtrip(self) -> None:
        """Test frame with all possible byte values in data."""
        doc_id = b"\x80" * DOC_ID_LEN
        all_bytes = bytes(range(256))
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=all_bytes,
        )
        encoded = encode_frame(frame)
        decoded = decode_frame(encoded)
        self.assertEqual(decoded.data, all_bytes)

    def test_zero_doc_id(self) -> None:
        """Test frame with all-zero doc_id."""
        doc_id = b"\x00" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"data",
        )
        encoded = encode_frame(frame)
        decoded = decode_frame(encoded)
        self.assertEqual(decoded.doc_id, doc_id)

    def test_max_byte_doc_id(self) -> None:
        """Test frame with all-0xFF doc_id."""
        doc_id = b"\xff" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"data",
        )
        encoded = encode_frame(frame)
        decoded = decode_frame(encoded)
        self.assertEqual(decoded.doc_id, doc_id)

    def test_single_frame_total_one(self) -> None:
        """Test single frame (index=0, total=1)."""
        doc_id = b"\x90" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"single",
        )
        encoded = encode_frame(frame)
        decoded = decode_frame(encoded)
        self.assertEqual(decoded.index, 0)
        self.assertEqual(decoded.total, 1)

    def test_corrupted_data_detected(self) -> None:
        """Test that corrupted data is detected (either via CRC or length check)."""
        doc_id = b"\xa0" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"important data",
        )
        encoded = bytearray(encode_frame(frame))
        # Corrupt byte in middle - may fail with CRC or length mismatch
        encoded[len(encoded) // 2] ^= 0xFF
        with self.assertRaises(ValueError):
            decode_frame(bytes(encoded))

    def test_corrupted_crc_fails(self) -> None:
        """Test that corrupting CRC specifically fails CRC check."""
        doc_id = b"\xb0" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"test data",
        )
        encoded = bytearray(encode_frame(frame))
        # Corrupt the last byte (part of CRC)
        encoded[-1] ^= 0xFF
        with self.assertRaises(ValueError) as ctx:
            decode_frame(bytes(encoded))
        self.assertIn("crc", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
