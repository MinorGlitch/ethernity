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

import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ethernity.publication import create_sibling_staging_dir
from ethernity.qr import scan as qr_scan
from ethernity.qr.scan import (
    QrDecoder,
    QrScanError,
    _iter_scan_files,
    _scan_pdf,
)


class _FakeImage:
    def __init__(self, data: bytes) -> None:
        self.data = data


class _FakePage:
    def __init__(self, images: list[_FakeImage]) -> None:
        self.images = images


class _FakeReader:
    def __init__(self, _path: str) -> None:
        self.pages = [
            _FakePage([_FakeImage(b"a"), _FakeImage(b"b")]),
            _FakePage([_FakeImage(b"c")]),
        ]


class _FakeReaderMissingImages:
    def __init__(self, _path: str) -> None:
        self.pages = [object()]


def _decode_image_bytes_skip_b(data: bytes) -> list[bytes]:
    if data == b"b":
        raise OSError("bad")
    return [data + b"-ok"]


_QR_CODE_FORMAT = object()


def _read_barcodes(_image, *, formats=None):
    if formats is not _QR_CODE_FORMAT:
        raise AssertionError("expected QR-only format filter")
    return [
        SimpleNamespace(bytes=b"\x01"),
        SimpleNamespace(raw_bytes=b"\x02"),
        SimpleNamespace(text="hello"),
    ]


class _DummyImage:
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


