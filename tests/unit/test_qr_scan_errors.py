import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.qr import scan as qr_scan
from ethernity.qr.scan import QrDecoder, QrScanError


def _decode_empty(_value):
    """Mock decoder that returns no payloads."""
    return []


def _decode_raises(_value):
    """Mock decoder that raises an error."""
    raise OSError("bad image")


def _decode_single(_value):
    """Mock decoder that returns a single payload."""
    return [b"decoded-payload"]


def _make_mock_decoder(
    *,
    decode_path=_decode_empty,
    decode_bytes=_decode_empty,
    name="mock-decoder",
) -> QrDecoder:
    """Create a mock QrDecoder with specified behaviors."""
    return QrDecoder(
        name=name,
        decode_image_path=decode_path,
        decode_image_bytes=decode_bytes,
    )


class TestQrScanErrors(unittest.TestCase):
    """Tests for QR scanning error handling with proper test isolation."""

    def test_no_payloads_found(self) -> None:
        """Test that QrScanError is raised when no QR codes are found."""
        mock_decoder = _make_mock_decoder(
            decode_path=_decode_empty,
            decode_bytes=_decode_empty,
        )
        with mock.patch.object(qr_scan, "_load_decoder", return_value=mock_decoder):
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "test.png"
                path.write_bytes(b"fake-png-content")
                with self.assertRaises(QrScanError) as ctx:
                    qr_scan.scan_qr_payloads([path])
                # Error message may be "no qr codes" or similar
                self.assertIn("no", str(ctx.exception).lower())

    def test_decode_error_raises(self) -> None:
        """Test that decode errors are wrapped in QrScanError."""
        mock_decoder = _make_mock_decoder(
            decode_path=_decode_raises,
            decode_bytes=_decode_empty,
        )
        with mock.patch.object(qr_scan, "_load_decoder", return_value=mock_decoder):
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "bad.png"
                path.write_bytes(b"fake-png-content")
                with self.assertRaises(QrScanError):
                    qr_scan.scan_qr_payloads([path])

    def test_successful_decode(self) -> None:
        """Test successful QR decoding returns payloads."""
        mock_decoder = _make_mock_decoder(
            decode_path=_decode_single,
            decode_bytes=_decode_single,
        )
        with mock.patch.object(qr_scan, "_load_decoder", return_value=mock_decoder):
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "valid.png"
                path.write_bytes(b"fake-png-content")
                payloads = qr_scan.scan_qr_payloads([path])
                self.assertEqual(payloads, [b"decoded-payload"])

    def test_multiple_files(self) -> None:
        """Test scanning multiple files collects all payloads."""
        call_count = [0]

        def _decode_with_index(_value):
            call_count[0] += 1
            return [f"payload-{call_count[0]}".encode()]

        mock_decoder = _make_mock_decoder(
            decode_path=_decode_with_index,
            decode_bytes=_decode_with_index,
        )
        with mock.patch.object(qr_scan, "_load_decoder", return_value=mock_decoder):
            with tempfile.TemporaryDirectory() as tmpdir:
                paths = []
                for i in range(3):
                    path = Path(tmpdir) / f"file{i}.png"
                    path.write_bytes(b"fake-png-content")
                    paths.append(path)
                payloads = qr_scan.scan_qr_payloads(paths)
                self.assertEqual(len(payloads), 3)

    def test_empty_file_list(self) -> None:
        """Test scanning empty file list raises error."""
        mock_decoder = _make_mock_decoder()
        with mock.patch.object(qr_scan, "_load_decoder", return_value=mock_decoder):
            with self.assertRaises(QrScanError):
                qr_scan.scan_qr_payloads([])


if __name__ == "__main__":
    unittest.main()
