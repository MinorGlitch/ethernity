import unittest

import tempfile
from pathlib import Path

from ethernity.qr import scan as qr_scan
from ethernity.qr.scan import QrDecoder, QrScanError


class TestQrScanErrors(unittest.TestCase):
    def test_no_payloads_found(self) -> None:
        def decode_path(_path):
            return []

        def decode_bytes(_data):
            return []

        decoder = QrDecoder(
            name="dummy",
            decode_image_path=decode_path,
            decode_image_bytes=decode_bytes,
        )
        original_loader = qr_scan._load_decoder
        qr_scan._load_decoder = lambda: decoder
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "test.png"
                path.write_bytes(b"")
                with self.assertRaises(QrScanError):
                    qr_scan.scan_qr_payloads([path])
        finally:
            qr_scan._load_decoder = original_loader

    def test_decode_error_raises(self) -> None:
        def decode_path(_path):
            raise OSError("bad image")

        def decode_bytes(_data):
            return []

        decoder = QrDecoder(
            name="dummy",
            decode_image_path=decode_path,
            decode_image_bytes=decode_bytes,
        )
        original_loader = qr_scan._load_decoder
        qr_scan._load_decoder = lambda: decoder
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "bad.png"
                path.write_bytes(b"")
                with self.assertRaises(QrScanError):
                    qr_scan.scan_qr_payloads([path])
        finally:
            qr_scan._load_decoder = original_loader


if __name__ == "__main__":
    unittest.main()
