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

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from ethernity.cli.features.backup.service import execute_prepared_backup, prepare_backup_run
from ethernity.cli.features.compact.service import run_compact
from ethernity.cli.features.extend.planning import _inspect_root_recovery
from ethernity.cli.features.extend.service import run_extend
from ethernity.cli.features.mint.workflow import execute_mint
from ethernity.cli.features.recover.service import execute_recover_plan, prepare_recover_plan
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.constants import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ethernity.cli.shared.io.frames import recovery_frames_from_scan
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import BackupArgs, CompactArgs, ExtendArgs, MintArgs, RecoverArgs
from ethernity.config.paths import DEFAULT_CONFIG_PATH, SUPPORTED_RENDER_STYLES
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import VERSION, Frame, FrameType, encode_frame
from ethernity.encoding.qr_payloads import encode_qr_payload
from ethernity.render import FallbackSection
from ethernity.render.fallback_text import fallback_lines_from_sections
from tests.test_support import suppress_output, temp_env

TEST_PASSPHRASE = "extension-integration-passphrase"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_V1_0_FILE_NO_SHARD_ROOT = (
    _REPO_ROOT / "tests" / "fixtures" / "v1_0" / "golden" / "base64" / "file_no_shard"
)
_V1_0_SOURCE_ROOT = _REPO_ROOT / "tests" / "fixtures" / "v1_0" / "source"
_V1_0_PASSPHRASE = "stable-v1-baseline-passphrase"


