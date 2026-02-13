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

from __future__ import annotations

import contextlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from ethernity.cli.core.types import BackupArgs, BackupResult, InputFile
from ethernity.cli.flows import backup
from ethernity.config import load_app_config
from ethernity.core.models import DocumentPlan, ShardingConfig, SigningSeedMode

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "src" / "ethernity" / "config" / "config.toml"


class TestBackupFlowWizardLogic(unittest.TestCase):
    def test_format_backup_input_error_variants(self) -> None:
        self.assertIn(
            "Check the path and try again.",
            backup._format_backup_input_error(ValueError("input file not found: x")),
        )
        self.assertIn(
            "Provide --base-dir",
            backup._format_backup_input_error(ValueError("input paths are on different roots")),
        )
        self.assertEqual(
            backup._format_backup_input_error(ValueError("no input files found in directory")),
            "No input files found. Select files or folders to back up.",
        )
        self.assertEqual(
            backup._format_backup_input_error(ValueError("unexpected problem")),
            "unexpected problem",
        )

    def test_prompt_encryption_with_provided_passphrase_replace_and_keep(self) -> None:
        args = BackupArgs(passphrase="old-pass")
        with mock.patch.object(backup, "prompt_optional_secret", return_value="new-pass"):
            passphrase, words = backup._prompt_encryption(args)
        self.assertEqual(passphrase, "new-pass")
        self.assertIsNone(words)

        with mock.patch.object(backup, "prompt_optional_secret", return_value=None):
            passphrase, words = backup._prompt_encryption(args)
        self.assertEqual(passphrase, "old-pass")
        self.assertIsNone(words)

    def test_prompt_encryption_autogen_and_validate_words_paths(self) -> None:
        args = BackupArgs(passphrase_generate=False, passphrase_words=None)
        with (
            mock.patch.object(backup, "prompt_optional_secret", return_value=None),
            mock.patch.object(backup, "prompt_passphrase_words", return_value=21) as prompt_words,
        ):
            passphrase, words = backup._prompt_encryption(args)
        self.assertIsNone(passphrase)
        self.assertEqual(words, 21)
        prompt_words.assert_called_once()

        args_with_words = BackupArgs(passphrase_generate=True, passphrase_words=18)
        with (
            mock.patch.object(backup, "prompt_optional_secret", return_value=None),
            mock.patch.object(backup, "_validate_passphrase_words") as validate_words,
            mock.patch.object(backup, "prompt_passphrase_words") as prompt_words,
        ):
            passphrase, words = backup._prompt_encryption(args_with_words)
        self.assertIsNone(passphrase)
        self.assertEqual(words, 18)
        validate_words.assert_called_once_with(18)
        prompt_words.assert_not_called()

    def test_prompt_recovery_options_branches(self) -> None:
        no_shard_args = BackupArgs(sealed=True)
        with mock.patch.object(backup, "resolve_passphrase_sharding", return_value=None):
            sealed, debug, mode, sharding, signing_seed_sharding = backup._prompt_recovery_options(
                no_shard_args,
                debug_override=True,
                quiet=True,
            )
        self.assertTrue(sealed)
        self.assertTrue(debug)
        self.assertEqual(mode, SigningSeedMode.EMBEDDED)
        self.assertIsNone(sharding)
        self.assertIsNone(signing_seed_sharding)

        sharding = ShardingConfig(threshold=2, shares=3)
        sharded_args = BackupArgs(sealed=False)
        with (
            mock.patch.object(backup, "resolve_passphrase_sharding", return_value=sharding),
            mock.patch.object(backup, "prompt_yes_no", side_effect=[True, False]),
            mock.patch.object(
                backup, "resolve_signing_seed_mode", return_value=SigningSeedMode.SHARDED
            ),
            mock.patch.object(
                backup,
                "resolve_signing_seed_sharding",
                return_value=ShardingConfig(threshold=1, shares=2),
            ),
        ):
            sealed, debug, mode, out_sharding, signing_seed_sharding = (
                backup._prompt_recovery_options(
                    sharded_args,
                    debug_override=None,
                    quiet=False,
                )
            )
        self.assertTrue(sealed)
        self.assertFalse(debug)
        self.assertEqual(mode, SigningSeedMode.SHARDED)
        self.assertEqual(out_sharding, sharding)
        self.assertEqual(signing_seed_sharding, ShardingConfig(threshold=1, shares=2))

    def test_prompt_layout_paths(self) -> None:
        with (
            mock.patch.object(backup, "prompt_choice", return_value="custom"),
            mock.patch.object(backup, "prompt_path_with_picker", return_value="/tmp/cfg.toml"),
        ):
            config_path, paper = backup._prompt_layout(None, None)
        self.assertEqual(config_path, "/tmp/cfg.toml")
        self.assertIsNone(paper)

        with mock.patch.object(backup, "prompt_choice", return_value="letter"):
            config_path, paper = backup._prompt_layout(None, None)
        self.assertIsNone(config_path)
        self.assertEqual(paper, "LETTER")

        config_path, paper = backup._prompt_layout("settings.toml", "a4")
        self.assertEqual(config_path, "settings.toml")
        self.assertEqual(paper, "A4")

    def test_resolve_design_name_and_prompt_design_paths(self) -> None:
        designs = {
            "Forge": Path("/tmp/forge"),
            "Ledger": Path("/tmp/ledger"),
        }
        self.assertEqual(backup._resolve_design_name("forge", designs), "Forge")
        self.assertIsNone(backup._resolve_design_name("missing", designs))

        with mock.patch.object(backup, "list_template_designs", return_value={}):
            self.assertIsNone(backup._prompt_design(BackupArgs()))

        with mock.patch.object(
            backup, "list_template_designs", return_value={"ledger": Path("/tmp/ledger")}
        ):
            self.assertEqual(backup._prompt_design(BackupArgs(design="ledger")), "ledger")

        with (
            mock.patch.object(backup, "list_template_designs", return_value=designs),
            mock.patch.object(backup, "prompt_choice", return_value="Ledger"),
            mock.patch.object(backup.console_err, "print") as error_print,
        ):
            chosen = backup._prompt_design(BackupArgs(design="unknown"))
        self.assertEqual(chosen, "Ledger")
        error_print.assert_called_once()

    def test_prompt_inputs_retries_after_value_error(self) -> None:
        input_file = InputFile(
            source_path=Path("input.txt"),
            relative_path="input.txt",
            data=b"payload",
            mtime=None,
        )
        with (
            mock.patch.object(backup, "prompt_paths_with_picker", return_value=["input.txt"]),
            mock.patch.object(backup, "prompt_optional", return_value=None),
            mock.patch.object(
                backup, "progress", return_value=contextlib.nullcontext(None)
            ) as progress_mock,
            mock.patch.object(
                backup,
                "_load_input_files",
                side_effect=[
                    ValueError("no input files found"),
                    ([input_file], Path("/base"), "file", []),
                ],
            ) as load_inputs,
            mock.patch.object(backup.console_err, "print") as error_print,
        ):
            (
                input_files,
                resolved_base,
                output_dir,
                input_origin,
                input_roots,
            ) = backup._prompt_inputs(
                BackupArgs(base_dir="/base"),
                quiet=False,
                debug=True,
            )
        self.assertEqual(len(input_files), 1)
        self.assertEqual(resolved_base, Path("/base"))
        self.assertIsNone(output_dir)
        self.assertEqual(input_origin, "file")
        self.assertEqual(input_roots, [])
        self.assertEqual(load_inputs.call_count, 2)
        error_print.assert_called_once()
        progress_mock.assert_any_call(quiet=True)

    def test_apply_qr_chunk_size_override(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        self.assertIs(backup._apply_qr_chunk_size_override(config, None), config)
        updated = backup._apply_qr_chunk_size_override(config, 640)
        self.assertEqual(updated.qr_chunk_size, 640)
        self.assertEqual(
            config.qr_chunk_size, load_app_config(path=DEFAULT_CONFIG_PATH).qr_chunk_size
        )

    def test_build_review_rows_sharding_variants_and_kit_template_row(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        input_files = [
            InputFile(
                source_path=Path("input.txt"),
                relative_path="input.txt",
                data=b"x",
                mtime=None,
            )
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = Path(tmpdir) / "kit_index_document.html.j2"
            template_path.write_text("x", encoding="utf-8")
            with mock.patch.object(
                backup, "_resolve_kit_index_template_path", return_value=template_path
            ):
                rows = backup._build_review_rows(
                    passphrase=None,
                    passphrase_words=24,
                    plan=DocumentPlan(version=1, sealed=False, sharding=None),
                    input_files=input_files,
                    resolved_base=None,
                    output_dir=None,
                    config_path=None,
                    paper=None,
                    design=None,
                    config=config,
                    debug=False,
                )
        self.assertIn(("Sharding", "disabled"), rows)
        self.assertIn(("Signing key handling", "not applicable"), rows)
        self.assertIn(("Recovery kit index template", str(template_path)), rows)

        sharded_plan = DocumentPlan(
            version=1,
            sealed=False,
            sharding=ShardingConfig(threshold=2, shares=3),
            signing_seed_mode=SigningSeedMode.SHARDED,
            signing_seed_sharding=None,
        )
        rows = backup._build_review_rows(
            passphrase="p",
            passphrase_words=None,
            plan=sharded_plan,
            input_files=input_files,
            resolved_base=Path("/base"),
            output_dir="out",
            config_path="cfg.toml",
            paper="A4",
            design="forge",
            config=config,
            debug=True,
        )
        self.assertIn(("Sharding", "2 of 3"), rows)
        self.assertIn(("Signing key handling", "separate signing-key shard documents"), rows)
        self.assertIn(("Signing-key shards", "same as passphrase"), rows)
        self.assertIn(("Shard template", str(config.shard_template_path)), rows)
        self.assertIn(
            ("Signing-key shard template", str(config.signing_key_shard_template_path)), rows
        )

        sealed_sharded_plan = DocumentPlan(
            version=1,
            sealed=True,
            sharding=ShardingConfig(threshold=2, shares=3),
            signing_seed_mode=SigningSeedMode.SHARDED,
            signing_seed_sharding=ShardingConfig(threshold=1, shares=2),
        )
        rows = backup._build_review_rows(
            passphrase="p",
            passphrase_words=None,
            plan=sealed_sharded_plan,
            input_files=input_files,
            resolved_base=None,
            output_dir=None,
            config_path=None,
            paper=None,
            design=None,
            config=config,
            debug=False,
        )
        self.assertIn(("Signing key handling", "not stored (sealed backup)"), rows)
        self.assertIn(("Signing-key shards", "1 of 2"), rows)

    def test_resolve_kit_index_template_path_and_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            design_dir = root / "user" / "forge"
            design_dir.mkdir(parents=True, exist_ok=True)
            kit_template = design_dir / "kit_document.html.j2"
            kit_template.write_text("kit", encoding="utf-8")
            compatible = design_dir / "kit_index_document.html.j2"
            compatible.write_text("kit_index_inventory_artifacts_v3", encoding="utf-8")

            config = replace(
                load_app_config(path=DEFAULT_CONFIG_PATH), kit_template_path=kit_template
            )
            with mock.patch.object(backup, "PACKAGE_ROOT", root / "pkg"):
                self.assertEqual(backup._resolve_kit_index_template_path(config), compatible)

            compatible.write_text("incompatible", encoding="utf-8")
            package_candidate = root / "pkg" / "templates" / "forge" / "kit_index_document.html.j2"
            with mock.patch.object(backup, "PACKAGE_ROOT", root / "pkg"):
                self.assertEqual(backup._resolve_kit_index_template_path(config), package_candidate)

            self.assertFalse(backup._is_compatible_kit_index_template(root / "missing.html.j2"))

    def test_print_completion_actions_paths(self) -> None:
        result = BackupResult(
            doc_id=b"\x01" * 16,
            qr_path="/tmp/out/qr_document.pdf",
            recovery_path="/tmp/out/recovery_document.pdf",
            shard_paths=("s1.pdf", "s2.pdf"),
            signing_key_shard_paths=("k1.pdf",),
            passphrase_used="pass",
            kit_index_path="index.pdf",
        )
        with mock.patch.object(backup, "print_completion_panel") as completion_panel:
            backup._print_completion_actions(result, quiet=False)
        completion_panel.assert_called_once()
        actions = completion_panel.call_args.args[1]
        self.assertIn("Store the recovery kit index separately.", actions)
        self.assertIn("Store 2 shard documents in different locations.", actions)
        self.assertIn("Store 1 signing-key shard documents separately.", actions)

        with mock.patch.object(backup, "print_completion_panel") as completion_panel:
            backup._print_completion_actions(result, quiet=True)
        completion_panel.assert_not_called()

    def test_should_use_wizard_for_backup(self) -> None:
        with mock.patch.object(backup.os, "isatty", return_value=True):
            self.assertFalse(backup._should_use_wizard_for_backup(BackupArgs(input=["x"])))
            self.assertFalse(backup._should_use_wizard_for_backup(BackupArgs(input_dir=["d"])))
            self.assertTrue(backup._should_use_wizard_for_backup(BackupArgs()))
        with mock.patch.object(backup.os, "isatty", return_value=False):
            self.assertFalse(backup._should_use_wizard_for_backup(BackupArgs()))


if __name__ == "__main__":
    unittest.main()
