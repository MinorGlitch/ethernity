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

import tempfile
import unittest
from pathlib import Path

from ethernity.config import (
    DEFAULT_KIT_TEMPLATE_PATH,
    DEFAULT_PAPER_SIZE,
    DEFAULT_RECOVERY_TEMPLATE_PATH,
    DEFAULT_SHARD_TEMPLATE_PATH,
    DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH,
    DEFAULT_TEMPLATE_PATH,
    apply_template_design,
    load_app_config,
    load_cli_defaults,
)
from ethernity.encoding.chunking import DEFAULT_CHUNK_SIZE


class TestConfig(unittest.TestCase):
    def test_load_app_config_parses_qr_config(self) -> None:
        toml = """
[page]
size = "A4"

[qr]
scale = "6"
border = 2.0
version = "3"
mask = 2
micro = "true"
boost_error = false
dark = [1, 2, 3]
light = [4, 5, 6, 7]
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.template_path, DEFAULT_TEMPLATE_PATH)
        self.assertEqual(config.recovery_template_path, DEFAULT_RECOVERY_TEMPLATE_PATH)
        self.assertEqual(config.shard_template_path, DEFAULT_SHARD_TEMPLATE_PATH)
        self.assertEqual(
            config.signing_key_shard_template_path,
            DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH,
        )
        self.assertEqual(config.paper_size, DEFAULT_PAPER_SIZE)
        self.assertEqual(config.qr_config.scale, 6)
        self.assertEqual(config.qr_config.border, 2)
        self.assertEqual(config.qr_config.version, 3)
        self.assertEqual(config.qr_config.mask, 2)
        self.assertEqual(config.qr_config.micro, True)
        self.assertEqual(config.qr_config.dark, (1, 2, 3))
        self.assertEqual(config.qr_config.light, (4, 5, 6, 7))
        self.assertFalse(config.qr_config.boost_error)
        self.assertEqual(config.qr_chunk_size, DEFAULT_CHUNK_SIZE)

    def test_load_app_config_with_defaults(self) -> None:
        """Test loading config with minimal content uses defaults."""
        toml = """
[page]
size = "A4"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.paper_size, "A4")
        self.assertEqual(config.template_path, DEFAULT_TEMPLATE_PATH)
        self.assertEqual(config.qr_chunk_size, DEFAULT_CHUNK_SIZE)

    def test_load_app_config_empty_file(self) -> None:
        """Test loading empty config file uses all defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text("", encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.paper_size, DEFAULT_PAPER_SIZE)
        self.assertEqual(config.template_path, DEFAULT_TEMPLATE_PATH)
        self.assertEqual(config.qr_chunk_size, DEFAULT_CHUNK_SIZE)

    def test_load_app_config_missing_sections(self) -> None:
        """Test loading config with missing optional sections."""
        toml = """
[page]
size = "Letter"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.paper_size, "Letter")
        # QR config should have defaults
        self.assertIsNotNone(config.qr_config)

    def test_load_app_config_various_paper_sizes(self) -> None:
        """Test loading config with various paper sizes."""
        for paper_size in ["A4", "Letter", "Legal", "A3", "A5"]:
            toml = f"""
[page]
size = "{paper_size}"
"""
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "config.toml"
                path.write_text(toml, encoding="utf-8")
                config = load_app_config(path=path)
            self.assertEqual(config.paper_size, paper_size)

    def test_load_app_config_qr_boundary_values(self) -> None:
        """Test QR config with boundary values."""
        toml = """
[qr]
scale = 1
border = 0
version = 1
mask = 0
chunk_size = 512
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.qr_config.scale, 1)
        self.assertEqual(config.qr_config.border, 0)
        self.assertEqual(config.qr_config.version, 1)
        self.assertEqual(config.qr_config.mask, 0)
        self.assertEqual(config.qr_chunk_size, 512)

    def test_load_app_config_rejects_non_positive_chunk_size(self) -> None:
        toml = """
