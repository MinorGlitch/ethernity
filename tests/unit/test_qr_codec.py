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

import io
import unittest

from PIL import Image

from ethernity.qr.codec import qr_bytes

# Try to import zxingcpp for QR decoding verification
try:
    import zxingcpp

    HAS_ZXING = True
except ImportError:
    HAS_ZXING = False


def decode_qr_from_bytes(png_data: bytes) -> list[bytes]:
    """Decode QR code(s) from PNG bytes, returning list of payloads."""
    if not HAS_ZXING:
        return []
    with Image.open(io.BytesIO(png_data)) as img:
        results = zxingcpp.read_barcodes(img)
        payloads = []
        for result in results:
            data = getattr(result, "bytes", None) or getattr(result, "raw_bytes", None)
            if data:
                payloads.append(bytes(data))
            elif getattr(result, "text", None):
                payloads.append(result.text.encode("utf-8"))
        return payloads


class TestQrCodec(unittest.TestCase):
    def test_png_signature_for_bytes_and_text_payloads(self) -> None:
        """Generated PNG bytes should start with a valid PNG signature."""
        payloads = (
            b"hello",
            "TEST-123",
        )
        for payload in payloads:
            with self.subTest(payload_type=type(payload).__name__):
                png = qr_bytes(payload, kind="png")
                self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_png_is_valid_image(self) -> None:
        """Test that generated PNG can be opened as an image."""
        data = b"test-data"
        png = qr_bytes(data, kind="png")
        with Image.open(io.BytesIO(png)) as img:
            self.assertEqual(img.format, "PNG")
            self.assertGreater(img.width, 0)
            self.assertGreater(img.height, 0)

    @unittest.skipUnless(HAS_ZXING, "zxingcpp not available")
    def test_payload_decodable_cases(self) -> None:
        """Binary and text payloads should round-trip through QR encode/decode."""
        cases = (
            (b"hello-binary", b"hello-binary"),
            ("TEST-123", b"TEST-123"),
        )
        for payload, expected in cases:
            with self.subTest(payload_type=type(payload).__name__):
                png = qr_bytes(payload, kind="png")
                decoded = decode_qr_from_bytes(png)
                self.assertEqual(len(decoded), 1)
                self.assertEqual(decoded[0], expected)

    def test_module_shape_argument_rejected(self) -> None:
        """Test that module_shape argument is not supported."""
        with self.assertRaises(TypeError):
            qr_bytes(b"data", module_shape="rounded")  # type: ignore[call-arg]

    @unittest.skipUnless(HAS_ZXING, "zxingcpp not available")
    def test_binary_all_bytes_decodable(self) -> None:
        """Test QR code with all possible byte values can be decoded."""
        data = bytes(range(256))
        png = qr_bytes(data, kind="png")
        decoded = decode_qr_from_bytes(png)
        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0], data)

    def test_svg_output(self) -> None:
        """Test SVG output format."""
        data = b"svg-test"
        svg = qr_bytes(data, kind="svg")
        self.assertTrue(svg.startswith(b"<?xml") or svg.startswith(b"<svg"))
        self.assertIn(b"</svg>", svg)

    @unittest.skipUnless(HAS_ZXING, "zxingcpp not available")
    def test_option_variants_remain_decodable(self) -> None:
        data = b"option-test"
        cases = (
            ("scale", {"scale": 1}),
            ("scale", {"scale": 4}),
            ("scale", {"scale": 10}),
            ("border", {"border": 0}),
            ("border", {"border": 2}),
            ("border", {"border": 4}),
            ("border", {"border": 8}),
        )
        for label, kwargs in cases:
            with self.subTest(label=label, kwargs=kwargs):
                png = qr_bytes(data, kind="png", **kwargs)
                decoded = decode_qr_from_bytes(png)
                self.assertEqual(decoded[0], data)


if __name__ == "__main__":
    unittest.main()
