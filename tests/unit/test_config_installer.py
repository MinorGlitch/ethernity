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

import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from ethernity.config import installer
from ethernity.core import app_paths


def _home_env(home: Path) -> dict[str, str]:
    env = {"HOME": str(home), "USERPROFILE": str(home)}
    drive, tail = os.path.splitdrive(str(home))
    if drive:
        env["HOMEDRIVE"] = drive
        env["HOMEPATH"] = tail or "\\"
    return env


def _create_design(root: Path, name: str) -> Path:
    design_dir = root / name
    design_dir.mkdir(parents=True, exist_ok=True)
    for filename in installer.TEMPLATE_FILENAMES:
        (design_dir / filename).write_text(f"{name}:{filename}", encoding="utf-8")
    return design_dir


class TestConfigInstaller(unittest.TestCase):
    def test_first_run_onboarding_marker_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "config"
            with mock.patch.object(installer, "user_config_dir_path", return_value=config_root):
                self.assertTrue(installer.first_run_onboarding_needed())
                marker = installer.mark_first_run_onboarding_complete()
                self.assertEqual(marker, config_root / ".first_run_onboarding_v1.done")
                self.assertTrue(marker.is_file())
                self.assertFalse(installer.first_run_onboarding_needed())
                self.assertEqual(installer.first_run_onboarding_configured_fields(), frozenset())

    def test_first_run_onboarding_marker_tracks_configured_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "config"
            with mock.patch.object(installer, "user_config_dir_path", return_value=config_root):
                installer.mark_first_run_onboarding_complete(
                    configured_fields={
                        installer.ONBOARDING_FIELD_TEMPLATE_DESIGN,
                        installer.ONBOARDING_FIELD_SHARDING,
                    }
                )
                self.assertEqual(
                    installer.first_run_onboarding_configured_fields(),
                    frozenset(
                        {
                            installer.ONBOARDING_FIELD_TEMPLATE_DESIGN,
                            installer.ONBOARDING_FIELD_SHARDING,
                        }
                    ),
                )

    def test_apply_first_run_defaults_updates_existing_config(self) -> None:
        initial = (
            """
[templates]
default_name = "sentinel"

[template]
name = "sentinel"

[recovery_template]
name = "sentinel"

[shard_template]
name = "sentinel"

[signing_key_shard_template]
name = "sentinel"

[kit_template]
name = "sentinel"

[defaults.backup]
payload_codec = "auto"
qr_payload_codec = "raw"
""".strip()
            + "\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(initial, encoding="utf-8")
            with mock.patch.object(
                installer,
                "resolve_template_design_path",
                return_value=Path("/tmp/forge"),
            ):
                updated_path = installer.apply_first_run_defaults(
                    config_path,
                    design="forge",
                    payload_codec="gzip",
                    qr_payload_codec="base64",
                    page_size="LETTER",
                    backup_output_dir="/tmp/backups",
                    qr_chunk_size=384,
                    shard_threshold=2,
                    shard_count=3,
                    signing_key_mode="sharded",
                )
            self.assertEqual(updated_path, config_path)
            parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(parsed["templates"]["default_name"], "forge")
        self.assertEqual(parsed["template"]["name"], "forge")
        self.assertEqual(parsed["recovery_template"]["name"], "forge")
        self.assertEqual(parsed["shard_template"]["name"], "forge")
        self.assertEqual(parsed["signing_key_shard_template"]["name"], "forge")
        self.assertEqual(parsed["kit_template"]["name"], "forge")
        self.assertEqual(parsed["defaults"]["backup"]["payload_codec"], "gzip")
        self.assertEqual(parsed["defaults"]["backup"]["qr_payload_codec"], "base64")
        self.assertEqual(parsed["page"]["size"], "LETTER")
        self.assertEqual(parsed["defaults"]["backup"]["output_dir"], "/tmp/backups")
        self.assertEqual(parsed["qr"]["chunk_size"], 384)
        self.assertEqual(parsed["defaults"]["backup"]["shard_threshold"], 2)
        self.assertEqual(parsed["defaults"]["backup"]["shard_count"], 3)
        self.assertEqual(parsed["defaults"]["backup"]["signing_key_mode"], "sharded")

    def test_upsert_table_key_updates_dotted_assignment(self) -> None:
        text = 'defaults.backup.payload_codec = "raw"\n'
        updated = installer._upsert_table_key(
            text,
            table="defaults.backup",
            key="payload_codec",
            value='"gzip"',
        )
        self.assertEqual(tomllib.loads(updated)["defaults"]["backup"]["payload_codec"], "gzip")

    def test_upsert_table_key_preserves_dotted_table_style_without_header(self) -> None:
        text = 'defaults.backup.payload_codec = "raw"\ndefaults.backup.qr_payload_codec = "raw"\n'
        updated = installer._upsert_table_key(
            text,
            table="defaults.backup",
            key="output_dir",
            value='"/tmp/backups"',
        )
        self.assertNotIn("[defaults.backup]", updated)
        parsed = tomllib.loads(updated)
        self.assertEqual(parsed["defaults"]["backup"]["output_dir"], "/tmp/backups")

    def test_upsert_table_key_ignores_hash_inside_string_values(self) -> None:
        text = '[defaults.backup]\noutput_dir = "C:/tmp/#archive"\n'
        updated = installer._upsert_table_key(
            text,
            table="defaults.backup",
            key="output_dir",
            value='"D:/target"',
        )
        parsed = tomllib.loads(updated)
        self.assertEqual(parsed["defaults"]["backup"]["output_dir"], "D:/target")

    def test_user_config_dir_precedence(self) -> None:
        with mock.patch.dict(
            os.environ,
            {app_paths.XDG_CONFIG_ENV: "/tmp/xdg"},
            clear=False,
        ):
            with mock.patch.object(app_paths.sys, "platform", "linux"):
                self.assertEqual(app_paths.user_config_dir_path(), Path("/tmp/xdg/ethernity"))

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(app_paths.XDG_CONFIG_ENV, None)
            with mock.patch.object(app_paths.sys, "platform", "darwin"):
                with mock.patch.object(app_paths.Path, "home", return_value=Path("/Users/example")):
                    self.assertEqual(
                        app_paths.user_config_dir_path(),
                        Path("/Users/example/.config/ethernity"),
                    )

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(app_paths.XDG_CONFIG_ENV, None)
            with mock.patch.object(app_paths.sys, "platform", "linux"):
                with mock.patch.object(
                    app_paths,
                    "user_config_dir",
                    return_value="/opt/config/ethernity",
                ):
                    self.assertEqual(
                        app_paths.user_config_dir_path(),
                        Path("/opt/config/ethernity"),
                    )

    def test_build_paths_contains_expected_required_files(self) -> None:
        user_cfg = Path("/tmp/usercfg")
        with mock.patch.object(installer, "user_config_dir_path", return_value=user_cfg):
            with mock.patch.object(
                installer, "user_templates_root_path", return_value=user_cfg / "templates"
            ):
                with mock.patch.object(
                    installer,
                    "user_templates_design_path",
                    side_effect=lambda design: user_cfg / "templates" / design,
                ):
                    with mock.patch.object(
                        installer,
                        "user_config_file_path",
                        return_value=user_cfg / "config.toml",
                    ):
                        paths = installer._build_paths()

        self.assertEqual(paths.user_config_dir, Path("/tmp/usercfg"))
        self.assertEqual(paths.user_templates_root, Path("/tmp/usercfg/templates"))
        self.assertEqual(paths.user_templates_dir, Path("/tmp/usercfg/templates/sentinel"))
        self.assertEqual(paths.user_config_path, Path("/tmp/usercfg/config.toml"))
        self.assertEqual(len(paths.user_template_paths), 5)
        self.assertEqual(len(paths.user_required_files), 6)
        self.assertIn(paths.user_config_path, paths.user_required_files)

    def test_list_template_designs_handles_missing_and_filters_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir) / "package"
            user_cfg = Path(tmpdir) / "usercfg"
            with mock.patch.object(installer, "PACKAGE_ROOT", package_root):
                with mock.patch.object(installer, "user_config_dir_path", return_value=user_cfg):
                    with mock.patch.object(
                        installer, "user_templates_root_path", return_value=user_cfg / "templates"
                    ):
                        self.assertEqual(installer.list_template_designs(), {})

                        templates_root = package_root / "templates"
                        templates_root.mkdir(parents=True, exist_ok=True)

                        _create_design(templates_root, "ledger")
                        _create_design(templates_root, "maritime")
                        _create_design(templates_root, "archive_stack")
                        _create_design(templates_root, "maritime_ledger")
                        _create_design(templates_root, "shadow_archive")
                        _create_design(templates_root, ".hidden")
                        (templates_root / "file.txt").write_text("x", encoding="utf-8")
                        (templates_root / "invalid").mkdir(parents=True, exist_ok=True)
                        (templates_root / "_shared").mkdir(parents=True, exist_ok=True)

                        user_ledger = _create_design(user_cfg / "templates", "ledger")
                        result = installer.list_template_designs()

        self.assertEqual(set(result.keys()), {"ledger", "maritime"})
        self.assertEqual(result["ledger"], user_ledger)
        self.assertEqual(result["maritime"], package_root / "templates" / "maritime")
        self.assertNotIn("archive_stack", result)
        self.assertNotIn("maritime_ledger", result)
        self.assertNotIn("shadow_archive", result)

    def test_resolve_template_design_path_variants(self) -> None:
        designs = {
            "Ledger": Path("/tmp/ledger"),
            "forge": Path("/tmp/forge"),
        }
        with mock.patch.object(installer, "list_template_designs", return_value=designs):
            self.assertEqual(installer.resolve_template_design_path("forge"), Path("/tmp/forge"))
            self.assertEqual(installer.resolve_template_design_path("ledger"), Path("/tmp/ledger"))
            with self.assertRaisesRegex(ValueError, "cannot be empty"):
                installer.resolve_template_design_path("   ")
            with self.assertRaisesRegex(ValueError, "unknown template design"):
                installer.resolve_template_design_path("nope")

    def test_init_user_config_success_and_failure(self) -> None:
        paths = installer.ConfigPaths(
            user_config_dir=Path("/tmp/config"),
            user_templates_root=Path("/tmp/config/templates"),
            user_templates_dir=Path("/tmp/config/templates/ledger"),
            user_config_path=Path("/tmp/config/config.toml"),
            user_template_paths={},
            user_required_files=(),
        )
        with mock.patch.object(installer, "_build_paths", return_value=paths):
            with mock.patch.object(installer, "_ensure_user_config", return_value=True):
                self.assertEqual(installer.init_user_config(), Path("/tmp/config"))
            with mock.patch.object(installer, "_ensure_user_config", return_value=False):
                with self.assertRaisesRegex(OSError, "unable to create config dir"):
                    installer.init_user_config()

    def test_user_config_needs_init_true_and_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            existing = root / "existing.txt"
            missing = root / "missing.txt"
            existing.write_text("ok", encoding="utf-8")
            paths = installer.ConfigPaths(
                user_config_dir=root,
                user_templates_root=root / "templates",
                user_templates_dir=root / "templates" / "ledger",
                user_config_path=root / "config.toml",
                user_template_paths={},
                user_required_files=(existing, missing),
            )
            with mock.patch.object(installer, "_build_paths", return_value=paths):
                self.assertTrue(installer.user_config_needs_init())
            missing.write_text("ok", encoding="utf-8")
            with mock.patch.object(installer, "_build_paths", return_value=paths):
                self.assertFalse(installer.user_config_needs_init())

    def test_resolve_config_path_paths(self) -> None:
        explicit = installer.resolve_config_path("custom.toml")
        self.assertEqual(explicit, Path("custom.toml"))
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            with mock.patch.dict(os.environ, _home_env(home), clear=False):
                self.assertEqual(
                    installer.resolve_config_path("~/custom.toml"),
                    home / "custom.toml",
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config.toml"
            config_path.write_text("x", encoding="utf-8")
            paths = installer.ConfigPaths(
                user_config_dir=root,
                user_templates_root=root / "templates",
                user_templates_dir=root / "templates" / "ledger",
                user_config_path=config_path,
                user_template_paths={},
                user_required_files=(),
            )
            with mock.patch.object(installer, "_build_paths", return_value=paths):
                with mock.patch.object(installer, "_ensure_user_config", return_value=True):
                    self.assertEqual(installer.resolve_config_path(), config_path)
            with mock.patch.object(installer, "_build_paths", return_value=paths):
                with mock.patch.object(installer, "_ensure_user_config", return_value=False):
                    self.assertEqual(installer.resolve_config_path(), installer.DEFAULT_CONFIG_PATH)

    def test_ensure_user_config_success_and_oserror(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = installer.ConfigPaths(
                user_config_dir=root / "cfg",
                user_templates_root=root / "cfg" / "templates",
                user_templates_dir=root / "cfg" / "templates" / "ledger",
                user_config_path=root / "cfg" / "config.toml",
                user_template_paths={},
                user_required_files=(),
            )
            with mock.patch.object(installer, "_copy_if_missing") as copy_mock:
                with mock.patch.object(installer, "_copy_template_designs") as copy_designs_mock:
                    with mock.patch.object(
                        installer,
                        "_migrate_user_config",
                        return_value=False,
                    ) as migrate_mock:
                        with mock.patch.object(
                            installer,
                            "get_ethernity_version",
                            return_value="9.9.9",
                        ):
                            self.assertTrue(installer._ensure_user_config(paths))
            copy_mock.assert_called_once()
            migrate_mock.assert_called_once_with(paths.user_config_path)
            copy_designs_mock.assert_called_once_with(paths, overwrite=True)
            self.assertTrue(paths.user_config_dir.is_dir())
            self.assertTrue(paths.user_templates_root.is_dir())

            with mock.patch.object(installer, "_copy_if_missing", side_effect=OSError("denied")):
                self.assertFalse(installer._ensure_user_config(paths))

    def test_ensure_user_config_reuses_synced_version_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = installer.ConfigPaths(
                user_config_dir=root / "cfg",
                user_templates_root=root / "cfg" / "templates",
                user_templates_dir=root / "cfg" / "templates" / "ledger",
                user_config_path=root / "cfg" / "config.toml",
                user_template_paths={},
                user_required_files=(),
            )

            with mock.patch.object(installer, "_copy_if_missing"):
                with mock.patch.object(installer, "_migrate_user_config", return_value=False):
                    with mock.patch.object(
                        installer, "_copy_template_designs"
                    ) as copy_designs_mock:
                        with mock.patch.object(
                            installer,
                            "get_ethernity_version",
                            return_value="9.9.9",
                        ):
                            self.assertTrue(installer._ensure_user_config(paths))
                            copy_designs_mock.assert_called_once_with(paths, overwrite=True)

                            state_path = (
                                paths.user_templates_root / installer._TEMPLATE_SYNC_STATE_FILENAME
                            )
                            state = json.loads(state_path.read_text(encoding="utf-8"))
                            self.assertEqual(state["template_version"], "9.9.9")

                            copy_designs_mock.reset_mock()
                            self.assertTrue(installer._ensure_user_config(paths))
                            copy_designs_mock.assert_called_once_with(paths, overwrite=False)

    def test_ensure_user_config_migrates_stale_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "cfg" / "config.toml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            original = '[defaults.backup]\npayload_codec = "auto"\n'
            config_path.write_text(original, encoding="utf-8")

            paths = installer.ConfigPaths(
                user_config_dir=root / "cfg",
                user_templates_root=root / "cfg" / "templates",
                user_templates_dir=root / "cfg" / "templates" / "ledger",
                user_config_path=config_path,
                user_template_paths={},
                user_required_files=(),
            )

            with mock.patch.object(installer, "_copy_template_designs") as copy_designs_mock:
                with mock.patch.object(
                    installer,
                    "get_ethernity_version",
                    return_value="9.9.9",
                ):
                    self.assertTrue(installer._ensure_user_config(paths))
            copy_designs_mock.assert_called_once_with(paths, overwrite=True)

            migrated = config_path.read_text(encoding="utf-8")
            self.assertIn('qr_payload_codec = "raw"', migrated)

            backup_path = config_path.with_name("config.toml.bak")
            self.assertTrue(backup_path.is_file())
            self.assertEqual(backup_path.read_text(encoding="utf-8"), original)

    def test_inject_missing_backup_qr_payload_codec_when_section_missing(self) -> None:
        text = "[ui]\nquiet = false\n"
        migrated = installer._inject_missing_backup_qr_payload_codec(text)
        self.assertIsNotNone(migrated)
        migrated_text = "" if migrated is None else migrated
        self.assertIn("[defaults.backup]", migrated_text)
        self.assertIn('qr_payload_codec = "raw"', migrated_text)

    def test_inject_missing_backup_qr_payload_codec_skips_malformed_defaults_shape(self) -> None:
        text = "defaults = 3\n"
        self.assertIsNone(installer._inject_missing_backup_qr_payload_codec(text))

    def test_inject_missing_backup_qr_payload_codec_supports_dotted_keys(self) -> None:
        text = 'defaults.backup.payload_codec = "auto"\n'
        migrated = installer._inject_missing_backup_qr_payload_codec(text)
        self.assertIsNotNone(migrated)
        migrated_text = "" if migrated is None else migrated
        self.assertNotIn("[defaults.backup]", migrated_text)
        self.assertIn('defaults.backup.qr_payload_codec = "raw"', migrated_text)
        self.assertEqual(
            tomllib.loads(migrated_text)["defaults"]["backup"]["qr_payload_codec"],
            "raw",
        )

    def test_inject_missing_backup_qr_payload_codec_skips_inline_backup_table(self) -> None:
        text = '[defaults]\nbackup = { payload_codec = "auto" }\n'
        self.assertIsNone(installer._inject_missing_backup_qr_payload_codec(text))

    def test_migrate_user_config_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text('[defaults.backup]\npayload_codec = "auto"\n', encoding="utf-8")

            self.assertTrue(installer._migrate_user_config(path))
            self.assertFalse(installer._migrate_user_config(path))

            backup_path = path.with_name("config.toml.bak")
            self.assertTrue(backup_path.is_file())

    def test_apply_config_migrations_runs_in_order(self) -> None:
        steps = (
            installer.ConfigMigrationStep(
                migration_id="first",
                apply=lambda text: text.replace("[x]", "[y]") if "[x]" in text else None,
            ),
            installer.ConfigMigrationStep(
                migration_id="second",
                apply=(
                    lambda text: (
                        text + 'qr_payload_codec = "raw"\n' if text.endswith("[y]\n") else None
                    )
                ),
            ),
        )
        updated, applied = installer._apply_config_migrations("[x]\n", steps)
        self.assertEqual(updated, '[y]\nqr_payload_codec = "raw"\n')
        self.assertEqual(applied, ("first", "second"))

    def test_apply_config_migrations_ignores_noop_changes(self) -> None:
        steps = (
            installer.ConfigMigrationStep(
                migration_id="noop",
                apply=lambda text: text,
            ),
        )
        updated, applied = installer._apply_config_migrations("[defaults.backup]\n", steps)
        self.assertEqual(updated, "[defaults.backup]\n")
        self.assertEqual(applied, ())

    def test_copy_template_designs_shared_and_design_copy_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_root = root / "package"
            templates_root = package_root / "templates"
            shared = templates_root / "_shared"
            shared.mkdir(parents=True, exist_ok=True)
            (shared / "a.txt").write_text("a", encoding="utf-8")
            (shared / ".secret").write_text("secret", encoding="utf-8")
            (shared / "nested").mkdir(parents=True, exist_ok=True)
            (shared / "nested" / "b.txt").write_text("b", encoding="utf-8")

            _create_design(templates_root, "ledger")
            invalid = templates_root / "invalid"
            invalid.mkdir(parents=True, exist_ok=True)
            (invalid / "main_document.html.j2").write_text("x", encoding="utf-8")
            (templates_root / ".dotdesign").mkdir(parents=True, exist_ok=True)

            paths = installer.ConfigPaths(
                user_config_dir=root / "cfg",
                user_templates_root=root / "cfg" / "templates",
                user_templates_dir=root / "cfg" / "templates" / "ledger",
                user_config_path=root / "cfg" / "config.toml",
                user_template_paths={},
                user_required_files=(),
            )
            with mock.patch.object(installer, "PACKAGE_ROOT", package_root):
                installer._copy_template_designs(paths)
            self.assertTrue((paths.user_templates_root / "_shared" / "a.txt").is_file())
            self.assertTrue((paths.user_templates_root / "_shared" / "nested" / "b.txt").is_file())
            self.assertFalse((paths.user_templates_root / "_shared" / ".secret").exists())
            for filename in installer.TEMPLATE_FILENAMES:
                self.assertTrue((paths.user_templates_root / "ledger" / filename).is_file())
            self.assertFalse((paths.user_templates_root / "invalid").exists())

    def test_copy_template_designs_overwrite_flag_controls_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_root = root / "package"
            templates_root = package_root / "templates"

            _create_design(templates_root, "ledger")

            paths = installer.ConfigPaths(
                user_config_dir=root / "cfg",
                user_templates_root=root / "cfg" / "templates",
                user_templates_dir=root / "cfg" / "templates" / "ledger",
                user_config_path=root / "cfg" / "config.toml",
                user_template_paths={},
                user_required_files=(),
            )
            existing_path = (
                paths.user_templates_root / "ledger" / installer.DEFAULT_TEMPLATE_PATH.name
            )
            existing_path.parent.mkdir(parents=True, exist_ok=True)
            existing_path.write_text("custom-user-template", encoding="utf-8")

            with mock.patch.object(installer, "PACKAGE_ROOT", package_root):
                installer._copy_template_designs(paths, overwrite=False)
                self.assertEqual(existing_path.read_text(encoding="utf-8"), "custom-user-template")

                installer._copy_template_designs(paths, overwrite=True)
                self.assertEqual(
                    existing_path.read_text(encoding="utf-8"),
                    f"ledger:{installer.DEFAULT_TEMPLATE_PATH.name}",
                )

    def test_copy_template_designs_no_package_templates_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = installer.ConfigPaths(
                user_config_dir=root / "cfg",
                user_templates_root=root / "cfg" / "templates",
                user_templates_dir=root / "cfg" / "templates" / "ledger",
                user_config_path=root / "cfg" / "config.toml",
                user_template_paths={},
                user_required_files=(),
            )
            with mock.patch.object(installer, "PACKAGE_ROOT", root / "missing-package"):
                installer._copy_template_designs(paths)
            self.assertFalse(paths.user_templates_root.exists())

    def test_copy_if_missing_respects_existing_and_copies_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.txt"
            source.write_text("new", encoding="utf-8")
            existing_dest = root / "existing" / "dest.txt"
            existing_dest.parent.mkdir(parents=True, exist_ok=True)
            existing_dest.write_text("old", encoding="utf-8")

            installer._copy_if_missing(source, existing_dest)
            self.assertEqual(existing_dest.read_text(encoding="utf-8"), "old")

            fresh_dest = root / "fresh" / "dest.txt"
            installer._copy_if_missing(source, fresh_dest)
            self.assertEqual(fresh_dest.read_text(encoding="utf-8"), "new")


if __name__ == "__main__":
    unittest.main()