[qr]
chunk_size = 0
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_app_config(path=path)

    def test_load_app_config_ignores_payload_encoding_key(self) -> None:
        toml = """
[qr]
payload_encoding = "base64url"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)
        self.assertIsNotNone(config.qr_config)

    def test_load_app_config_qr_large_values(self) -> None:
        """Test QR config with larger valid values."""
        toml = """
[qr]
scale = 20
border = 10
version = 40
mask = 7
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.qr_config.scale, 20)
        self.assertEqual(config.qr_config.border, 10)
        self.assertEqual(config.qr_config.version, 40)
        self.assertEqual(config.qr_config.mask, 7)

    def test_load_app_config_template_names_per_section(self) -> None:
        toml = """
[template]
name = "sentinel"

[recovery_template]
name = "sentinel"

[shard_template]
name = "sentinel"

[signing_key_shard_template]
name = "monograph"

[kit_template]
name = "sentinel"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.template_path.parent.name, "sentinel")
        self.assertEqual(config.recovery_template_path.parent.name, "sentinel")
        self.assertEqual(config.shard_template_path.parent.name, "sentinel")
        self.assertEqual(config.signing_key_shard_template_path.parent.name, "monograph")
        self.assertEqual(config.kit_template_path.parent.name, "sentinel")
        self.assertEqual(config.template_path.name, DEFAULT_TEMPLATE_PATH.name)
        self.assertEqual(config.recovery_template_path.name, DEFAULT_RECOVERY_TEMPLATE_PATH.name)
        self.assertEqual(config.shard_template_path.name, DEFAULT_SHARD_TEMPLATE_PATH.name)
        self.assertEqual(
            config.signing_key_shard_template_path.name,
            DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH.name,
        )
        self.assertEqual(config.kit_template_path.name, DEFAULT_KIT_TEMPLATE_PATH.name)

    def test_load_app_config_template_default_name_fallback(self) -> None:
        toml = """
[templates]
default_name = "forge"

[signing_key_shard_template]
name = "monograph"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.template_path.parent.name, "forge")
        self.assertEqual(config.recovery_template_path.parent.name, "forge")
        self.assertEqual(config.shard_template_path.parent.name, "forge")
        self.assertEqual(config.kit_template_path.parent.name, "forge")
        self.assertEqual(config.signing_key_shard_template_path.parent.name, "monograph")

    def test_load_app_config_rejects_legacy_template_path_key(self) -> None:
        toml = """
[template]
path = "templates/ledger/main_document.html.j2"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "template.path is unsupported"):
                load_app_config(path=path)

    def test_load_app_config_rejects_blank_template_name(self) -> None:
        toml = """
[template]
name = "   "
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "template.name must be a non-empty string"):
                load_app_config(path=path)

    def test_load_app_config_rejects_unknown_template_name(self) -> None:
        toml = """
[template]
name = "does-not-exist"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown template design"):
                load_app_config(path=path)

    def test_load_app_config_rejects_invalid_default_name(self) -> None:
        toml = """
[templates]
default_name = 123
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "templates.default_name must be a non-empty string"
            ):
                load_app_config(path=path)

    def test_apply_template_design_overrides_name_resolved_templates(self) -> None:
        toml = """
[templates]
default_name = "sentinel"

[signing_key_shard_template]
name = "monograph"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        overridden = apply_template_design(config, "forge")
        self.assertEqual(overridden.template_path.parent.name, "forge")
        self.assertEqual(overridden.recovery_template_path.parent.name, "forge")
        self.assertEqual(overridden.shard_template_path.parent.name, "forge")
        self.assertEqual(overridden.signing_key_shard_template_path.parent.name, "forge")
        self.assertEqual(overridden.kit_template_path.parent.name, "forge")

    def test_load_app_config_color_tuples(self) -> None:
        """Test loading config with RGB color tuples."""
        toml = """
