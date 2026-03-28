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

import tempfile
import tomllib
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

import ethernity.config.api_patch as api_config
import ethernity.config.install as installer
from ethernity.config.install import ONBOARDING_FIELDS
from ethernity.config.paths import DEFAULT_CONFIG_PATH

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestApiConfigService(unittest.TestCase):
    def test_get_api_config_snapshot_uses_default_target_when_user_config_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "config"
            with mock.patch.multiple(
                installer,
                user_config_dir_path=mock.Mock(return_value=config_root),
                user_config_file_path=mock.Mock(side_effect=lambda name: config_root / name),
                user_templates_root_path=mock.Mock(return_value=config_root / "templates"),
                user_templates_design_path=mock.Mock(
                    side_effect=lambda design: config_root / "templates" / design
                ),
            ):
                snapshot = api_config.get_api_config_snapshot()

        templates = cast(dict[str, Any], snapshot.values["templates"])
        self.assertEqual(snapshot.source, "default")
        self.assertEqual(snapshot.status, "valid")
        self.assertEqual(snapshot.errors, ())
        self.assertEqual(snapshot.path, str(DEFAULT_CONFIG_PATH))
        self.assertEqual(
            snapshot.options["template_designs"],
            ["archive", "forge", "ledger", "maritime", "sentinel"],
        )
        self.assertEqual(snapshot.options["onboarding_fields"], list(ONBOARDING_FIELDS))
        self.assertFalse(snapshot.onboarding["needed"])
        self.assertEqual(snapshot.onboarding["configured_fields"], [])
        self.assertIn("template_name", templates)

    def test_get_api_config_snapshot_uses_user_config_target_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "config"
            config_root.mkdir(parents=True, exist_ok=True)
            (config_root / "config.toml").write_text(
                DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            with mock.patch.multiple(
                installer,
                user_config_dir_path=mock.Mock(return_value=config_root),
                user_config_file_path=mock.Mock(side_effect=lambda name: config_root / name),
                user_templates_root_path=mock.Mock(return_value=config_root / "templates"),
                user_templates_design_path=mock.Mock(
                    side_effect=lambda design: config_root / "templates" / design
                ),
            ):
                snapshot = api_config.get_api_config_snapshot()

        self.assertEqual(snapshot.source, "user")
        self.assertEqual(snapshot.status, "valid")
        self.assertTrue(snapshot.path.endswith("config.toml"))

    def test_apply_api_config_patch_updates_values_and_onboarding_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "config"
            with mock.patch.multiple(
                installer,
                user_config_dir_path=mock.Mock(return_value=config_root),
                user_config_file_path=mock.Mock(side_effect=lambda name: config_root / name),
                user_templates_root_path=mock.Mock(return_value=config_root / "templates"),
                user_templates_design_path=mock.Mock(
                    side_effect=lambda design: config_root / "templates" / design
                ),
            ):
                snapshot = api_config.apply_api_config_patch(
                    None,
                    {
                        "values": {
                            "templates": {"template_name": "ledger"},
                            "page": {"size": "LETTER"},
                            "defaults": {"backup": {"output_dir": "/tmp/backups"}},
                        },
                        "onboarding": {
                            "mark_complete": True,
                            "configured_fields": ["page_size", "backup_output_dir"],
                        },
                    },
                )
                parsed = tomllib.loads(Path(snapshot.path).read_text(encoding="utf-8"))

        defaults = snapshot.values["defaults"]
        templates = cast(dict[str, Any], snapshot.values["templates"])
        self.assertEqual(snapshot.values["page"], {"size": "LETTER"})
        self.assertEqual(templates["template_name"], "ledger")
        self.assertIsInstance(defaults, dict)
        backup = cast(dict[str, Any], defaults)["backup"]
        self.assertIsInstance(backup, dict)
        self.assertEqual(backup["output_dir"], "/tmp/backups")
        self.assertFalse(snapshot.onboarding["needed"])
        self.assertEqual(
            snapshot.onboarding["configured_fields"],
            ["backup_output_dir", "page_size"],
        )
        self.assertEqual(parsed["page"]["size"], "LETTER")
        self.assertEqual(parsed["template"]["name"], "ledger")
        self.assertEqual(parsed["defaults"]["backup"]["output_dir"], "/tmp/backups")

    def test_get_api_config_snapshot_reports_invalid_toml_and_defaults(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".toml") as handle:
            path = Path(handle.name)
            path.write_text('[defaults.backup\noutput_dir = "oops"\n', encoding="utf-8")
            snapshot = api_config.get_api_config_snapshot(path)

        page = cast(dict[str, Any], snapshot.values["page"])
        self.assertEqual(snapshot.status, "invalid_toml")
        self.assertTrue(snapshot.errors)
        self.assertEqual(page["size"], "A4")

    def test_apply_api_config_patch_repairs_invalid_current_values(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".toml") as handle:
            path = Path(handle.name)
            path.write_text(
                DEFAULT_CONFIG_PATH.read_text(encoding="utf-8").replace(
                    'size = "A4"',
                    'size = "Letter"',
                    1,
                ),
                encoding="utf-8",
            )
            snapshot = api_config.apply_api_config_patch(
                path,
                {"values": {"ui": {"quiet": True}}},
            )
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(snapshot.status, "valid")
        self.assertEqual(parsed["page"]["size"], "LETTER")
        self.assertEqual(parsed["ui"]["quiet"], True)

    def test_apply_api_config_patch_repairs_invalid_toml(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".toml") as handle:
            path = Path(handle.name)
            path.write_text('[defaults.backup\noutput_dir = "oops"\n', encoding="utf-8")
            snapshot = api_config.apply_api_config_patch(
                path,
                {"values": {"page": {"size": "LETTER"}}},
            )
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(snapshot.status, "valid")
        self.assertEqual(parsed["page"]["size"], "LETTER")

    def test_apply_api_config_patch_resets_onboarding_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "config"
            with mock.patch.multiple(
                installer,
                user_config_dir_path=mock.Mock(return_value=config_root),
                user_config_file_path=mock.Mock(side_effect=lambda name: config_root / name),
                user_templates_root_path=mock.Mock(return_value=config_root / "templates"),
                user_templates_design_path=mock.Mock(
                    side_effect=lambda design: config_root / "templates" / design
                ),
            ):
                api_config.apply_api_config_patch(
                    None,
                    {
                        "onboarding": {
                            "mark_complete": True,
                            "configured_fields": ["page_size"],
                        }
                    },
                )
                snapshot = api_config.apply_api_config_patch(
                    None,
                    {"onboarding": {"mark_complete": False}},
                )

        self.assertTrue(snapshot.onboarding["needed"])
        self.assertEqual(snapshot.onboarding["configured_fields"], [])

    def test_apply_api_config_patch_preserves_existing_template_overrides(self) -> None:
        initial = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
        initial = initial.replace(
            '[template]\nname = "sentinel"',
            '[template]\nname = "ledger"',
            1,
        )
        initial = initial.replace(
            '[recovery_template]\nname = "sentinel"',
            '[recovery_template]\nname = "forge"',
            1,
        )
        with tempfile.NamedTemporaryFile(suffix=".toml") as handle:
            path = Path(handle.name)
            path.write_text(initial, encoding="utf-8")
            snapshot = api_config.apply_api_config_patch(
                path,
                {"values": {"ui": {"quiet": True}}},
            )
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))

        templates = cast(dict[str, Any], snapshot.values["templates"])
        self.assertEqual(templates["template_name"], "ledger")
        self.assertEqual(templates["recovery_template_name"], "forge")
        self.assertEqual(parsed["template"]["name"], "ledger")
        self.assertEqual(parsed["recovery_template"]["name"], "forge")

    def test_apply_api_config_patch_reverts_config_when_marker_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "config"
            with mock.patch.multiple(
                installer,
                user_config_dir_path=mock.Mock(return_value=config_root),
                user_config_file_path=mock.Mock(side_effect=lambda name: config_root / name),
                user_templates_root_path=mock.Mock(return_value=config_root / "templates"),
                user_templates_design_path=mock.Mock(
                    side_effect=lambda design: config_root / "templates" / design
                ),
            ):
                config_path = installer.resolve_writable_config_path(None)
                original = config_path.read_text(encoding="utf-8")
                original_write_text_atomic = installer._write_text_atomic

                def _fail_on_marker(path: Path, text: str) -> None:
                    if path.name == ".first_run_onboarding_v1.done":
                        raise OSError("marker write failed")
                    original_write_text_atomic(path, text)

                with (
                    mock.patch(
                        "ethernity.config.api_patch._write_text_atomic",
                        side_effect=_fail_on_marker,
                    ),
                    mock.patch.object(installer, "_write_text_atomic", side_effect=_fail_on_marker),
                ):
                    with self.assertRaises(OSError):
                        api_config.apply_api_config_patch(
                            None,
                            {
                                "values": {"page": {"size": "LETTER"}},
                                "onboarding": {"mark_complete": True, "configured_fields": []},
                            },
                        )

                self.assertEqual(config_path.read_text(encoding="utf-8"), original)

    def test_get_api_config_snapshot_for_explicit_config_hides_onboarding_state(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".toml") as handle:
            path = Path(handle.name)
            path.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            with mock.patch(
                "ethernity.config.api_patch.first_run_onboarding_configured_fields",
                return_value=frozenset({installer.ONBOARDING_FIELD_PAGE_SIZE}),
            ):
                snapshot = api_config.get_api_config_snapshot(path)

        self.assertEqual(snapshot.source, "explicit")
        self.assertFalse(snapshot.onboarding["needed"])
        self.assertEqual(snapshot.onboarding["configured_fields"], [])

    def test_apply_api_config_patch_requires_explicit_onboarding_mark_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "config"
            with mock.patch.multiple(
                installer,
                user_config_dir_path=mock.Mock(return_value=config_root),
                user_config_file_path=mock.Mock(side_effect=lambda name: config_root / name),
                user_templates_root_path=mock.Mock(return_value=config_root / "templates"),
                user_templates_design_path=mock.Mock(
                    side_effect=lambda design: config_root / "templates" / design
                ),
            ):
                with self.assertRaises(api_config.ConfigPatchError) as raised:
                    api_config.apply_api_config_patch(
                        None,
                        {
                            "values": {"page": {"size": "LETTER"}},
                            "onboarding": {"configured_fields": []},
                        },
                    )

        self.assertEqual(raised.exception.code, "CONFIG_INVALID_VALUE")

    def test_apply_api_config_patch_rejects_empty_onboarding_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "config"
            with mock.patch.multiple(
                installer,
                user_config_dir_path=mock.Mock(return_value=config_root),
                user_config_file_path=mock.Mock(side_effect=lambda name: config_root / name),
                user_templates_root_path=mock.Mock(return_value=config_root / "templates"),
                user_templates_design_path=mock.Mock(
                    side_effect=lambda design: config_root / "templates" / design
                ),
            ):
                with self.assertRaises(api_config.ConfigPatchError) as raised:
                    api_config.apply_api_config_patch(None, {"onboarding": {}})

        self.assertEqual(raised.exception.code, "CONFIG_INVALID_VALUE")

    def test_apply_api_config_patch_invalid_values_do_not_initialize_user_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "config"
            config_path = config_root / "config.toml"
            with mock.patch.multiple(
                installer,
                user_config_dir_path=mock.Mock(return_value=config_root),
                user_config_file_path=mock.Mock(side_effect=lambda name: config_root / name),
                user_templates_root_path=mock.Mock(return_value=config_root / "templates"),
                user_templates_design_path=mock.Mock(
                    side_effect=lambda design: config_root / "templates" / design
                ),
            ):
                with self.assertRaises(api_config.ConfigPatchError) as raised:
                    api_config.apply_api_config_patch(None, {"values": "not-an-object"})

        self.assertEqual(raised.exception.code, "CONFIG_INVALID_VALUE")
        self.assertFalse(config_path.exists())

    def test_apply_api_config_patch_rejects_unknown_field(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".toml") as handle:
            path = Path(handle.name)
            path.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaises(api_config.ConfigPatchError) as raised:
                api_config.apply_api_config_patch(
                    path,
                    {"values": {"unknown": {"value": True}}},
                )

        self.assertEqual(raised.exception.code, "CONFIG_UNKNOWN_FIELD")

    def test_apply_api_config_patch_rejects_onboarding_for_explicit_config(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".toml") as handle:
            path = Path(handle.name)
            path.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaises(api_config.ConfigPatchError) as raised:
                api_config.apply_api_config_patch(
                    path,
                    {"onboarding": {"mark_complete": True}},
                )

        self.assertEqual(raised.exception.code, "CONFIG_CONFLICT")


if __name__ == "__main__":
    unittest.main()
