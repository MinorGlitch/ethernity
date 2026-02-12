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

from ethernity.encoding.chunking import DEFAULT_CHUNK_SIZE, chunk_payload
from ethernity.encoding.framing import DOC_ID_LEN, FrameType, encode_frame
from ethernity.encoding.qr_payloads import encode_qr_payload
from ethernity.qr.capacity import choose_frame_chunk_size
from ethernity.qr.codec import QrConfig, make_qr


class TestQrChunkSize(unittest.TestCase):
    def test_choose_frame_chunk_size_scales_down_for_fixed_version(self) -> None:
        payload_len = 5000
        ciphertext = b"\xff" * payload_len
        doc_id = b"\x10" * DOC_ID_LEN
        qr_config = QrConfig(error="L", version=10, micro=False, boost_error=False)

        chunk_size = choose_frame_chunk_size(
            payload_len,
            preferred_chunk_size=DEFAULT_CHUNK_SIZE,
            doc_id=doc_id,
            frame_type=FrameType.MAIN_DOCUMENT,
            qr_config=qr_config,
        )
        self.assertGreater(chunk_size, 0)
        self.assertLessEqual(chunk_size, DEFAULT_CHUNK_SIZE)

        frames = chunk_payload(
            ciphertext,
            doc_id=doc_id,
            frame_type=FrameType.MAIN_DOCUMENT,
            chunk_size=chunk_size,
        )
        self.assertGreater(len(frames), 1)

        for frame in (frames[0], frames[-1]):
            qr_payload = encode_qr_payload(encode_frame(frame))
            make_qr(
                qr_payload,
                error=qr_config.error,
                version=qr_config.version,
                mask=qr_config.mask,
                micro=qr_config.micro,
                boost_error=qr_config.boost_error,
            )

    def test_choose_frame_chunk_size_keeps_default_for_auto_version(self) -> None:
        payload_len = 5000
        doc_id = b"\x22" * DOC_ID_LEN
        qr_config = QrConfig(error="L", version=None, micro=False, boost_error=False)

        chunk_size = choose_frame_chunk_size(
            payload_len,
            preferred_chunk_size=DEFAULT_CHUNK_SIZE,
            doc_id=doc_id,
            frame_type=FrameType.MAIN_DOCUMENT,
            qr_config=qr_config,
        )
        self.assertEqual(chunk_size, DEFAULT_CHUNK_SIZE)

    def test_choose_frame_chunk_size_scales_down_for_auto_version_high_error(self) -> None:
        payload_len = 5000
        ciphertext = b"\xff" * payload_len
        doc_id = b"\x33" * DOC_ID_LEN
        qr_config = QrConfig(error="H", version=None, micro=False, boost_error=False)

        chunk_size = choose_frame_chunk_size(
            payload_len,
            preferred_chunk_size=DEFAULT_CHUNK_SIZE,
            doc_id=doc_id,
            frame_type=FrameType.MAIN_DOCUMENT,
            qr_config=qr_config,
        )
        self.assertGreater(chunk_size, 0)
        self.assertLess(chunk_size, DEFAULT_CHUNK_SIZE)

        frames = chunk_payload(
            ciphertext,
            doc_id=doc_id,
            frame_type=FrameType.MAIN_DOCUMENT,
            chunk_size=chunk_size,
        )
        self.assertGreater(len(frames), 1)

        for frame in (frames[0], frames[-1]):
            qr_payload = encode_qr_payload(encode_frame(frame))
            make_qr(
                qr_payload,
                error=qr_config.error,
                version=qr_config.version,
                mask=qr_config.mask,
                micro=qr_config.micro,
                boost_error=qr_config.boost_error,
            )


if __name__ == "__main__":
    unittest.main()
