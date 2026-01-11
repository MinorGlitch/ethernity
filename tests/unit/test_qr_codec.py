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
    def test_png_signature(self) -> None:
        """Test that generated PNG has valid signature."""
        data = b"hello"
        png = qr_bytes(data, kind="png")
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
    def test_bytes_payload_decodable(self) -> None:
        """Test that binary payload QR code can be decoded back."""
        data = b"hello-binary"
        png = qr_bytes(data, kind="png")
        decoded = decode_qr_from_bytes(png)
        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0], data)

    @unittest.skipUnless(HAS_ZXING, "zxingcpp not available")
    def test_text_payload_decodable(self) -> None:
        """Test that text payload QR code can be decoded back."""
        data = "TEST-123"
        png = qr_bytes(data, kind="png")
        decoded = decode_qr_from_bytes(png)
        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0], data.encode("utf-8"))

    def test_text_payload(self) -> None:
        """Test that text payload generates valid PNG."""
        data = "TEST-123"
        png = qr_bytes(data, kind="png")
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_invalid_shape_raises(self) -> None:
        """Test that invalid module shape raises ValueError."""
        with self.assertRaises(ValueError):
            qr_bytes(b"data", module_shape="triangle")

    def test_custom_shape_requires_png(self) -> None:
        """Test that custom shapes require PNG output."""
        with self.assertRaises(ValueError):
            qr_bytes(b"data", kind="svg", module_shape="rounded")

    @unittest.skipUnless(HAS_ZXING, "zxingcpp not available")
    def test_custom_shape_png_decodable(self) -> None:
        """Test that custom shape QR code can be decoded."""
        data = b"custom-shape-data"
        png = qr_bytes(data, kind="png", module_shape="rounded")
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        decoded = decode_qr_from_bytes(png)
        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0], data)

    def test_custom_shape_png(self) -> None:
        """Test custom shape generates valid PNG."""
        png = qr_bytes("custom-shape", kind="png", module_shape="rounded")
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

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
    def test_various_scale_values(self) -> None:
        """Test QR generation with different scale values."""
        data = b"scale-test"
        for scale in [1, 4, 10]:
            png = qr_bytes(data, kind="png", scale=scale)
            decoded = decode_qr_from_bytes(png)
            self.assertEqual(decoded[0], data, f"Failed for scale={scale}")

    @unittest.skipUnless(HAS_ZXING, "zxingcpp not available")
    def test_various_border_values(self) -> None:
        """Test QR generation with different border values."""
        data = b"border-test"
        for border in [0, 2, 4, 8]:
            png = qr_bytes(data, kind="png", border=border)
            decoded = decode_qr_from_bytes(png)
            self.assertEqual(decoded[0], data, f"Failed for border={border}")


if __name__ == "__main__":
    unittest.main()
