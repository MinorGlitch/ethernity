import tempfile
import unittest
from pathlib import Path

from ethernity.qr import scan as qr_scan
from ethernity.qr.scan import QrDecoder, QrScanError


class _DecoderFactory:
    def __init__(self, decoder: QrDecoder) -> None:
        self._decoder = decoder

    def __call__(self) -> QrDecoder:
        return self._decoder


def _decode_empty(_value):
    return []


def _decode_raises(_value):
    raise OSError("bad image")


class TestQrScanErrors(unittest.TestCase):
    def test_no_payloads_found(self) -> None:
        decoder = QrDecoder(
            name="dummy",
            decode_image_path=_decode_empty,
            decode_image_bytes=_decode_empty,
        )
        original_loader = qr_scan._load_decoder
        qr_scan._load_decoder = _DecoderFactory(decoder)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "test.png"
                path.write_bytes(b"")
                with self.assertRaises(QrScanError):
                    qr_scan.scan_qr_payloads([path])
        finally:
            qr_scan._load_decoder = original_loader

    def test_decode_error_raises(self) -> None:
        decoder = QrDecoder(
            name="dummy",
            decode_image_path=_decode_raises,
            decode_image_bytes=_decode_empty,
        )
        original_loader = qr_scan._load_decoder
        qr_scan._load_decoder = _DecoderFactory(decoder)
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
