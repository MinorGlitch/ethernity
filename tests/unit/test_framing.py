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


if __name__ == "__main__":
    unittest.main()
