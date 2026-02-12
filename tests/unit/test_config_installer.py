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

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.config import installer


def _create_design(root: Path, name: str) -> Path:
    design_dir = root / name
    design_dir.mkdir(parents=True, exist_ok=True)
    for filename in installer.TEMPLATE_FILENAMES:
        (design_dir / filename).write_text(f"{name}:{filename}", encoding="utf-8")
    return design_dir


class TestConfigInstaller(unittest.TestCase):
    def test_user_config_dir_precedence(self) -> None:
        with mock.patch.dict(
            os.environ,
            {installer.XDG_CONFIG_ENV: "/tmp/xdg"},
            clear=False,
        ):
            with mock.patch.object(installer.sys, "platform", "linux"):
                self.assertEqual(installer._user_config_dir(), Path("/tmp/xdg/ethernity"))

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(installer.XDG_CONFIG_ENV, None)
            with mock.patch.object(installer.sys, "platform", "darwin"):
                with mock.patch.object(installer.Path, "home", return_value=Path("/Users/example")):
                    self.assertEqual(
                        installer._user_config_dir(),
                        Path("/Users/example/.config/ethernity"),
                    )

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(installer.XDG_CONFIG_ENV, None)
            with mock.patch.object(installer.sys, "platform", "linux"):
                with mock.patch.object(
                    installer, "user_config_dir", return_value="/opt/config/ethernity"
                ):
                    self.assertEqual(installer._user_config_dir(), Path("/opt/config/ethernity"))

    def test_build_paths_contains_expected_required_files(self) -> None:
        with mock.patch.object(installer, "_user_config_dir", return_value=Path("/tmp/usercfg")):
            paths = installer._build_paths()

        self.assertEqual(paths.user_config_dir, Path("/tmp/usercfg"))
        self.assertEqual(paths.user_templates_root, Path("/tmp/usercfg/templates"))
        self.assertEqual(paths.user_templates_dir, Path("/tmp/usercfg/templates/ledger"))
        self.assertEqual(paths.user_config_path, Path("/tmp/usercfg/config.toml"))
        self.assertEqual(len(paths.user_template_paths), 5)
        self.assertEqual(len(paths.user_required_files), 6)
        self.assertIn(paths.user_config_path, paths.user_required_files)

    def test_list_template_designs_handles_missing_and_filters_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir) / "package"
            user_cfg = Path(tmpdir) / "usercfg"
            with mock.patch.object(installer, "PACKAGE_ROOT", package_root):
                with mock.patch.object(installer, "_user_config_dir", return_value=user_cfg):
                    self.assertEqual(installer.list_template_designs(), {})

                    templates_root = package_root / "templates"
                    templates_root.mkdir(parents=True, exist_ok=True)

                    _create_design(templates_root, "ledger")
                    _create_design(templates_root, "maritime")
                    _create_design(templates_root, ".hidden")
                    (templates_root / "file.txt").write_text("x", encoding="utf-8")
                    (templates_root / "invalid").mkdir(parents=True, exist_ok=True)
                    (templates_root / "_shared").mkdir(parents=True, exist_ok=True)

                    user_ledger = _create_design(user_cfg / "templates", "ledger")
                    result = installer.list_template_designs()

        self.assertEqual(set(result.keys()), {"ledger", "maritime"})
        self.assertEqual(result["ledger"], user_ledger)
        self.assertEqual(result["maritime"], package_root / "templates" / "maritime")

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
                    self.assertTrue(installer._ensure_user_config(paths))
            copy_mock.assert_called_once()
            copy_designs_mock.assert_called_once_with(paths)
            self.assertTrue(paths.user_config_dir.is_dir())
            self.assertTrue(paths.user_templates_root.is_dir())

            with mock.patch.object(installer, "_copy_if_missing", side_effect=OSError("denied")):
                self.assertFalse(installer._ensure_user_config(paths))

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
