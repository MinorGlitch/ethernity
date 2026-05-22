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

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from ethernity.cli import run_compact, run_extend
from ethernity.cli.features.backup.orchestrator import run_backup_command
from ethernity.cli.features.mint.workflow import execute_mint
from ethernity.cli.features.recover.orchestrator import run_recover_command
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.constants import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ethernity.cli.shared.io.fallback_parser import (
    detect_fallback_section,
    filter_fallback_lines,
)
from ethernity.cli.shared.io.frames import _frames_from_fallback_lines, _recovery_frames_from_scan
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import BackupArgs, CompactArgs, ExtendArgs, MintArgs, RecoverArgs
from ethernity.config.paths import DEFAULT_CONFIG_PATH, SUPPORTED_TEMPLATE_DESIGNS
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import VERSION, Frame, FrameType, encode_frame
from ethernity.encoding.qr_payloads import encode_qr_payload
from ethernity.render import FallbackSection
from ethernity.render.fallback import fallback_lines_from_sections
from tests.test_support import ensure_playwright_browsers, suppress_output, temp_env

TEST_PASSPHRASE = "extension-integration-passphrase"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_V1_0_FILE_NO_SHARD_ROOT = (
    _REPO_ROOT / "tests" / "fixtures" / "v1_0" / "golden" / "base64" / "file_no_shard"
)
_V1_0_SOURCE_ROOT = _REPO_ROOT / "tests" / "fixtures" / "v1_0" / "source"
_V1_0_PASSPHRASE = "stable-v1-baseline-passphrase"
_PDF_FALLBACK_LINE_COUNTER_RE = re.compile(r"^\s*(?P<counter>\d+)[.)]?\s+")


