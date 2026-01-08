import unittest

from PIL import Image  # noqa: F401

from ethernity.qr.codec import qr_bytes


class TestQrCodec(unittest.TestCase):
    def test_png_signature(self) -> None:
        data = b"hello"
        png = qr_bytes(data, kind="png")
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_text_payload(self) -> None:
        data = "TEST-123"
        png = qr_bytes(data, kind="png")
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_invalid_shape_raises(self) -> None:
        with self.assertRaises(ValueError):
            qr_bytes(b"data", module_shape="triangle")

    def test_custom_shape_requires_png(self) -> None:
        with self.assertRaises(ValueError):
            qr_bytes(b"data", kind="svg", module_shape="rounded")

    def test_custom_shape_png(self) -> None:
        png = qr_bytes("custom-shape", kind="png", module_shape="rounded")
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
