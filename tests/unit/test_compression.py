import unittest

from ethernity.formats.compression import MAGIC, unwrap_payload, wrap_payload
from ethernity.formats.compression import CompressionConfig


class TestCompression(unittest.TestCase):
    def test_wrap_unwrap_none(self) -> None:
        config = CompressionConfig(enabled=False, algorithm="zstd", level=3)
        payload = b"sample data"
        wrapped, info = wrap_payload(payload, config)
        self.assertTrue(wrapped.startswith(MAGIC))
        self.assertFalse(info.compressed)
        unwrapped, out_info = unwrap_payload(wrapped)
        self.assertEqual(unwrapped, payload)
        self.assertEqual(out_info.algorithm, "none")

    def test_wrap_unwrap_zstd(self) -> None:
        try:
            import zstandard  # noqa: F401
        except ImportError:
            self.skipTest("zstandard not installed")
        config = CompressionConfig(enabled=True, algorithm="zstd", level=3)
        payload = b"sample data" * 50
        wrapped, info = wrap_payload(payload, config)
        self.assertTrue(wrapped.startswith(MAGIC))
        self.assertTrue(info.compressed)
        unwrapped, out_info = unwrap_payload(wrapped)
        self.assertEqual(unwrapped, payload)
        self.assertEqual(out_info.algorithm, "zstd")


if __name__ == "__main__":
    unittest.main()
