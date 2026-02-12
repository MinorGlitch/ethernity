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
    DEFAULT_PAPER_SIZE,
    DEFAULT_RECOVERY_TEMPLATE_PATH,
    DEFAULT_SHARD_TEMPLATE_PATH,
    DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH,
    DEFAULT_TEMPLATE_PATH,
    load_app_config,
)
from ethernity.encoding.chunking import DEFAULT_CHUNK_SIZE


class TestConfig(unittest.TestCase):
    def test_load_app_config_parses_qr_config(self) -> None:
        toml = """
[template]
path = 123

[recovery_template]
path = 456

[shard_template]
path = 789

[signing_key_shard_template]
path = 1011

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

    def test_load_app_config_template_paths(self) -> None:
        """Test loading config with custom template paths."""
        toml = """
[template]
path = "/custom/template.html"

[recovery_template]
path = "/custom/recovery.html"

[shard_template]
path = "/custom/shard.html"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        def assert_custom_path(actual: Path, expected_suffix: str) -> None:
            self.assertTrue(actual.is_absolute())
            self.assertTrue(actual.as_posix().endswith(expected_suffix))

        assert_custom_path(config.template_path, "/custom/template.html")
        assert_custom_path(config.recovery_template_path, "/custom/recovery.html")
        assert_custom_path(config.shard_template_path, "/custom/shard.html")

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


if __name__ == "__main__":
    unittest.main()
