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
from types import SimpleNamespace

from ethernity.core.bounds import MAX_QR_PAYLOAD_CHARS
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType, encode_frame
from ethernity.encoding.qr_payloads import (
    decode_qr_payload,
    encode_qr_payload,
)
from ethernity.render.service import RenderService


class TestQrPayloads(unittest.TestCase):
    def test_roundtrip_base64(self) -> None:
        data = b"\x00\xffpayload"
        encoded = encode_qr_payload(data)
        self.assertIsInstance(encoded, str)
        decoded = decode_qr_payload(encoded)
        self.assertEqual(decoded, data)
        decoded_bytes = decode_qr_payload(encoded.encode("ascii"))
        self.assertEqual(decoded_bytes, data)

    def test_decode_rejects_invalid_base64(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid base64 QR payload"):
            decode_qr_payload("not-base64@@")

    def test_decode_rejects_padded_base64(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid base64 QR payload"):
            decode_qr_payload("YQ==")

    def test_render_service_qr_payload_bound(self) -> None:
        config = SimpleNamespace()
        service = RenderService(config=config)  # type: ignore[arg-type]

        max_frame: Frame | None = None
        overflow_frame: Frame | None = None

        for size in range(1, 20_000):
            frame = Frame(
                version=VERSION,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x01" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"x" * size,
            )
            payload = encode_qr_payload(encode_frame(frame))
            text = payload.decode("ascii") if isinstance(payload, bytes) else payload
            if len(text) <= MAX_QR_PAYLOAD_CHARS:
                max_frame = frame
                continue
            overflow_frame = frame
            break

        self.assertIsNotNone(max_frame)
        self.assertIsNotNone(overflow_frame)

        payload = service.build_qr_payloads([max_frame])[0]  # type: ignore[arg-type]
        payload_text = payload.decode("ascii") if isinstance(payload, bytes) else payload
        self.assertLessEqual(len(payload_text), MAX_QR_PAYLOAD_CHARS)

        with self.assertRaisesRegex(ValueError, "MAX_QR_PAYLOAD_CHARS"):
            service.build_qr_payloads([overflow_frame])  # type: ignore[list-item]


if __name__ == "__main__":
    unittest.main()