class TestIntegrationExtensions(unittest.TestCase):
    def test_valid_bip39_is_canonical_across_backup_and_exact_first_recovery(self) -> None:
        spaced = "  " + "  ".join(["abandon"] * 11 + ["about"]) + "  "
        canonical = " ".join(["abandon"] * 11 + ["about"])
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup"
            recovered_dir = tmp_path / "recovered"
            source_dir.mkdir()
            (source_dir / "secret.txt").write_text("canonical", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                with suppress_output():
                    backup_args = BackupArgs(
                        config=str(DEFAULT_CONFIG_PATH),
                        input_dir=[str(source_dir)],
                        base_dir=str(source_dir),
                        output_dir=str(root_dir),
                        passphrase=spaced,
                        design="ledger",
                        quiet=True,
                    )
                    result = execute_prepared_backup(prepare_backup_run(backup_args))
                    recover_args = RecoverArgs(
                        config=str(DEFAULT_CONFIG_PATH),
                        scan=[str(root_dir)],
                        passphrase=spaced,
                        output=str(recovered_dir),
                        assume_yes=True,
                        quiet=True,
                    )
                    execute_recover_plan(
                        prepare_recover_plan(recover_args),
                        quiet=True,
                    )

            self.assertEqual(result.passphrase_used, canonical)
            self.assertEqual(
                self._snapshot_tree(recovered_dir),
                {"secret.txt": b"canonical"},
            )

    def test_strict_root_fallback_audit_accepts_frozen_v1_profiles(self) -> None:
        cases = (
            ("v1_0", "raw", "stable-v1-baseline-passphrase"),
            ("v1_0", "base64", "stable-v1-baseline-passphrase"),
            ("v1_1", "raw", "stable-v1_1-golden-passphrase"),
            ("v1_1", "base64", "stable-v1_1-golden-passphrase"),
        )
        for version, profile, passphrase in cases:
            with self.subTest(version=version, profile=profile):
                root_dir = (
                    _REPO_ROOT
                    / "tests"
                    / "fixtures"
                    / version
                    / "golden"
                    / profile
                    / "sharded_signing_sharded"
                    / "backup"
                )
                recovery = _inspect_root_recovery(
                    root_dir,
                    ExtendArgs(
                        root_dir=str(root_dir),
                        passphrase=passphrase,
                        quiet=True,
                    ),
                    extension_inventory=None,
                )

                self.assertEqual(recovery.inspection.auth_status, "verified")
                self.assertTrue(recovery.inspection.unlock.satisfied)

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
                self._write_extension_fallback_file(
                    second_extension.qr_document_path, extension_fallback
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

    def test_extend_writes_structured_layout_debug_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            debug_dir = tmp_path / "layout-debug"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir, design="sentinel")
                (source_dir / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
                self._run_extend(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    design="sentinel",
                    layout_debug_dir=debug_dir,
                )

            expected = {
                "qr_document.layout.json": "main",
                "recovery_document.layout.json": "recovery",
            }
            for filename, doc_type in expected.items():
                with self.subTest(filename=filename):
                    sidecar = debug_dir / filename
                    self.assertTrue(sidecar.exists(), msg=f"missing layout sidecar: {sidecar}")
                    payload = json.loads(sidecar.read_text(encoding="utf-8"))
                    self.assertEqual(payload["doc_type"], doc_type)
                    self.assertIn("layout_first", payload)
                    self.assertIsInstance(payload["pages"], list)
                    self.assertGreaterEqual(len(payload["pages"]), 1)
                    self.assertIn("qr_count", payload["pages"][0])

    def test_extend_from_scanned_chain_without_original_publish_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            original_root = tmp_path / "original-root"
            loose_scans = tmp_path / "loose-scans"
            rehydrated_root = tmp_path / "rehydrated-root"
            source_dir.mkdir()
            loose_scans.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=original_root)

                (source_dir / "alpha.txt").write_text("first-alpha", encoding="utf-8")
                first_extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=original_root,
                )

                root_scan = loose_scans / "paper-root.pdf"
                first_scan = loose_scans / "paper-extension-one.pdf"
                shutil.copy2(original_root / "qr_document.pdf", root_scan)
                shutil.copy2(first_extension.qr_document_path, first_scan)
                shutil.rmtree(original_root)

                (source_dir / "alpha.txt").write_text("second-alpha", encoding="utf-8")
                (source_dir / "beta.txt").write_text("second-beta", encoding="utf-8")
                second_extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=rehydrated_root,
                    scan=[str(root_scan), str(first_scan)],
                    expected_head_doc_hash=first_extension.doc_hash.hex(),
                )

                self.assertEqual(second_extension.index, 2)
                self.assertTrue(second_extension.qr_document_path.exists())
                self.assertEqual(second_extension.final_dir.parent, rehydrated_root)
                self.assertTrue(second_extension.final_dir.name.startswith("extension-02-"))
                self.assertEqual(
                    second_extension.qr_document_path.parent, second_extension.final_dir
                )
                self.assertFalse((rehydrated_root / "qr_document.pdf").exists())
                self.assertFalse((rehydrated_root / "extensions").exists())

                recovered_dir = tmp_path / "recovered-latest"
                self._run_recover(
                    root_dir=rehydrated_root,
                    output_dir=recovered_dir,
                    scan=[
                        str(root_scan),
                        str(first_scan),
                        str(second_extension.qr_document_path),
                    ],
                )
                self.assertEqual(
                    self._snapshot_tree(recovered_dir),
                    {
                        "alpha.txt": b"second-alpha",
                        "beta.txt": b"second-beta",
                    },
                )

    def test_compact_from_scanned_chain_without_original_publish_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            original_root = tmp_path / "original-root"
            loose_scans = tmp_path / "loose-scans"
            compacted_dir = tmp_path / "compacted-from-scans"
            recovered_dir = tmp_path / "recovered-compacted-from-scans"
            source_dir.mkdir()
            loose_scans.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=original_root)

                (source_dir / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
                (source_dir / "beta.txt").write_text("extension-beta", encoding="utf-8")
                extension = self._run_extend(source_dir=source_dir, root_dir=original_root)

                root_scan = loose_scans / "paper-root.pdf"
                extension_scan = loose_scans / "paper-extension-one.pdf"
                shutil.copy2(original_root / "qr_document.pdf", root_scan)
                shutil.copy2(extension.qr_document_path, extension_scan)
                shutil.rmtree(original_root)

                compact_result = self._run_compact(
                    root_dir=None,
                    output_dir=compacted_dir,
                    scan=[str(root_scan), str(extension_scan)],
                    allow_stale_head=True,
                )
                self._run_recover(
                    root_dir=compacted_dir,
                    output_dir=recovered_dir,
                    passphrase=TEST_PASSPHRASE,
                    shard_scan=list(compact_result.shard_paths[:2]) or None,
                )

            self.assertEqual(
                self._snapshot_tree(recovered_dir),
                {
                    "alpha.txt": b"extension-alpha",
                    "beta.txt": b"extension-beta",
                },
            )

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
                    args = RecoverArgs(
                        config=str(DEFAULT_CONFIG_PATH),
                        scan=[str(root_dir)],
                        shard_scan=[str(path) for path in extension.shard_paths[:2]],
                        output=str(recovered_dir),
                        allow_unsigned=False,
                        assume_yes=True,
                        quiet=True,
                    )
                    execute_recover_plan(prepare_recover_plan(args), quiet=args.quiet)

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
            (source_dir / "extension_note.txt").write_bytes(
                b"added after frozen v1.0 root\n",
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

    def test_extension_recovery_document_renders_for_supported_designs(self) -> None:
        for design in SUPPORTED_RENDER_STYLES:
            with self.subTest(design=design):
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_path = Path(tmpdir)
                    source_dir = tmp_path / "source"
                    root_dir = tmp_path / "backup-root"
                    recovered_dir = tmp_path / "recovered"
                    source_dir.mkdir()
                    (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")
                    expected_alpha = f"extension-alpha-{design}"

                    with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                        self._run_backup(source_dir=source_dir, root_dir=root_dir)

                        (source_dir / "alpha.txt").write_text(expected_alpha, encoding="utf-8")
                        extension = self._run_extend(
                            source_dir=source_dir,
                            root_dir=root_dir,
                            design=design,
                        )
                        self._run_recover(root_dir=root_dir, output_dir=recovered_dir)

                        reader = PdfReader(extension.recovery_document_path)
                    self.assertGreater(len(reader.pages), 0)
                    self.assertEqual(
                        self._snapshot_tree(recovered_dir),
                        {"alpha.txt": expected_alpha.encode("utf-8")},
                    )

    def test_extend_forge_generated_folder_allows_second_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            recovered_dir = tmp_path / "recovered"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir, design="forge")

                (source_dir / "alpha.txt").write_text("first-alpha", encoding="utf-8")
                (source_dir / "first.bin").write_bytes(bytes(index % 251 for index in range(8192)))
                self._run_extend(source_dir=source_dir, root_dir=root_dir, design="forge")

                (source_dir / "alpha.txt").write_text("second-alpha", encoding="utf-8")
                (source_dir / "second.bin").write_bytes(
                    bytes((index * 7) % 251 for index in range(9216))
                )
                self._run_extend(source_dir=source_dir, root_dir=root_dir, design="forge")

                self._run_recover(root_dir=root_dir, output_dir=recovered_dir)

            self.assertEqual(
                self._snapshot_tree(recovered_dir),
                {
                    "alpha.txt": b"second-alpha",
                    "first.bin": bytes(index % 251 for index in range(8192)),
                    "second.bin": bytes((index * 7) % 251 for index in range(9216)),
                },
            )

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
                            expected_head_doc_hash=extension.doc_hash.hex(),
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
                            expected_head_doc_hash=extension.doc_hash.hex(),
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

    def test_compact_with_mixed_root_and_extension_shards_uses_extension_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            compacted_dir = tmp_path / "compacted-mixed-shards"
            recovered_dir = tmp_path / "recovered-compacted-mixed-shards"
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

                compact_result = self._run_compact(
                    root_dir=root_dir,
                    output_dir=compacted_dir,
                    passphrase=None,
                    shard_scan=[
                        *(str(path) for path in root_shards[:2]),
                        *(str(path) for path in extension.shard_paths[:2]),
                    ],
                )
                self.assertEqual(len(compact_result.shard_paths), 3)

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

                root_only_dir = tmp_path / "corrupt-root-only-recovered"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=root_only_dir,
                    extension_index=0,
                )
                self.assertEqual(
                    self._snapshot_tree(root_only_dir),
                    {"alpha.txt": b"root-alpha"},
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

    def test_corrupt_published_extension_shards_block_later_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
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
                )
                self.assertTrue(extension.shard_paths)
                for shard_path in extension.shard_paths:
                    Path(shard_path).write_bytes(b"not a PDF")

                (source_dir / "alpha.txt").write_text("blocked-alpha", encoding="utf-8")
                with self.assertRaises(ApiCommandError) as ctx:
                    self._run_extend(source_dir=source_dir, root_dir=root_dir)

                self.assertEqual(ctx.exception.code, "EXTENSION_LAYOUT_INVALID")
                self.assertIn("shard", str(ctx.exception).lower())
                self.assertFalse((root_dir / "extensions" / "02").exists())

    def test_blank_present_extension_carrier_fails_closed_across_flows(self) -> None:
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

                blank_carrier = (
                    root_dir / "extensions" / "01" / f"qr_document-01-{extension.doc_id.hex()}.pdf"
                )
                self.assertTrue(blank_carrier.exists())
                self._write_blank_pdf(blank_carrier)

                with self.assertRaisesRegex(
                    ValueError,
                    "published extension carrier contains no QR codes",
                ):
                    self._run_recover(
                        root_dir=root_dir,
                        output_dir=tmp_path / "blank-recovered",
                    )

                root_only_dir = tmp_path / "blank-root-only-recovered"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=root_only_dir,
                    extension_index=0,
                )
                self.assertEqual(
                    self._snapshot_tree(root_only_dir),
                    {"alpha.txt": b"root-alpha"},
                )

                with self.assertRaisesRegex(
                    ValueError,
                    "published extension carrier contains no QR codes",
                ):
                    self._run_compact(
                        root_dir=root_dir,
                        output_dir=tmp_path / "blank-compacted",
                    )

    def test_missing_present_extension_carrier_fails_closed_across_flows(self) -> None:
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

                missing_carrier = (
                    root_dir / "extensions" / "01" / f"qr_document-01-{extension.doc_id.hex()}.pdf"
                )
                self.assertTrue(missing_carrier.exists())
                missing_carrier.unlink()

                with self.assertRaisesRegex(
                    ValueError,
                    "canonical extension directory is missing its QR document carrier",
                ):
                    self._run_recover(
                        root_dir=root_dir,
                        output_dir=tmp_path / "missing-recovered",
                    )

                root_only_dir = tmp_path / "missing-root-only-recovered"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=root_only_dir,
                    extension_index=0,
                )
                self.assertEqual(
                    self._snapshot_tree(root_only_dir),
                    {"alpha.txt": b"root-alpha"},
                )

                with self.assertRaisesRegex(
                    ValueError,
                    "canonical extension directory is missing its QR document carrier",
                ):
                    self._run_compact(
                        root_dir=root_dir,
                        output_dir=tmp_path / "missing-compacted",
                    )

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
            args = BackupArgs(
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
            result = execute_prepared_backup(prepare_backup_run(args))
        self.assertTrue(Path(result.qr_path).exists())
        self.assertTrue(Path(result.recovery_path).exists())

    def _run_compact(
        self,
        *,
        root_dir: Path | None,
        output_dir: Path,
        passphrase: str | None = TEST_PASSPHRASE,
        scan: list[str] | None = None,
        shard_scan: list[str] | None = None,
        allow_stale_head: bool = False,
    ):
        with suppress_output():
            return run_compact(
                CompactArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    root_dir=str(root_dir) if root_dir is not None else None,
                    scan=scan,
                    output_dir=str(output_dir),
                    passphrase=passphrase,
                    shard_scan=shard_scan,
                    allow_stale_head=allow_stale_head,
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
        scan: list[str] | None = None,
        shard_scan: list[str] | None = None,
        expected_head_doc_hash: str | None = None,
        allow_stale_head: bool = False,
        layout_debug_dir: Path | None = None,
    ):
        with suppress_output():
            return run_extend(
                ExtendArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    root_dir=str(root_dir),
                    scan=scan,
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
                    expected_head_doc_hash=expected_head_doc_hash,
                    allow_stale_head=allow_stale_head,
                    layout_debug_dir=(
                        str(layout_debug_dir) if layout_debug_dir is not None else None
                    ),
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
            args = RecoverArgs(
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
            execute_recover_plan(prepare_recover_plan(args), quiet=args.quiet)

    def _write_split_payload_files(
        self,
        qr_documents: tuple[Path, ...],
        *,
        main_payloads: Path,
        auth_payloads: Path,
    ) -> None:
        frames: list[Frame] = []
        for path in qr_documents:
            frames.extend(recovery_frames_from_scan([str(path)], quiet=True))
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
        frames = recovery_frames_from_scan([str(qr_document)], quiet=True)
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
    def _write_blank_pdf(path: Path) -> None:
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with path.open("wb") as handle:
            writer.write(handle)

    @staticmethod
    def _snapshot_tree(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