class TestIntegrationExtensions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_playwright_browsers()

    def test_extend_recover_latest_and_select_prior_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")
            (source_dir / "nested").mkdir()
            (source_dir / "nested" / "beta.txt").write_text("root-beta", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir, design="sentinel")

                (source_dir / "alpha.txt").write_text("first-alpha", encoding="utf-8")
                (source_dir / "gamma.txt").write_text("gamma-one", encoding="utf-8")
                first_extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    design="sentinel",
                )

                (source_dir / "alpha.txt").write_text("second-alpha", encoding="utf-8")
                (source_dir / "gamma.txt").write_text("gamma-two", encoding="utf-8")
                (source_dir / "nested" / "delta.txt").write_text("delta", encoding="utf-8")
                second_extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    design="sentinel",
                )

                expected_latest_state = {
                    "alpha.txt": b"second-alpha",
                    "gamma.txt": b"gamma-two",
                    "nested/beta.txt": b"root-beta",
                    "nested/delta.txt": b"delta",
                }
                latest_dir = tmp_path / "recovered-latest"
                self._run_recover(root_dir=root_dir, output_dir=latest_dir)
                self.assertEqual(self._snapshot_tree(latest_dir), expected_latest_state)

                main_payloads = tmp_path / "main_payloads.txt"
                auth_payloads = tmp_path / "auth_payloads.txt"
                self._write_split_payload_files(
                    (
                        root_dir / "qr_document.pdf",
                        first_extension.qr_document_path,
                        second_extension.qr_document_path,
                    ),
                    main_payloads=main_payloads,
                    auth_payloads=auth_payloads,
                )
                separate_auth_dir = tmp_path / "recovered-separate-auth"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=separate_auth_dir,
                    scan=[],
                    payloads_file=str(main_payloads),
                    auth_payloads_file=str(auth_payloads),
                )
                self.assertEqual(self._snapshot_tree(separate_auth_dir), expected_latest_state)

                extension_fallback = tmp_path / "extension_fallback.txt"
                self._write_extension_recovery_pdf_fallback_file(
                    second_extension.recovery_document_path,
                    extension_fallback,
                    expected_doc_id=second_extension.doc_id,
                )
                fallback_recovered_dir = tmp_path / "recovered-extension-fallback"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=fallback_recovered_dir,
                    scan=[str(root_dir / "qr_document.pdf"), str(first_extension.qr_document_path)],
                    fallback_file=str(extension_fallback),
                )
                self.assertEqual(self._snapshot_tree(fallback_recovered_dir), expected_latest_state)

                expected_first = {
                    "alpha.txt": b"first-alpha",
                    "gamma.txt": b"gamma-one",
                    "nested/beta.txt": b"root-beta",
                }

                later_extension_dir = root_dir / "extensions" / "02"
                (
                    later_extension_dir
                    / f"recovery_document-02-{second_extension.doc_id.hex()}.pdf"
                ).unlink(missing_ok=True)

                degraded_latest_dir = tmp_path / "recovered-latest-degraded"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=degraded_latest_dir,
                )
                self.assertEqual(self._snapshot_tree(degraded_latest_dir), expected_latest_state)

                (source_dir / "alpha.txt").write_text("blocked-third-alpha", encoding="utf-8")
                blocked_extension_dir = root_dir / "extensions" / "03"
                with self.assertRaises(ApiCommandError) as ctx:
                    self._run_extend(source_dir=source_dir, root_dir=root_dir)
                self.assertEqual(ctx.exception.code, "EXTENSION_LAYOUT_INVALID")
                self.assertFalse(blocked_extension_dir.exists())

                first_dir = tmp_path / "recovered-first"
                self._run_recover(root_dir=root_dir, output_dir=first_dir, extension_index=1)
                self.assertEqual(self._snapshot_tree(first_dir), expected_first)

                first_hash_dir = tmp_path / "recovered-first-hash"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=first_hash_dir,
                    extension_doc_hash=first_extension.doc_hash.hex(),
                )
                self.assertEqual(self._snapshot_tree(first_hash_dir), expected_first)

    def test_recover_with_extension_local_shards_unlocks_root_plus_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            recovered_dir = tmp_path / "recovered-from-extension-shards"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
                (source_dir / "beta.txt").write_text("extension-beta", encoding="utf-8")
                extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    shard_threshold=2,
                    shard_count=3,
                )

                self.assertEqual(len(extension.shard_paths), 3)
                with suppress_output():
                    exit_code = run_recover_command(
                        RecoverArgs(
                            config=str(DEFAULT_CONFIG_PATH),
                            scan=[str(root_dir)],
                            shard_scan=[str(path) for path in extension.shard_paths[:2]],
                            output=str(recovered_dir),
                            allow_unsigned=False,
                            assume_yes=True,
                            quiet=True,
                        )
                    )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                self._snapshot_tree(recovered_dir),
                {
                    "alpha.txt": b"extension-alpha",
                    "beta.txt": b"extension-beta",
                },
            )

    def test_extend_with_previous_extension_local_shards_appends_next_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            recovered_dir = tmp_path / "recovered-latest"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
                (source_dir / "beta.txt").write_text("extension-beta", encoding="utf-8")
                first_extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    shard_threshold=2,
                    shard_count=3,
                )

                (source_dir / "gamma.txt").write_text("second-extension-gamma", encoding="utf-8")
                second_extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    passphrase=None,
                    shard_scan=[str(path) for path in first_extension.shard_paths[:2]],
                )

                self.assertEqual(second_extension.index, 2)
                self._run_recover(root_dir=root_dir, output_dir=recovered_dir)

            self.assertEqual(
                self._snapshot_tree(recovered_dir),
                {
                    "alpha.txt": b"extension-alpha",
                    "beta.txt": b"extension-beta",
                    "gamma.txt": b"second-extension-gamma",
                },
            )

    def test_reuse_root_extension_unlocks_with_root_shards_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            recovered_dir = tmp_path / "recovered-reuse-root"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    shard_threshold=2,
                    shard_count=3,
                )

                (source_dir / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
                extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    unlock_policy="reuse-root",
                    shard_threshold=None,
                    shard_count=None,
                )

                self.assertEqual(extension.shard_paths, ())
                root_shards = sorted(root_dir.glob("shard-*.pdf"))
                self.assertEqual(len(root_shards), 3)
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=recovered_dir,
                    passphrase=None,
                    shard_scan=[str(path) for path in root_shards[:2]],
                )

            self.assertEqual(
                self._snapshot_tree(recovered_dir),
                {"alpha.txt": b"extension-alpha"},
            )

    def test_recover_with_mixed_root_and_extension_shard_scan_uses_extension_quorum(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            recovered_dir = tmp_path / "recovered-mixed-shards"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    shard_threshold=2,
                    shard_count=3,
                )
                root_shards = sorted(root_dir.glob("shard-*.pdf"))
                self.assertEqual(len(root_shards), 3)

                (source_dir / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
                (source_dir / "beta.txt").write_text("extension-beta", encoding="utf-8")
                extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    shard_threshold=2,
                    shard_count=3,
                )

                self.assertEqual(len(extension.shard_paths), 3)
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=recovered_dir,
                    passphrase=None,
                    shard_scan=[
                        *(str(path) for path in root_shards[:2]),
                        *(str(path) for path in extension.shard_paths[:2]),
                    ],
                )

            self.assertEqual(
                self._snapshot_tree(recovered_dir),
                {
                    "alpha.txt": b"extension-alpha",
                    "beta.txt": b"extension-beta",
                },
            )

    def test_extend_frozen_v1_0_backup_and_recover_latest_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            root_dir = tmp_path / "v1-root"
            source_dir = tmp_path / "source"
            recovered_dir = tmp_path / "recovered"
            shutil.copytree(_V1_0_FILE_NO_SHARD_ROOT / "backup", root_dir)
            source_dir.mkdir()
            shutil.copy2(
                _V1_0_SOURCE_ROOT / "standalone_secret.txt",
                source_dir / "standalone_secret.txt",
            )
            (source_dir / "extension_note.txt").write_text(
                "added after frozen v1.0 root\n",
                encoding="utf-8",
            )

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    passphrase=_V1_0_PASSPHRASE,
                )
                self.assertTrue(extension.qr_document_path.is_file())
                self.assertTrue(extension.recovery_document_path.is_file())
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=recovered_dir,
                    passphrase=_V1_0_PASSPHRASE,
                )

            self.assertEqual(
                self._snapshot_tree(recovered_dir),
                {
                    "extension_note.txt": b"added after frozen v1.0 root\n",
                    "standalone_secret.txt": (
                        _V1_0_SOURCE_ROOT / "standalone_secret.txt"
                    ).read_bytes(),
                },
            )

    def test_extension_recovery_document_fallback_is_visible_for_supported_designs(self) -> None:
        for design in SUPPORTED_TEMPLATE_DESIGNS:
            with self.subTest(design=design):
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_path = Path(tmpdir)
                    source_dir = tmp_path / "source"
                    root_dir = tmp_path / "backup-root"
                    source_dir.mkdir()
                    (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

                    with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                        self._run_backup(source_dir=source_dir, root_dir=root_dir)

                        (source_dir / "alpha.txt").write_text(
                            f"extension-alpha-{design}",
                            encoding="utf-8",
                        )
                        extension = self._run_extend(
                            source_dir=source_dir,
                            root_dir=root_dir,
                            design=design,
                        )

                        reader = PdfReader(extension.recovery_document_path)
                        text = "\n".join(page.extract_text() or "" for page in reader.pages)

                    upper_text = text.upper()
                    self.assertIn("AUTH FRAME", upper_text)
                    self.assertIn("MAIN FRAME", upper_text)

    def test_mint_against_extension_head_creates_recoverable_extension_bound_shards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            mint_dir = tmp_path / "minted-extension-shards"
            recovered_dir = tmp_path / "recovered-from-minted-extension-shards"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
                (source_dir / "beta.txt").write_text("extension-beta", encoding="utf-8")
                extension = self._run_extend(source_dir=source_dir, root_dir=root_dir)

                with suppress_output():
                    mint_result = execute_mint(
                        MintArgs(
                            config=str(DEFAULT_CONFIG_PATH),
                            scan=[str(root_dir)],
                            passphrase=TEST_PASSPHRASE,
                            output_dir=str(mint_dir),
                            shard_threshold=2,
                            shard_count=3,
                            mint_signing_key_shards=False,
                            quiet=True,
                        )
                    )

                self.assertEqual(mint_result.doc_id, extension.doc_id)
                self.assertEqual(len(mint_result.shard_paths), 3)
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=recovered_dir,
                    passphrase=None,
                    shard_scan=list(mint_result.shard_paths[:2]),
                )

            self.assertEqual(
                self._snapshot_tree(recovered_dir),
                {
                    "alpha.txt": b"extension-alpha",
                    "beta.txt": b"extension-beta",
                },
            )

    def test_mint_replaces_extension_signing_key_shard_from_scanned_extension_shards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            mint_dir = tmp_path / "minted-signing-key-replacement"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
                extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    shard_threshold=2,
                    shard_count=3,
                    signing_key_mode="sharded",
                    signing_key_shard_threshold=2,
                    signing_key_shard_count=3,
                )

                self.assertEqual(len(extension.shard_paths), 3)
                self.assertEqual(len(extension.signing_key_shard_paths), 3)
                with suppress_output():
                    mint_result = execute_mint(
                        MintArgs(
                            config=str(DEFAULT_CONFIG_PATH),
                            scan=[str(root_dir)],
                            passphrase=TEST_PASSPHRASE,
                            signing_key_shard_scan=[
                                str(path) for path in extension.signing_key_shard_paths[:2]
                            ],
                            output_dir=str(mint_dir),
                            mint_passphrase_shards=False,
                            mint_signing_key_shards=True,
                            signing_key_replacement_count=1,
                            quiet=True,
                        )
                    )

            self.assertEqual(mint_result.doc_id, extension.doc_id)
            self.assertEqual(mint_result.doc_hash, extension.doc_hash)
            self.assertEqual(mint_result.shard_paths, ())
            self.assertEqual(len(mint_result.signing_key_shard_paths), 1)
            self.assertEqual(mint_result.selected_extension_index, extension.index)
            self.assertEqual(mint_result.selected_extension_doc_hash, extension.doc_hash.hex())
            self.assertTrue(Path(mint_result.signing_key_shard_paths[0]).exists())

    def test_compact_with_extension_local_shards_preserves_latest_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            compacted_dir = tmp_path / "compacted-from-extension-shards"
            recovered_dir = tmp_path / "recovered-compacted-from-extension-shards"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
                (source_dir / "beta.txt").write_text("extension-beta", encoding="utf-8")
                extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    shard_threshold=2,
                    shard_count=3,
                )

                compact_result = self._run_compact(
                    root_dir=root_dir,
                    output_dir=compacted_dir,
                    passphrase=None,
                    shard_scan=[str(path) for path in extension.shard_paths[:2]],
                )

                self._run_recover(
                    root_dir=compacted_dir,
                    output_dir=recovered_dir,
                    passphrase=None,
                    shard_scan=list(compact_result.shard_paths[:2]),
                )

            self.assertEqual(
                self._snapshot_tree(recovered_dir),
                {
                    "alpha.txt": b"extension-alpha",
                    "beta.txt": b"extension-beta",
                },
            )

    def test_compact_preserves_latest_state_from_degraded_redundant_carrier(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            healthy_compacted_dir = tmp_path / "healthy-compacted-root"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")
            (source_dir / "nested").mkdir()
            (source_dir / "nested" / "beta.txt").write_text("root-beta", encoding="utf-8")

            expected_latest_state = {
                "alpha.txt": b"second-alpha",
                "gamma.txt": b"gamma-two",
                "nested/beta.txt": b"root-beta",
                "nested/delta.txt": b"delta",
            }

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("first-alpha", encoding="utf-8")
                (source_dir / "gamma.txt").write_text("gamma-one", encoding="utf-8")
                self._run_extend(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("second-alpha", encoding="utf-8")
                (source_dir / "gamma.txt").write_text("gamma-two", encoding="utf-8")
                (source_dir / "nested" / "delta.txt").write_text("delta", encoding="utf-8")
                latest_extension = self._run_extend(source_dir=source_dir, root_dir=root_dir)

                healthy_latest_dir = tmp_path / "healthy-latest"
                self._run_recover(root_dir=root_dir, output_dir=healthy_latest_dir)
                self.assertEqual(self._snapshot_tree(healthy_latest_dir), expected_latest_state)

                healthy_compact_result = self._run_compact(
                    root_dir=root_dir,
                    output_dir=healthy_compacted_dir,
                )

                self.assertTrue(Path(healthy_compact_result.qr_path).exists())
                self.assertTrue(Path(healthy_compact_result.recovery_path).exists())

                healthy_compacted_recovered_dir = tmp_path / "healthy-compacted-state"
                self._run_recover(
                    root_dir=healthy_compacted_dir,
                    output_dir=healthy_compacted_recovered_dir,
                )
                self.assertEqual(
                    self._snapshot_tree(healthy_compacted_recovered_dir),
                    expected_latest_state,
                )

                degraded_carrier = (
                    root_dir
                    / "extensions"
                    / "02"
                    / f"recovery_document-02-{latest_extension.doc_id.hex()}.pdf"
                )
                self.assertTrue(degraded_carrier.exists())
                degraded_carrier.unlink()

                degraded_latest_dir = tmp_path / "degraded-latest"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=degraded_latest_dir,
                )
                self.assertEqual(self._snapshot_tree(degraded_latest_dir), expected_latest_state)

                degraded_compacted_dir = tmp_path / "degraded-compacted-root"
                degraded_compact_result = self._run_compact(
                    root_dir=root_dir,
                    output_dir=degraded_compacted_dir,
                )
                self.assertTrue(Path(degraded_compact_result.qr_path).exists())
                degraded_compacted_recovered_dir = tmp_path / "degraded-compacted-state"
                self._run_recover(
                    root_dir=degraded_compacted_dir,
                    output_dir=degraded_compacted_recovered_dir,
                )
                self.assertEqual(
                    self._snapshot_tree(degraded_compacted_recovered_dir),
                    expected_latest_state,
                )

    def test_corrupt_present_extension_carrier_fails_closed_across_flows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
                extension = self._run_extend(source_dir=source_dir, root_dir=root_dir)

                corrupt_carrier = (
                    root_dir / "extensions" / "01" / f"qr_document-01-{extension.doc_id.hex()}.pdf"
                )
                self.assertTrue(corrupt_carrier.exists())
                corrupt_carrier.write_bytes(b"%PDF-1.7\ncorrupt extension carrier\n")

                with self.assertRaisesRegex(ValueError, "failed to read PDF"):
                    self._run_recover(
                        root_dir=root_dir,
                        output_dir=tmp_path / "corrupt-recovered",
                    )

                with self.assertRaisesRegex(ValueError, "failed to read PDF"):
                    self._run_compact(
                        root_dir=root_dir,
                        output_dir=tmp_path / "corrupt-compacted",
                    )

                (source_dir / "alpha.txt").write_text("blocked-alpha", encoding="utf-8")
                blocked_extension_dir = root_dir / "extensions" / "02"
                with self.assertRaises(ApiCommandError) as ctx:
                    self._run_extend(source_dir=source_dir, root_dir=root_dir)
                self.assertEqual(ctx.exception.code, "EXTENSION_LAYOUT_INVALID")
                self.assertFalse(blocked_extension_dir.exists())

    def test_compact_sealed_root_without_auth_inputs_round_trips_through_recover(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "sealed-source"
            root_dir = tmp_path / "sealed-backup-root"
            compacted_dir = tmp_path / "sealed-compacted-root"
            recovered_dir = tmp_path / "sealed-compacted-recovered"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("sealed-alpha", encoding="utf-8")
            (source_dir / "nested").mkdir()
            (source_dir / "nested" / "beta.txt").write_text("sealed-beta", encoding="utf-8")

            expected_tree = {
                "alpha.txt": b"sealed-alpha",
                "nested/beta.txt": b"sealed-beta",
            }

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir, sealed=True)

                compact_result = self._run_compact(
                    root_dir=root_dir,
                    output_dir=compacted_dir,
                )

                self.assertTrue(Path(compact_result.qr_path).exists())
                self.assertTrue(Path(compact_result.recovery_path).exists())

                self._run_recover(root_dir=compacted_dir, output_dir=recovered_dir)
                self.assertEqual(self._snapshot_tree(recovered_dir), expected_tree)

    def test_compact_preserves_external_root_passphrase_shard_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            external_shard_dir = tmp_path / "separate-shards"
            compacted_dir = tmp_path / "compacted-root"
            recovered_dir = tmp_path / "compacted-recovered"
            source_dir.mkdir()
            external_shard_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    shard_threshold=2,
                    shard_count=3,
                )
                root_shards = sorted(root_dir.glob("shard-*.pdf"))
                self.assertEqual(len(root_shards), 3)
                external_shards: list[Path] = []
                for shard_path in root_shards:
                    moved_path = external_shard_dir / shard_path.name
                    shard_path.rename(moved_path)
                    external_shards.append(moved_path)
                self.assertEqual(sorted(root_dir.glob("shard-*.pdf")), [])

                compact_result = self._run_compact(
                    root_dir=root_dir,
                    output_dir=compacted_dir,
                    passphrase=None,
                    shard_scan=[str(path) for path in external_shards[:2]],
                )

                self.assertEqual(len(compact_result.shard_paths), 3)
                for shard_path in compact_result.shard_paths:
                    self.assertTrue(Path(shard_path).exists())
                self._run_recover(
                    root_dir=compacted_dir,
                    output_dir=recovered_dir,
                    passphrase=None,
                    shard_scan=list(compact_result.shard_paths[:2]),
                )
                self.assertEqual(
                    self._snapshot_tree(recovered_dir),
                    {"alpha.txt": b"root-alpha"},
                )

    def _run_backup(
        self,
        *,
        source_dir: Path,
        root_dir: Path,
        design: str | None = None,
        sealed: bool = False,
        shard_threshold: int | None = None,
        shard_count: int | None = None,
    ) -> None:
        with suppress_output():
            exit_code = run_backup_command(
                BackupArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    input_dir=[str(source_dir)],
                    base_dir=str(source_dir),
                    output_dir=str(root_dir),
                    passphrase=TEST_PASSPHRASE,
                    design=design,
                    sealed=sealed,
                    shard_threshold=shard_threshold,
                    shard_count=shard_count,
                    quiet=True,
                )
            )
        self.assertEqual(exit_code, 0)

    def _run_compact(
        self,
        *,
        root_dir: Path,
        output_dir: Path,
        passphrase: str | None = TEST_PASSPHRASE,
        shard_scan: list[str] | None = None,
    ):
        with suppress_output():
            return run_compact(
                CompactArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    root_dir=str(root_dir),
                    output_dir=str(output_dir),
                    passphrase=passphrase,
                    shard_scan=shard_scan,
                    quiet=True,
                )
            )

    def _run_extend(
        self,
        *,
        source_dir: Path,
        root_dir: Path,
        design: str | None = None,
        shard_threshold: int | None = None,
        shard_count: int | None = 0,
        passphrase: str = TEST_PASSPHRASE,
        unlock_policy: str | None = None,
        signing_key_mode: str | None = None,
        signing_key_shard_threshold: int | None = None,
        signing_key_shard_count: int | None = None,
        shard_scan: list[str] | None = None,
    ):
        with suppress_output():
            return run_extend(
                ExtendArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    root_dir=str(root_dir),
                    input_dir=[str(source_dir)],
                    base_dir=str(source_dir),
                    passphrase=passphrase,
                    shard_scan=shard_scan,
                    design=design,
                    shard_threshold=shard_threshold,
                    shard_count=shard_count,
                    unlock_policy=unlock_policy,
                    signing_key_mode=signing_key_mode,
                    signing_key_shard_threshold=signing_key_shard_threshold,
                    signing_key_shard_count=signing_key_shard_count,
                    quiet=True,
                )
            )

    def _assert_extend_head_untrusted(
        self,
        *,
        source_dir: Path,
        root_dir: Path,
        expected_latest_head_index: int,
        expected_validated_head_index: int,
        blocked_extension_dir: Path,
        expected_failure_fragment: str = "missing required MAIN documents",
    ) -> ApiCommandError:
        with self.assertRaises(ApiCommandError) as ctx:
            self._run_extend(source_dir=source_dir, root_dir=root_dir)

        exc = ctx.exception
        self.assertEqual(exc.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(exc.details["stage"], "replay")
        self.assertEqual(exc.details["failure_stage"], "discovery")
        self.assertEqual(exc.details["failure_head_index"], expected_latest_head_index)
        self.assertEqual(exc.details["failure_head_dir_name"], f"{expected_latest_head_index:02d}")
        self.assertEqual(exc.details["latest_head_index"], expected_latest_head_index)
        self.assertEqual(exc.details["latest_head_dir_name"], f"{expected_latest_head_index:02d}")
        self.assertIsNone(exc.details["requested_head_index"])
        self.assertIsNone(exc.details["requested_head_doc_hash"])
        self.assertEqual(exc.details["validated_head_index"], expected_validated_head_index)
        self.assertIsInstance(exc.details["validated_head_doc_hash"], str)
        self.assertEqual(len(exc.details["validated_head_doc_hash"]), 64)
        self.assertFalse(exc.details["explicit_selection"])
        self.assertIn("latest supplied recovery head could not be trusted", str(exc))
        self.assertIn(expected_failure_fragment, str(exc))
        self.assertFalse(blocked_extension_dir.exists())
        self.assertEqual(list((root_dir / "extensions").glob(".staging-*")), [])
        return exc

    def _run_recover(
        self,
        *,
        root_dir: Path,
        output_dir: Path,
        extension_index: int | None = None,
        extension_doc_hash: str | None = None,
        passphrase: str | None = TEST_PASSPHRASE,
        shard_scan: list[str] | None = None,
        scan: list[str] | None = None,
        fallback_file: str | None = None,
        payloads_file: str | None = None,
        auth_payloads_file: str | None = None,
    ) -> None:
        with suppress_output():
            exit_code = run_recover_command(
                RecoverArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    fallback_file=fallback_file,
                    payloads_file=payloads_file,
                    scan=[str(root_dir)] if scan is None else scan,
                    passphrase=passphrase,
                    shard_scan=shard_scan,
                    auth_payloads_file=auth_payloads_file,
                    extension_index=extension_index,
                    extension_doc_hash=extension_doc_hash,
                    output=str(output_dir),
                    allow_unsigned=False,
                    assume_yes=True,
                    quiet=True,
                )
            )
        self.assertEqual(exit_code, 0)

    def _write_extension_recovery_pdf_fallback_file(
        self,
        recovery_document: Path,
        fallback_path: Path,
        *,
        expected_doc_id: bytes,
    ) -> None:
        lines = self._fallback_lines_from_recovery_document(recovery_document)
        frames = _frames_from_fallback_lines(lines, allow_invalid_auth=False, quiet=True)
        main_frames = [frame for frame in frames if frame.frame_type == FrameType.MAIN_DOCUMENT]
        auth_frames = [frame for frame in frames if frame.frame_type == FrameType.AUTH]

        self.assertEqual(len(main_frames), 1)
        self.assertEqual(len(auth_frames), 1)
        self.assertEqual(main_frames[0].doc_id, expected_doc_id)
        self.assertEqual(auth_frames[0].doc_id, expected_doc_id)
        fallback_path.write_text("\n".join(lines), encoding="utf-8")

    def _fallback_lines_from_recovery_document(self, recovery_document: Path) -> list[str]:
        reader = PdfReader(recovery_document)
        lines: list[str] = []
        current_section: str | None = None
        accept_payload_continuation = False
        expected_row = 1
        for page in reader.pages:
            for raw_line in (page.extract_text() or "").splitlines():
                section = detect_fallback_section(raw_line)
                if section in {"auth", "main"}:
                    current_section = section
                    accept_payload_continuation = False
                    expected_row = 1
                    lines.append(AUTH_FALLBACK_LABEL if section == "auth" else MAIN_FALLBACK_LABEL)
                    continue
                if current_section not in {"auth", "main"}:
                    continue
                payload_line = self._extract_pdf_fallback_payload_line(
                    raw_line,
                    require_counter=True,
                    expected_counter=expected_row,
                )
                if payload_line is None and accept_payload_continuation:
                    payload_line = self._extract_pdf_fallback_payload_line(
                        raw_line,
                        require_counter=False,
                        expected_counter=None,
                    )
                if payload_line is None:
                    accept_payload_continuation = False
                    continue
                lines.append(payload_line)
                if _PDF_FALLBACK_LINE_COUNTER_RE.match(raw_line) is not None:
                    expected_row += 1
                accept_payload_continuation = True

        self.assertIn(AUTH_FALLBACK_LABEL, lines)
        self.assertIn(MAIN_FALLBACK_LABEL, lines)
        return lines

    def _extract_pdf_fallback_payload_line(
        self,
        line: str,
        *,
        require_counter: bool,
        expected_counter: int | None,
    ) -> str | None:
        counter_match = _PDF_FALLBACK_LINE_COUNTER_RE.match(line)
        has_counter = counter_match is not None
        if require_counter and counter_match is None:
            return None
        if (
            expected_counter is not None
            and counter_match is not None
            and int(counter_match.group("counter")) != expected_counter
        ):
            return None
        candidate = (
            _PDF_FALLBACK_LINE_COUNTER_RE.sub("", line.strip()) if has_counter else line.strip()
        )
        tokens: list[str] = []
        for token in candidate.split():
            if len(token) > 4:
                break
            try:
                filter_fallback_lines([token])
            except ValueError:
                break
            tokens.append(token)
        if not tokens:
            return None
        candidate = " ".join(tokens)
        try:
            filter_fallback_lines([candidate])
        except ValueError:
            return None
        return candidate

    def _write_split_payload_files(
        self,
        qr_documents: tuple[Path, ...],
        *,
        main_payloads: Path,
        auth_payloads: Path,
    ) -> None:
        frames: list[Frame] = []
        for path in qr_documents:
            frames.extend(_recovery_frames_from_scan([str(path)], quiet=True))
        main_lines = [
            self._payload_line(frame)
            for frame in frames
            if frame.frame_type == FrameType.MAIN_DOCUMENT
        ]
        auth_lines = [
            self._payload_line(frame) for frame in frames if frame.frame_type == FrameType.AUTH
        ]

        self.assertTrue(main_lines)
        self.assertTrue(auth_lines)
        main_payloads.write_text("\n".join(main_lines), encoding="utf-8")
        auth_payloads.write_text("\n".join(auth_lines), encoding="utf-8")

    def _write_extension_fallback_file(self, qr_document: Path, fallback_path: Path) -> None:
        frames = _recovery_frames_from_scan([str(qr_document)], quiet=True)
        main_frames = [frame for frame in frames if frame.frame_type == FrameType.MAIN_DOCUMENT]
        auth_frames = [frame for frame in frames if frame.frame_type == FrameType.AUTH]
        self.assertTrue(main_frames)
        self.assertEqual(len(auth_frames), 1)
        ciphertext = reassemble_payload(
            main_frames,
            expected_frame_type=FrameType.MAIN_DOCUMENT,
        )
        main_fallback_frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=main_frames[0].doc_id,
            index=0,
            total=1,
            data=ciphertext,
        )
        lines = fallback_lines_from_sections(
            (
                FallbackSection(label=AUTH_FALLBACK_LABEL, frame=auth_frames[0]),
                FallbackSection(label=MAIN_FALLBACK_LABEL, frame=main_fallback_frame),
            ),
            group_size=4,
            line_length=64,
        )
        fallback_path.write_text("\n".join(lines), encoding="utf-8")

    def _payload_line(self, frame: Frame) -> str:
        payload = encode_qr_payload(encode_frame(frame))
        if isinstance(payload, bytes):
            return payload.decode("ascii")
        return payload

    def _assert_recover_head_untrusted(
        self,
        *,
        root_dir: Path,
        output_dir: Path,
        expected_latest_head_index: int,
        expected_failure_fragment: str = "missing required MAIN documents",
    ) -> ApiCommandError:
        with self.assertRaises(ApiCommandError) as ctx:
            self._run_recover(root_dir=root_dir, output_dir=output_dir)

        exc = ctx.exception
        self._assert_head_untrusted_error(
            exc,
            output_dir=output_dir,
            expected_latest_head_index=expected_latest_head_index,
            expected_message_fragment="latest supplied recovery head could not be trusted",
            expected_failure_fragment=expected_failure_fragment,
            checkpoint_created=None,
        )
        return exc

    def _assert_compact_head_untrusted(
        self,
        *,
        root_dir: Path,
        output_dir: Path,
        expected_latest_head_index: int,
        expected_failure_fragment: str = "missing required MAIN documents",
    ) -> ApiCommandError:
        with self.assertRaises(ApiCommandError) as ctx:
            self._run_compact(root_dir=root_dir, output_dir=output_dir)

        exc = ctx.exception
        self._assert_head_untrusted_error(
            exc,
            output_dir=output_dir,
            expected_latest_head_index=expected_latest_head_index,
            expected_message_fragment=(
                "latest supplied compact head could not be trusted; no checkpoint was created"
            ),
            expected_failure_fragment=expected_failure_fragment,
            checkpoint_created=False,
        )
        return exc

    def _assert_head_untrusted_error(
        self,
        exc: ApiCommandError,
        *,
        output_dir: Path,
        expected_latest_head_index: int,
        expected_message_fragment: str,
        expected_failure_fragment: str,
        checkpoint_created: bool | None,
    ) -> None:
        self.assertEqual(exc.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(exc.details["stage"], "replay")
        self.assertEqual(exc.details["failure_stage"], "discovery")
        self.assertEqual(exc.details["failure_head_index"], expected_latest_head_index)
        self.assertEqual(exc.details["failure_head_dir_name"], f"{expected_latest_head_index:02d}")
        self.assertEqual(exc.details["latest_head_index"], expected_latest_head_index)
        self.assertEqual(exc.details["latest_head_dir_name"], f"{expected_latest_head_index:02d}")
        self.assertIsNone(exc.details["requested_head_index"])
        self.assertIsNone(exc.details["requested_head_doc_hash"])
        self.assertEqual(exc.details["validated_head_index"], 0)
        self.assertFalse(exc.details["explicit_selection"])
        self.assertIn(expected_message_fragment, str(exc))
        self.assertIn(expected_failure_fragment, str(exc))
        if checkpoint_created is None:
            self.assertNotIn("checkpoint_created", exc.details)
        else:
            self.assertEqual(exc.details["checkpoint_created"], checkpoint_created)
        self.assertFalse(output_dir.exists())

    @staticmethod
    def _snapshot_tree(root: Path) -> dict[str, bytes]:
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
