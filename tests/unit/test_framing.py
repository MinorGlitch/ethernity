# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

import unittest
import zlib

from ethernity.core.bounds import (
    MAX_AUTH_CBOR_BYTES,
    MAX_MAIN_FRAME_DATA_BYTES,
    MAX_MAIN_FRAME_TOTAL,
    MAX_SHARD_CBOR_BYTES,
)
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
            frame_type=FrameType.MAIN_DOCUMENT,
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

    def test_main_frame_data_accepts_exact_limit(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x05" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"x" * MAX_MAIN_FRAME_DATA_BYTES,
        )
        encoded = encode_frame(frame)
        decoded = decode_frame(encoded)
        self.assertEqual(len(decoded.data), MAX_MAIN_FRAME_DATA_BYTES)

    def test_main_frame_data_rejects_limit_overflow(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x06" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"x" * (MAX_MAIN_FRAME_DATA_BYTES + 1),
        )
        with self.assertRaisesRegex(ValueError, "MAX_MAIN_FRAME_DATA_BYTES"):
            encode_frame(frame)

    def test_main_frame_total_rejects_limit_overflow(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x07" * DOC_ID_LEN,
            index=0,
            total=MAX_MAIN_FRAME_TOTAL + 1,
            data=b"x",
        )
        with self.assertRaisesRegex(ValueError, "MAX_MAIN_FRAME_TOTAL"):
            encode_frame(frame)

    def test_auth_frame_data_rejects_limit_overflow(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=b"\x08" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"a" * (MAX_AUTH_CBOR_BYTES + 1),
        )
        with self.assertRaisesRegex(ValueError, "MAX_AUTH_CBOR_BYTES"):
            encode_frame(frame)

    def test_auth_frame_rejects_non_single_frame_metadata(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=b"\x8a" * DOC_ID_LEN,
            index=1,
            total=2,
            data=b"a",
        )
        with self.assertRaisesRegex(ValueError, "single-frame"):
            encode_frame(frame)

    def test_shard_frame_data_rejects_limit_overflow(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x09" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"s" * (MAX_SHARD_CBOR_BYTES + 1),
        )
        with self.assertRaisesRegex(ValueError, "MAX_SHARD_CBOR_BYTES"):
            encode_frame(frame)

    def test_shard_frame_rejects_non_single_frame_metadata(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x8b" * DOC_ID_LEN,
            index=1,
            total=2,
            data=b"s",
        )
        with self.assertRaisesRegex(ValueError, "single-frame"):
            encode_frame(frame)

    def test_decode_rejects_auth_non_single_frame_metadata(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x8c" * DOC_ID_LEN,
            index=0,
            total=2,
            data=b"auth",
        )
        encoded = bytearray(encode_frame(frame))
        # FRAME_TYPE byte is at MAGIC(2) + VERSION(1).
        encoded[3] = int(FrameType.AUTH)
        body = bytes(encoded[:-4])
        crc = zlib.crc32(body) & 0xFFFFFFFF
        encoded[-4:] = crc.to_bytes(4, "big")
        with self.assertRaisesRegex(ValueError, "single-frame"):
            decode_frame(bytes(encoded))

    def test_decode_rejects_shard_non_single_frame_metadata(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x8d" * DOC_ID_LEN,
            index=0,
            total=2,
            data=b"shard",
        )
        encoded = bytearray(encode_frame(frame))
        # FRAME_TYPE byte is at MAGIC(2) + VERSION(1).
        encoded[3] = int(FrameType.KEY_DOCUMENT)
        body = bytes(encoded[:-4])
        crc = zlib.crc32(body) & 0xFFFFFFFF
        encoded[-4:] = crc.to_bytes(4, "big")
        with self.assertRaisesRegex(ValueError, "single-frame"):
            decode_frame(bytes(encoded))

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

    def test_zero_total_raises(self) -> None:
        """Frame TOTAL must be >= 1."""
        doc_id = b"\x61" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=0,
            data=b"data",
        )
        with self.assertRaises(ValueError) as ctx:
            encode_frame(frame)
        self.assertIn("total", str(ctx.exception).lower())

    def test_decode_unsupported_version_raises(self) -> None:
        """Frame VERSION must match framing.VERSION."""
        doc_id = b"\x62" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"data",
        )
        encoded = bytearray(encode_frame(frame))
        # Modify VERSION uvarint (single byte for values 1/2)
        encoded[2] = 2
        body = bytes(encoded[:-4])
        crc = zlib.crc32(body) & 0xFFFFFFFF
        encoded[-4:] = crc.to_bytes(4, "big")
        with self.assertRaises(ValueError) as ctx:
            decode_frame(bytes(encoded))
        self.assertIn("version", str(ctx.exception).lower())

    def test_decode_unsupported_type_raises(self) -> None:
        """Frame type must be one of the supported constants."""
        doc_id = b"\x63" * DOC_ID_LEN
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"data",
        )
        encoded = bytearray(encode_frame(frame))
        # FRAME_TYPE byte is after MAGIC + VERSION (uvarint(1) = 1 byte)
        encoded[3] = 0x00
        body = bytes(encoded[:-4])
        crc = zlib.crc32(body) & 0xFFFFFFFF
        encoded[-4:] = crc.to_bytes(4, "big")
        with self.assertRaises(ValueError) as ctx:
            decode_frame(bytes(encoded))
        self.assertIn("type", str(ctx.exception).lower())

    def test_decode_rejects_non_canonical_version_varint(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x64" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"data",
        )
        encoded = encode_frame(frame)
        body = encoded[:-4]
        # Replace canonical VERSION=1 (0x01) with overlong encoding (0x81 0x00).
        mutated_body = body[:2] + b"\x81\x00" + body[3:]
        crc = zlib.crc32(mutated_body) & 0xFFFFFFFF
        mutated = mutated_body + crc.to_bytes(4, "big")
        with self.assertRaisesRegex(ValueError, "non-canonical varint"):
            decode_frame(mutated)

    def test_decode_rejects_non_canonical_index_varint(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x65" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"data",
        )
        encoded = encode_frame(frame)
        body = encoded[:-4]
        # INDEX starts after MAGIC(2)+VERSION(1)+FRAME_TYPE(1)+DOC_ID(8) == offset 12.
        mutated_body = body[:12] + b"\x80\x00" + body[13:]
        crc = zlib.crc32(mutated_body) & 0xFFFFFFFF
        mutated = mutated_body + crc.to_bytes(4, "big")
        with self.assertRaisesRegex(ValueError, "non-canonical varint"):
            decode_frame(mutated)

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