[qr]
dark = [0, 0, 0]
light = [255, 255, 255]
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.qr_config.dark, (0, 0, 0))
        self.assertEqual(config.qr_config.light, (255, 255, 255))

    def test_load_app_config_rgba_colors(self) -> None:
        """Test loading config with RGBA color tuples."""
        toml = """
[qr]
dark = [0, 0, 0, 255]
light = [255, 255, 255, 128]
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.qr_config.dark, (0, 0, 0, 255))
        self.assertEqual(config.qr_config.light, (255, 255, 255, 128))

    def test_load_app_config_parses_cli_defaults_sections(self) -> None:
        toml = """
[defaults.backup]
base_dir = "/tmp/base"
output_dir = "/tmp/out"
shard_threshold = 2
shard_count = 3
signing_key_mode = "sharded"
signing_key_shard_threshold = 2
signing_key_shard_count = 3

[defaults.recover]
output = "/tmp/recovered"

[ui]
quiet = true
no_color = true
no_animations = true

[debug]
max_bytes = 4096

[runtime]
render_jobs = 6
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.cli_defaults.backup.base_dir, "/tmp/base")
        self.assertEqual(config.cli_defaults.backup.output_dir, "/tmp/out")
        self.assertEqual(config.cli_defaults.backup.shard_threshold, 2)
        self.assertEqual(config.cli_defaults.backup.shard_count, 3)
        self.assertEqual(config.cli_defaults.backup.signing_key_mode, "sharded")
        self.assertEqual(config.cli_defaults.backup.signing_key_shard_threshold, 2)
        self.assertEqual(config.cli_defaults.backup.signing_key_shard_count, 3)
        self.assertEqual(config.cli_defaults.recover.output, "/tmp/recovered")
        self.assertTrue(config.cli_defaults.ui.quiet)
        self.assertTrue(config.cli_defaults.ui.no_color)
        self.assertTrue(config.cli_defaults.ui.no_animations)
        self.assertEqual(config.cli_defaults.debug.max_bytes, 4096)
        self.assertEqual(config.cli_defaults.runtime.render_jobs, 6)

    def test_load_cli_defaults_parses_unset_sentinels(self) -> None:
        toml = """
[defaults.backup]
base_dir = ""
output_dir = ""
shard_threshold = 0
shard_count = 0
signing_key_mode = ""
signing_key_shard_threshold = 0
signing_key_shard_count = 0

[defaults.recover]
output = ""

[debug]
max_bytes = 0

[runtime]
render_jobs = "auto"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            defaults = load_cli_defaults(path=path)

        self.assertIsNone(defaults.backup.base_dir)
        self.assertIsNone(defaults.backup.output_dir)
        self.assertIsNone(defaults.backup.shard_threshold)
        self.assertIsNone(defaults.backup.shard_count)
        self.assertIsNone(defaults.backup.signing_key_mode)
        self.assertIsNone(defaults.backup.signing_key_shard_threshold)
        self.assertIsNone(defaults.backup.signing_key_shard_count)
        self.assertIsNone(defaults.recover.output)
        self.assertIsNone(defaults.debug.max_bytes)
        self.assertEqual(defaults.runtime.render_jobs, "auto")

    def test_load_cli_defaults_rejects_invalid_signing_key_mode(self) -> None:
        toml = """
[defaults.backup]
signing_key_mode = "invalid"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "defaults.backup.signing_key_mode must be 'embedded', 'sharded', or empty",
            ):
                load_cli_defaults(path=path)

    def test_load_cli_defaults_rejects_invalid_render_jobs(self) -> None:
        toml = """
[runtime]
render_jobs = "many"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "runtime.render_jobs must be an integer",
            ):
                load_cli_defaults(path=path)

    def test_load_cli_defaults_rejects_invalid_ui_bool(self) -> None:
        toml = """
[ui]
no_color = "maybe"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ui.no_color must be a boolean"):
                load_cli_defaults(path=path)


if __name__ == "__main__":
    unittest.main()
