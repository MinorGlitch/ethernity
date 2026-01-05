import tempfile
import unittest
from pathlib import Path

from ethernity.qr_scan import QrScanError, _expand_paths


class TestQrScanInputs(unittest.TestCase):
    def test_missing_path(self) -> None:
        with self.assertRaises(QrScanError):
            list(_expand_paths([Path("does-not-exist")]))

    def test_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(QrScanError):
                list(_expand_paths([Path(tmpdir)]))


if __name__ == "__main__":
    unittest.main()
