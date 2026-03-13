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

from ethernity.config import api_config, installer

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "src" / "ethernity" / "config" / "config.toml"


class TestApiConfigService(unittest.TestCase):
    def test_get_api_config_snapshot_uses_user_config_target(self) -> None:
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

        self.assertEqual(snapshot.source, "user")
        self.assertTrue(snapshot.path.endswith("config.toml"))
        self.assertIn("template_designs", snapshot.options)
        self.assertIn("available_fields", snapshot.onboarding)

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
        self.assertEqual(snapshot.values["page"], {"size": "LETTER"})
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
        self.assertEqual(parsed["defaults"]["backup"]["output_dir"], "/tmp/backups")

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
