import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from ethernity.qr import scan as qr_scan
from ethernity.qr.scan import QrDecoder, QrScanError, _iter_scan_files, _scan_pdf


@contextmanager
def _patched_modules(replacements: dict[str, object]):
    original: dict[str, object | None] = {}
    for name, module in replacements.items():
        original[name] = sys.modules.get(name)
        sys.modules[name] = module
    try:
        yield
    finally:
        for name, module in original.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class TestQrScanMore(unittest.TestCase):
    def test_iter_scan_files_collects_supported_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.png").write_bytes(b"")
            (root / "b.txt").write_text("skip", encoding="utf-8")
            sub = root / "nested"
            sub.mkdir()
            (sub / "c.PDF").write_bytes(b"")
            files = _iter_scan_files(root)
        self.assertEqual([path.name for path in files], ["a.png", "c.PDF"])

    def test_scan_qr_payloads_rejects_unsupported_type(self) -> None:
        decoder = QrDecoder(name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: [])
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "note.txt"
            path.write_text("x", encoding="utf-8")
            original_loader = qr_scan._load_decoder
            qr_scan._load_decoder = lambda: decoder
            try:
                with self.assertRaises(QrScanError):
                    qr_scan.scan_qr_payloads([path])
            finally:
                qr_scan._load_decoder = original_loader

    def test_scan_pdf_decodes_images_and_skips_errors(self) -> None:
        class FakeImage:
            def __init__(self, data: bytes) -> None:
                self.data = data

        class FakePage:
            def __init__(self, images: list[FakeImage]) -> None:
                self.images = images

        class FakeReader:
            def __init__(self, _path: str) -> None:
                self.pages = [
                    FakePage([FakeImage(b"a"), FakeImage(b"b")]),
                    FakePage([FakeImage(b"c")]),
                ]

        def decode_image_bytes(data: bytes) -> list[bytes]:
            if data == b"b":
                raise OSError("bad")
            return [data + b"-ok"]

        decoder = QrDecoder(
            name="dummy",
            decode_image_path=lambda _: [],
            decode_image_bytes=decode_image_bytes,
        )
        pypdf = types.ModuleType("pypdf")
        pypdf.PdfReader = FakeReader
        with _patched_modules({"pypdf": pypdf}):
            payloads = _scan_pdf(Path("dummy.pdf"), decoder)
        self.assertEqual(payloads, [b"a-ok", b"c-ok"])

    def test_scan_pdf_missing_images_attr(self) -> None:
        class FakeReader:
            def __init__(self, _path: str) -> None:
                self.pages = [object()]

        decoder = QrDecoder(name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: [])
        pypdf = types.ModuleType("pypdf")
        pypdf.PdfReader = FakeReader
        with _patched_modules({"pypdf": pypdf}):
            with self.assertRaises(QrScanError):
                _scan_pdf(Path("dummy.pdf"), decoder)

    def test_load_decoder_uses_bytes_and_text(self) -> None:
        def read_barcodes(_image):
            return [
                SimpleNamespace(bytes=b"\x01"),
                SimpleNamespace(raw_bytes=b"\x02"),
                SimpleNamespace(text="hello"),
            ]

        zxingcpp = types.ModuleType("zxingcpp")
        zxingcpp.read_barcodes = read_barcodes

        class DummyImage:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

        def open_fn(_fp):
            return DummyImage()

        image_mod = types.ModuleType("PIL.Image")
        image_mod.open = open_fn
        pil_mod = types.ModuleType("PIL")
        pil_mod.Image = image_mod

        with _patched_modules({"zxingcpp": zxingcpp, "PIL": pil_mod, "PIL.Image": image_mod}):
            decoder = qr_scan._load_decoder()
            payloads = decoder.decode_image_bytes(b"data")
            payloads_path = decoder.decode_image_path(Path("fake.png"))

        self.assertEqual(payloads, [b"\x01", b"\x02", b"hello"])
        self.assertEqual(payloads_path, [b"\x01", b"\x02", b"hello"])


if __name__ == "__main__":
    unittest.main()
