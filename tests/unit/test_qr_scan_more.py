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

from ethernity.qr import scan as qr_scan
from ethernity.qr.scan import (
    QrDecoder,
    QrScanError,
    _is_under_unpublished_extension_workspace,
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

    def test_iter_scan_files_ignores_unpublished_extension_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            published = root / "extensions" / "01"
            published.mkdir(parents=True)
            (published / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"")
            staging = root / "extensions" / ".staging-2-aborted"
            staging.mkdir(parents=True)
            (staging / "qr_document-02-cafebabedeadbeef.pdf").write_bytes(b"")
            nested_staging = staging / "nested"
            nested_staging.mkdir()
            (nested_staging / "recovery_document-02-cafebabedeadbeef.pdf").write_bytes(b"")
            crash_staging = root / "extensions" / ".staging-crash"
            crash_staging.mkdir()
            (crash_staging / "qr_document-99-feedfacecafebeef.pdf").write_bytes(b"")
            ordinary_staging = root / "loose" / ".staging-2-aborted"
            ordinary_staging.mkdir(parents=True)
            (ordinary_staging / "loose-carrier.pdf").write_bytes(b"")

            files = _iter_scan_files(root)
            staged_files = _iter_scan_files(staging)

        self.assertEqual(
            [path.relative_to(root).as_posix() for path in files],
            [
                "extensions/01/qr_document-01-deadbeefcafebabe.pdf",
                "loose/.staging-2-aborted/loose-carrier.pdf",
            ],
        )
        self.assertEqual(staged_files, [])

    def test_iter_scan_files_rejects_extension_like_top_level_entries(self) -> None:
        for entry_name, is_dir in (
            ("extension-01", True),
            ("1", True),
            ("qr_document-01-deadbeefcafebabe.pdf", False),
        ):
            with self.subTest(entry_name=entry_name):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    (root / "qr_document.pdf").write_bytes(b"%PDF-1.7\n")
                    extensions = root / "extensions"
                    extensions.mkdir()
                    entry = extensions / entry_name
                    if is_dir:
                        entry.mkdir()
                    else:
                        entry.write_bytes(b"%PDF-1.7\n")

                    with self.assertRaisesRegex(
                        QrScanError,
                        "unexpected extension-like top-level entry",
                    ):
                        _iter_scan_files(root)

    def test_iter_scan_files_rejects_nested_extension_like_top_level_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nested_backup = root / "nested-backup"
            nested_backup.mkdir()
            (nested_backup / "qr_document.pdf").write_bytes(b"%PDF-1.7\n")
            extensions = nested_backup / "extensions"
            extensions.mkdir()
            (extensions / "extension-01").mkdir()

            with self.assertRaisesRegex(
                QrScanError,
                "unexpected extension-like top-level entry",
            ):
                _iter_scan_files(root)

    def test_iter_scan_files_can_exclude_published_extension_carriers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "qr_document.pdf").write_bytes(b"%PDF-1.7\n")
            extension_dir = root / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (extension_dir / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"%PDF-1.7\n")

            files = _iter_scan_files(root, include_extension_carriers=False)

        self.assertEqual([path.relative_to(root).as_posix() for path in files], ["qr_document.pdf"])

    def test_iter_scan_files_root_only_rejects_symlinked_canonical_extension_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            external = Path(tmpdir) / "external"
            root.mkdir()
            external.mkdir()
            (root / "qr_document.pdf").write_bytes(b"%PDF-1.7\n")
            extensions_dir = root / "extensions"
            extensions_dir.mkdir()
            try:
                (extensions_dir / "01").symlink_to(external, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(
                QrScanError,
                "extensions directory must not contain symlinked entries",
            ):
                _iter_scan_files(root, include_extension_carriers=False)

    def test_iter_scan_files_can_bound_published_extension_carriers_by_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "qr_document.pdf").write_bytes(b"%PDF-1.7\n")
            extension_01 = root / "extensions" / "01"
            extension_02 = root / "extensions" / "02"
            extension_01.mkdir(parents=True)
            extension_02.mkdir()
            (extension_01 / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"%PDF-1.7\n")
            (extension_02 / "qr_document-02-cafebabedeadbeef.pdf").write_bytes(b"%PDF-1.7\n")
            (extension_02 / "recovery_document-02-cafebabedeadbeef.pdf").write_bytes(b"%PDF-1.7\n")

            files = _iter_scan_files(root, extension_carrier_max_index=1)

        self.assertEqual(
            [path.relative_to(root).as_posix() for path in files],
            [
                "extensions/01/qr_document-01-deadbeefcafebabe.pdf",
                "qr_document.pdf",
            ],
        )

    def test_iter_scan_files_tolerates_future_malformed_extension_entries_when_bounded(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "qr_document.pdf").write_bytes(b"%PDF-1.7\n")
            extension_01 = root / "extensions" / "01"
            extension_01.mkdir(parents=True)
            (extension_01 / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"%PDF-1.7\n")
            (root / "extensions" / "02").write_bytes(b"not a directory")

            files = _iter_scan_files(root, extension_carrier_max_index=1)

        self.assertEqual(
            [path.relative_to(root).as_posix() for path in files],
            [
                "extensions/01/qr_document-01-deadbeefcafebabe.pdf",
                "qr_document.pdf",
            ],
        )

    def test_iter_scan_files_excludes_nested_published_extension_carriers_for_root_only(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nested_backup = root / "nested-backup"
            nested_backup.mkdir()
            (nested_backup / "qr_document.pdf").write_bytes(b"%PDF-1.7\n")
            extension_dir = nested_backup / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (extension_dir / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"%PDF-1.7\n")

            files = _iter_scan_files(root, include_extension_carriers=False)

        self.assertEqual(
            [path.relative_to(root).as_posix() for path in files],
            ["nested-backup/qr_document.pdf"],
        )

    def test_iter_scan_files_uses_only_payload_main_carriers_in_published_extensions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            extension_dir = root / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (extension_dir / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"%PDF-1.7\n")
            (extension_dir / "recovery_document-01-deadbeefcafebabe.pdf").write_bytes(b"%PDF-1.7\n")
            (extension_dir / "recovery_kit_index-01-deadbeefcafebabe.pdf").write_bytes(
                b"%PDF-1.7\n"
            )
            loose = root / "loose"
            loose.mkdir()
            (loose / "recovery_document-01-deadbeefcafebabe.pdf").write_bytes(b"%PDF-1.7\n")

            files = _iter_scan_files(root)

        self.assertEqual(
            [path.relative_to(root).as_posix() for path in files],
            [
                "extensions/01/qr_document-01-deadbeefcafebabe.pdf",
                "loose/recovery_document-01-deadbeefcafebabe.pdf",
            ],
        )

    def test_iter_scan_files_rejects_canonical_extension_entry_that_is_not_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "qr_document.pdf").write_bytes(b"%PDF-1.7\n")
            extensions_dir = root / "extensions"
            extensions_dir.mkdir()
            (extensions_dir / "01").write_bytes(b"not a directory")

            with self.assertRaisesRegex(
                QrScanError,
                "canonical extension entry must be a directory",
            ):
                _iter_scan_files(root)

    def test_iter_scan_files_rejects_canonical_extension_dir_without_qr_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "qr_document.pdf").write_bytes(b"%PDF-1.7\n")
            extension_dir = root / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (extension_dir / "recovery_document-01-deadbeefcafebabe.pdf").write_bytes(b"%PDF-1.7\n")

            with self.assertRaisesRegex(
                QrScanError,
                "canonical extension directory is missing its QR document carrier",
            ):
                _iter_scan_files(root)

    def test_iter_scan_files_rejects_extension_dir_with_mismatched_qr_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "qr_document.pdf").write_bytes(b"%PDF-1.7\n")
            extension_dir = root / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (extension_dir / "qr_document-02-deadbeefcafebabe.pdf").write_bytes(b"%PDF-1.7\n")

            with self.assertRaisesRegex(
                QrScanError,
                "canonical extension directory is missing its QR document carrier",
            ):
                _iter_scan_files(root)

    def test_iter_scan_files_root_only_can_ignore_extension_dir_without_qr_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "qr_document.pdf").write_bytes(b"%PDF-1.7\n")
            extension_dir = root / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (extension_dir / "recovery_document-01-deadbeefcafebabe.pdf").write_bytes(b"%PDF-1.7\n")

            files = _iter_scan_files(root, include_extension_carriers=False)

        self.assertEqual([path.relative_to(root).as_posix() for path in files], ["qr_document.pdf"])

    def test_iter_scan_files_bounds_missing_qr_carrier_validation_by_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "qr_document.pdf").write_bytes(b"%PDF-1.7\n")
            extension_01 = root / "extensions" / "01"
            extension_02 = root / "extensions" / "02"
            extension_01.mkdir(parents=True)
            extension_02.mkdir()
            (extension_01 / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"%PDF-1.7\n")
            (extension_02 / "recovery_document-02-cafebabedeadbeef.pdf").write_bytes(b"%PDF-1.7\n")

            files = _iter_scan_files(root, extension_carrier_max_index=1)

        self.assertEqual(
            [path.relative_to(root).as_posix() for path in files],
            [
                "extensions/01/qr_document-01-deadbeefcafebabe.pdf",
                "qr_document.pdf",
            ],
        )

    def test_scan_qr_payloads_directory_does_not_decode_unpublished_staging(self) -> None:
        decoder = QrDecoder(
            name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: []
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            published = root / "extensions" / "01"
            published.mkdir(parents=True)
            published_pdf = published / "qr_document-01-deadbeefcafebabe.pdf"
            published_pdf.write_bytes(b"")
            staging = root / "extensions" / ".staging-2-aborted"
            staging.mkdir(parents=True)
            staged_pdf = staging / "qr_document-02-cafebabedeadbeef.pdf"
            staged_pdf.write_bytes(b"")
            scanned: list[str] = []

            def fake_scan_pdf(path: Path, _decoder: QrDecoder) -> list[bytes]:
                scanned.append(path.relative_to(root).as_posix())
                return [path.name.encode("utf-8")]

            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(qr_scan, "_scan_pdf", side_effect=fake_scan_pdf),
            ):
                payloads = qr_scan.scan_qr_payloads([root])

        self.assertEqual(payloads, [published_pdf.name.encode("utf-8")])
        self.assertEqual(scanned, ["extensions/01/qr_document-01-deadbeefcafebabe.pdf"])

    def test_scan_qr_payloads_rejects_blank_published_extension_carrier(self) -> None:
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

            def fake_scan_pdf(path: Path, _decoder: QrDecoder) -> list[bytes]:
                if path == extension_pdf:
                    return []
                return [b"root"]

            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(qr_scan, "_scan_pdf", side_effect=fake_scan_pdf),
                self.assertRaisesRegex(
                    QrScanError,
                    "published extension carrier contains no QR codes",
                ),
            ):
                qr_scan.scan_qr_payloads([root])

            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(qr_scan, "_scan_pdf", side_effect=fake_scan_pdf),
            ):
                payloads = qr_scan.scan_qr_payloads(
                    [root],
                    include_extension_carriers=False,
                )

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

    def test_scan_qr_payloads_scans_explicit_published_extension_for_root_only(self) -> None:
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
            scanned: list[str] = []

            def fake_scan_pdf(path: Path, _decoder: QrDecoder) -> list[bytes]:
                scanned.append(path.relative_to(root).as_posix())
                return [path.name.encode("utf-8")]

            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(qr_scan, "_scan_pdf", side_effect=fake_scan_pdf),
            ):
                payloads = qr_scan.scan_qr_payloads(
                    [root_pdf, extension_pdf],
                    include_extension_carriers=False,
                )

        self.assertEqual(
            payloads,
            [root_pdf.name.encode("utf-8"), extension_pdf.name.encode("utf-8")],
        )
        self.assertEqual(
            scanned, ["qr_document.pdf", "extensions/01/qr_document-01-deadbeefcafebabe.pdf"]
        )

    def test_scan_qr_payloads_scans_explicit_published_extension_after_max_index(self) -> None:
        decoder = QrDecoder(
            name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: []
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            extension_dir = root / "extensions" / "02"
            extension_dir.mkdir(parents=True)
            extension_pdf = extension_dir / "qr_document-02-deadbeefcafebabe.pdf"
            extension_pdf.write_bytes(b"%PDF-1.7\n")

            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(qr_scan, "_scan_pdf", return_value=[b"explicit"]),
            ):
                payloads = qr_scan.scan_qr_payloads(
                    [extension_pdf],
                    extension_carrier_max_index=1,
                )

        self.assertEqual(payloads, [b"explicit"])

    def test_explicit_staging_carrier_file_remains_a_scan_input(self) -> None:
        decoder = QrDecoder(
            name="dummy", decode_image_path=lambda _: [], decode_image_bytes=lambda _: []
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            staging = root / "extensions" / ".staging-2-aborted"
            staging.mkdir(parents=True)
            staged_pdf = staging / "qr_document-02-cafebabedeadbeef.pdf"
            staged_pdf.write_bytes(b"")
            with (
                mock.patch.object(qr_scan, "_load_decoder", return_value=decoder),
                mock.patch.object(qr_scan, "_scan_pdf", return_value=[b"explicit"]),
            ):
                payloads = qr_scan.scan_qr_payloads([staged_pdf])

        self.assertEqual(payloads, [b"explicit"])

    def test_detects_unpublished_extension_workspace_paths(self) -> None:
        self.assertTrue(
            _is_under_unpublished_extension_workspace(
                Path("root/extensions/.staging-2-aborted/qr_document.pdf")
            )
        )
        self.assertTrue(
            _is_under_unpublished_extension_workspace(
                Path("root/extensions/.staging-crash/qr_document.pdf")
            )
        )
        self.assertFalse(
            _is_under_unpublished_extension_workspace(
                Path("root/loose/.staging-2-aborted/qr_document.pdf")
            )
        )

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