def _open_dummy_image(_fp):
    return _DummyImage()


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
    def test_optional_import_treats_broken_optional_dependency_as_unavailable(self) -> None:
        for exc in (ImportError("broken import"), OSError("broken shared library")):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(qr_scan.importlib, "import_module", side_effect=exc):
                    self.assertIsNone(qr_scan._optional_import("PIL.Image"))

    def test_iter_scan_files_collects_supported_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.png").write_bytes(b"")
            (root / "b.txt").write_text("skip", encoding="utf-8")
            (root / "scan-without-extension").write_bytes(b"%PDF-1.7\n")
            sub = root / "nested"
            sub.mkdir()
            (sub / "c.PDF").write_bytes(b"")
            files = _iter_scan_files(root)
        self.assertEqual(
            [path.name for path in files],
            ["a.png", "c.PDF", "scan-without-extension"],
        )

    def test_iter_scan_files_rejects_too_many_scan_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for index in range(3):
                (root / f"{index}.png").write_bytes(b"")

            with (
                mock.patch.object(qr_scan, "MAX_SCAN_INPUT_FILES", 2),
                self.assertRaisesRegex(QrScanError, "MAX_SCAN_INPUT_FILES"),
            ):
                _iter_scan_files(root)

    def test_iter_scan_files_rejects_symlinked_scan_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "outside.pdf"
            target.write_bytes(b"%PDF-1.7\n")
            link = root / "linked.pdf"
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(QrScanError, "scan file must not be a symlink"):
                _iter_scan_files(root)

    def test_scan_qr_payloads_rejects_explicit_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "outside.pdf"
            target.write_bytes(b"%PDF-1.7\n")
            link = root / "linked.pdf"
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(QrScanError, "scan path must not be a symlink"):
                qr_scan.scan_qr_payloads([link])

    def test_scan_qr_payloads_rejects_oversized_scan_file(self) -> None:
        decoder = QrDecoder(
            name="dummy", decode_image_path=lambda _: [b"ok"], decode_image_bytes=lambda _: []
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "large.png"
            path.write_bytes(b"xx")

            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(qr_scan, "MAX_SCAN_INPUT_BYTES", 1),
                self.assertRaisesRegex(QrScanError, "MAX_SCAN_INPUT_BYTES"),
            ):
                qr_scan.scan_qr_payloads([path])

    def test_scan_qr_payloads_rejects_too_many_decoded_payloads(self) -> None:
        decoder = QrDecoder(
            name="dummy",
            decode_image_path=lambda _: [b"one", b"two"],
            decode_image_bytes=lambda _: [],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scan.png"
            path.write_bytes(b"png-ish")

            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(qr_scan, "MAX_SCAN_QR_PAYLOADS", 1),
                self.assertRaisesRegex(QrScanError, "MAX_SCAN_QR_PAYLOADS"),
            ):
                qr_scan.scan_qr_payloads([path])

    def test_directory_names_and_document_names_do_not_control_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = (
                "extensions/1/renamed.pdf",
                "extensions/folder-without-index/nested/page.png",
                "extensions/extension-99/recovery_document-01-deadbeefcafebabe.pdf",
                "ordinary/notes-02-deadbeefcafebabe.pdf",
            )
            for relative in paths:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")
            (root / "extensions" / "02").write_bytes(b"unrelated data")
            files = _iter_scan_files(root)

        self.assertEqual([path.relative_to(root).as_posix() for path in files], sorted(paths))

    def test_scan_qr_payloads_decodes_all_supplied_directory_content(self) -> None:
        decoder = QrDecoder(
            name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: []
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for relative in ("extensions/01/renamed.pdf", "extensions/another-folder/x.pdf"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"%PDF-1.7\n")
            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(
                    qr_scan, "_scan_pdf", side_effect=lambda path, _decoder: [path.name.encode()]
                ),
            ):
                payloads = qr_scan.scan_qr_payloads([root])

        self.assertCountEqual(payloads, [b"renamed.pdf", b"x.pdf"])

    def test_directory_import_skips_unpublished_staging_without_hiding_explicit_files(self) -> None:
        decoder = QrDecoder(
            name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: []
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            published_pdf = root / "root.pdf"
            published_pdf.write_bytes(b"%PDF-1.7\n")
            staged_dir = create_sibling_staging_dir(root / "rebuilt")
            partial_pdf = staged_dir / "partial.pdf"
            partial_pdf.write_bytes(b"%PDF-1.7\n")
            nested = staged_dir / "nested"
            nested.mkdir()
            (nested / "page.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            stage_named_file = root / ".staging-user-document.pdf"
            stage_named_file.write_bytes(b"%PDF-1.7\n")
            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(
                    qr_scan, "_scan_pdf", side_effect=lambda path, _decoder: [path.name.encode()]
                ) as scan_pdf,
            ):
                directory_payloads = qr_scan.scan_qr_payloads([root])
                self.assertCountEqual(
                    directory_payloads, [b"root.pdf", b".staging-user-document.pdf"]
                )
                self.assertNotIn(mock.call(partial_pdf, decoder), scan_pdf.call_args_list)
                self.assertEqual(_iter_scan_files(staged_dir), [])
                self.assertEqual(_iter_scan_files(nested), [])
                explicit_payloads = qr_scan.scan_qr_payloads([partial_pdf])
                self.assertEqual(explicit_payloads, [b"partial.pdf"])

    def test_blank_directory_carrier_is_ignored_regardless_of_its_name(self) -> None:
        decoder = QrDecoder(
            name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: []
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            root_pdf = root / "qr_document.pdf"
            root_pdf.write_bytes(b"%PDF-1.7\n")
            extension_dir = root / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            extension_pdf = extension_dir / "qr_document-01-deadbeefcafebabe.pdf"
            extension_pdf.write_bytes(b"%PDF-1.7\n")
            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(
                    qr_scan,
                    "_scan_pdf",
                    side_effect=lambda path, _decoder: [b"root"] if path == root_pdf else [],
                ),
            ):
                payloads = qr_scan.scan_qr_payloads([root])

        self.assertEqual(payloads, [b"root"])

    def test_scan_qr_payloads_rejects_blank_explicit_scan_file(self) -> None:
        decoder = QrDecoder(
            name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: []
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            root_pdf = root / "root.pdf"
            loose_extension_pdf = root / "wallet-extension-one.pdf"
            root_pdf.write_bytes(b"%PDF-1.7\n")
            loose_extension_pdf.write_bytes(b"%PDF-1.7\n")

            def fake_scan_pdf(path: Path, _decoder: QrDecoder) -> list[bytes]:
                if path == root_pdf:
                    return [b"root"]
                return []

            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(qr_scan, "_scan_pdf", side_effect=fake_scan_pdf),
                self.assertRaisesRegex(QrScanError, "explicit scan input contains no QR codes"),
            ):
                qr_scan.scan_qr_payloads([root_pdf, loose_extension_pdf])

    def test_scan_qr_payloads_accepts_content_typed_file_without_suffix(self) -> None:
        decoder = QrDecoder(
            name="dummy",
            decode_image_path=lambda path: [Path(path).name.encode()],
            decode_image_bytes=lambda _: [],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "camera-export"
            path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            with mock.patch.object(qr_scan, "_load_decoder", return_value=decoder):
                payloads = qr_scan.scan_qr_payloads([path])
        self.assertEqual(payloads, [b"camera-export"])

    def test_scan_qr_payloads_accepts_content_typed_pdf_without_suffix(self) -> None:
        decoder = QrDecoder(
            name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: []
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "paper-scan"
            path.write_bytes(b"%PDF-1.7\n")
            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(qr_scan, "_scan_pdf", return_value=[b"pdf-payload"]),
            ):
                payloads = qr_scan.scan_qr_payloads([path])
        self.assertEqual(payloads, [b"pdf-payload"])

    def test_scan_qr_payloads_prefers_image_magic_over_pdf_suffix(self) -> None:
        decoder = QrDecoder(
            name="dummy",
            decode_image_path=lambda path: [Path(path).name.encode()],
            decode_image_bytes=lambda _: [],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "camera-export.pdf"
            path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(qr_scan, "_scan_pdf") as scan_pdf,
            ):
                payloads = qr_scan.scan_qr_payloads([path])
        self.assertEqual(payloads, [b"camera-export.pdf"])
        scan_pdf.assert_not_called()

    def test_scan_qr_payloads_prefers_pdf_magic_over_image_suffix(self) -> None:
        decoder = QrDecoder(
            name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: []
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "paper-scan.png"
            path.write_bytes(b"%PDF-1.7\n")
            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(qr_scan, "_scan_pdf", return_value=[b"pdf-payload"]),
            ):
                payloads = qr_scan.scan_qr_payloads([path])
        self.assertEqual(payloads, [b"pdf-payload"])

    def test_scan_qr_payloads_rejects_unsupported_type(self) -> None:
        decoder = QrDecoder(
            name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: []
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "note.txt"
            path.write_text("x", encoding="utf-8")
            with mock.patch.object(qr_scan, "_load_decoder", return_value=decoder):
                with self.assertRaises(QrScanError):
                    qr_scan.scan_qr_payloads([path])

    def test_scan_pdf_decodes_images_and_skips_errors(self) -> None:
        decoder = QrDecoder(
            name="dummy",
            decode_image_path=lambda _: [],
            decode_image_bytes=_decode_image_bytes_skip_b,
        )
        pypdf = types.ModuleType("pypdf")
        pypdf.PdfReader = _FakeReader
        with _patched_modules({"pypdf": pypdf}):
            payloads = _scan_pdf(Path("dummy.pdf"), decoder)
        self.assertEqual(payloads, [b"a-ok", b"c-ok"])

    def test_scan_pdf_enforces_page_image_and_embedded_byte_limits(self) -> None:
        decoder = QrDecoder(
            name="dummy",
            decode_image_path=lambda _: [],
            decode_image_bytes=lambda data: [data],
        )
        pypdf = types.ModuleType("pypdf")
        pypdf.PdfReader = _FakeReader
        with _patched_modules({"pypdf": pypdf}):
            with (
                mock.patch.object(qr_scan, "MAX_SCAN_PDF_PAGES", 1),
                self.assertRaisesRegex(QrScanError, "MAX_SCAN_PDF_PAGES"),
            ):
                _scan_pdf(Path("dummy.pdf"), decoder)
            with (
                mock.patch.object(qr_scan, "MAX_SCAN_PDF_IMAGES", 2),
                self.assertRaisesRegex(QrScanError, "MAX_SCAN_PDF_IMAGES"),
            ):
                _scan_pdf(Path("dummy.pdf"), decoder)
            with (
                mock.patch.object(qr_scan, "MAX_SCAN_PDF_IMAGE_BYTES", 0),
                self.assertRaisesRegex(QrScanError, "MAX_SCAN_PDF_IMAGE_BYTES"),
            ):
                _scan_pdf(Path("dummy.pdf"), decoder)

    def test_scan_pdf_missing_images_attr(self) -> None:
        decoder = QrDecoder(
            name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: []
        )
        pypdf = types.ModuleType("pypdf")
        pypdf.PdfReader = _FakeReaderMissingImages
        with _patched_modules({"pypdf": pypdf}):
            with self.assertRaises(QrScanError):
                _scan_pdf(Path("dummy.pdf"), decoder)

    def test_load_decoder_uses_bytes_and_text(self) -> None:
        zxingcpp = types.ModuleType("zxingcpp")
        zxingcpp.read_barcodes = _read_barcodes
        zxingcpp.BarcodeFormat = SimpleNamespace(QRCode=_QR_CODE_FORMAT)

        image_mod = types.ModuleType("PIL.Image")
        image_mod.open = _open_dummy_image
        pil_mod = types.ModuleType("PIL")
        pil_mod.Image = image_mod

        with _patched_modules({"zxingcpp": zxingcpp, "PIL": pil_mod, "PIL.Image": image_mod}):
            decoder = qr_scan._load_decoder()
            payloads = decoder.decode_image_bytes(b"data")
            payloads_path = decoder.decode_image_path(Path("fake.png"))

        self.assertEqual(payloads, [b"\x01", b"\x02", b"hello"])
        self.assertEqual(payloads_path, [b"\x01", b"\x02", b"hello"])

    def test_load_decoder_rejects_missing_pillow_lazily(self) -> None:
        with (
            mock.patch.object(qr_scan, "pil_image", None),
            mock.patch.dict(sys.modules, {"PIL.Image": None}),
        ):
            with self.assertRaisesRegex(QrScanError, "Pillow is required"):
                qr_scan._load_decoder()


if __name__ == "__main__":
    unittest.main()
