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
    DEFAULT_RENDER_STYLE,
    apply_render_style,
    load_app_config,
    load_cli_defaults,
)
from ethernity.encoding.chunking import DEFAULT_CHUNK_SIZE


class TestConfig(unittest.TestCase):
    @staticmethod
    def _with_required_qr_payload_codec(toml: str) -> str:
        marker = "[defaults.backup]"
        if marker in toml:
            backup_section = toml.split(marker, 1)[1].split("\n[", 1)[0]
            if "qr_payload_codec" in backup_section:
                return toml
            return toml.replace(marker, f'{marker}\nqr_payload_codec = "raw"', 1)
        return toml.rstrip() + '\n\n[defaults.backup]\nqr_payload_codec = "raw"\n'

    def test_load_app_config_parses_qr_config(self) -> None:
        toml = """
[page]
size = "A4"

[qr]
scale = 6
border = 2
version = 3
mask = 2
micro = true
boost_error = false
dark = [1, 2, 3]
light = [4, 5, 6, 7]
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.design_name, DEFAULT_RENDER_STYLE)
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
        self.assertEqual(config.extension_chunking.target_size, 16 * 1024)
        self.assertEqual(config.extension_chunking.min_size, 4 * 1024)
        self.assertEqual(config.extension_chunking.max_size, 64 * 1024)

    def test_load_app_config_with_defaults(self) -> None:
        """Test loading config with minimal content uses defaults."""
        toml = """
[page]
size = "A4"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.paper_size, "A4")
        self.assertEqual(config.design_name, DEFAULT_RENDER_STYLE)
        self.assertEqual(config.qr_chunk_size, DEFAULT_CHUNK_SIZE)

    def test_load_app_config_empty_file(self) -> None:
        """Test loading empty config file fails when required backup defaults are missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "defaults.backup.qr_payload_codec is required and must be 'raw' or 'base64'",
            ):
                load_app_config(path=path)

    def test_load_app_config_missing_sections(self) -> None:
        """Test loading config with missing optional sections."""
        toml = """
[page]
size = "Letter"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.paper_size, "LETTER")
        # QR config should have defaults
        self.assertIsNotNone(config.qr_config)

    def test_load_app_config_various_paper_sizes(self) -> None:
        """Test loading config with supported paper sizes."""
        cases = (("A4", "A4"), ("Letter", "LETTER"), ("LETTER", "LETTER"))
        for paper_size, expected in cases:
            toml = f"""
[page]
size = "{paper_size}"
"""
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "config.toml"
                path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
                config = load_app_config(path=path)
            self.assertEqual(config.paper_size, expected)

    def test_load_app_config_rejects_unsupported_paper_sizes(self) -> None:
        for paper_size in ["Legal", "A3", "A5"]:
            toml = f"""
[page]
size = "{paper_size}"
"""
            with self.subTest(paper_size=paper_size), tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "config.toml"
                path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "page.size must be one of: A4, LETTER"):
                    load_app_config(path=path)

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
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
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
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_app_config(path=path)

    def test_load_app_config_rejects_coerced_qr_scalars(self) -> None:
        cases = (
            ("scale", '"6"', "qr.scale must be an integer"),
            ("border", "2.0", "qr.border must be an integer"),
            ("version", '"3"', "qr.version must be an integer"),
            ("chunk_size", '"512"', "qr.chunk_size must be an integer"),
        )
        for field, value, expected_error in cases:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "config.toml"
                path.write_text(
                    self._with_required_qr_payload_codec(
                        f"""
[qr]
{field} = {value}
"""
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, expected_error):
                    load_app_config(path=path)

    def test_load_app_config_parses_extension_chunking(self) -> None:
        toml = """
[extension.chunking]
target_size = 16384
min_size = 4096
max_size = 65536
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.extension_chunking.target_size, 16384)
        self.assertEqual(config.extension_chunking.min_size, 4096)
        self.assertEqual(config.extension_chunking.max_size, 65536)

    def test_load_app_config_rejects_invalid_extension_chunking_order(self) -> None:
        toml = """
[extension.chunking]
target_size = 4096
min_size = 16384
max_size = 65536
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "min_size <= target_size <= max_size"):
                load_app_config(path=path)

    def test_load_app_config_rejects_extension_chunking_below_profile_minimum(self) -> None:
        toml = """
[extension.chunking]
target_size = 1024
min_size = 1024
max_size = 4096
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "extension.chunking.target_size must be >= 4096"
            ):
                load_app_config(path=path)

    def test_load_app_config_rejects_non_integer_extension_chunking_values(self) -> None:
        cases = (
            ("target_size", "true"),
            ("target_size", "16384.0"),
            ("target_size", '"16384"'),
            ("min_size", "true"),
            ("min_size", "4096.0"),
            ("min_size", '"4096"'),
            ("max_size", "true"),
            ("max_size", "65536.0"),
            ("max_size", '"65536"'),
            ("target_size", "0"),
            ("min_size", "-1"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "config.toml"
                chunking_values = {
                    "target_size": "16384",
                    "min_size": "4096",
                    "max_size": "65536",
                }
                chunking_values[field] = value
                path.write_text(
                    self._with_required_qr_payload_codec(
                        f"""
[extension.chunking]
target_size = {chunking_values["target_size"]}
min_size = {chunking_values["min_size"]}
max_size = {chunking_values["max_size"]}
"""
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    ValueError,
                    f"extension.chunking.{field} must be a positive integer",
                ):
                    load_app_config(path=path)

    def test_load_app_config_ignores_payload_encoding_key(self) -> None:
        toml = """
[qr]
payload_encoding = "base64url"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
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
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.qr_config.scale, 20)
        self.assertEqual(config.qr_config.border, 10)
        self.assertEqual(config.qr_config.version, 40)
        self.assertEqual(config.qr_config.mask, 7)

    def test_load_app_config_ignores_removed_template_sections(self) -> None:
        toml = """
[template]
name = "sentinel"

[recovery_template]
name = "sentinel"

[shard_template]
name = "sentinel"

[signing_key_shard_template]
name = "maritime"

[kit_template]
name = "sentinel"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.design_name, DEFAULT_RENDER_STYLE)

    def test_load_app_config_reads_single_render_style(self) -> None:
        toml = """
[render]
style = "forge"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.design_name, "forge")

    def test_load_app_config_ignores_removed_legacy_render_key(self) -> None:
        toml = """
[template]
path = "templates/ledger/legacy-template.html"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            config = load_app_config(path=path)
        self.assertEqual(config.design_name, DEFAULT_RENDER_STYLE)

    def test_load_app_config_rejects_blank_render_style(self) -> None:
        toml = """
[render]
style = "   "
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "render.style must be a non-empty string"):
                load_app_config(path=path)

    def test_load_app_config_rejects_unknown_render_style(self) -> None:
        toml = """
[render]
style = "does-not-exist"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown render style"):
                load_app_config(path=path)

    def test_load_app_config_rejects_invalid_render_style(self) -> None:
        toml = """
[render]
style = 123
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "render.style must be a non-empty string"):
                load_app_config(path=path)

    def test_apply_render_style_overrides_render_style(self) -> None:
        toml = """
[render]
style = "sentinel"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            config = load_app_config(path=path)

        overridden = apply_render_style(config, "forge")
        self.assertEqual(overridden.design_name, "forge")

    def test_load_app_config_color_tuples(self) -> None:
        """Test loading config with RGB color tuples."""
        toml = """
[qr]
dark = [0, 0, 0]
light = [255, 255, 255]
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
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
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.qr_config.dark, (0, 0, 0, 255))
        self.assertEqual(config.qr_config.light, (255, 255, 255, 128))

    def test_load_app_config_rejects_invalid_qr_bool_values(self) -> None:
        for field, value in (("micro", '"maybe"'), ("micro", "2"), ("boost_error", '"maybe"')):
            with self.subTest(field=field, value=value):
                toml = f"""
[qr]
{field} = {value}
"""
                with tempfile.TemporaryDirectory() as tmpdir:
                    path = Path(tmpdir) / "config.toml"
                    path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, rf"qr\.{field} must be a boolean"):
                        load_app_config(path=path)

    def test_load_app_config_rejects_malformed_qr_section_type(self) -> None:
        toml = """
qr = 7
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "qr must be a table"):
                load_app_config(path=path)

    def test_load_app_config_rejects_malformed_qr_color_tuple(self) -> None:
        toml = """
[qr]
dark = [1, 2]
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "qr.dark must be a color string or RGB/RGBA tuple",
            ):
                load_app_config(path=path)

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
payload_codec = "raw"
qr_payload_codec = "base64"

[defaults.recover]
output = "/tmp/recovered"

[defaults.extend]
base_dir = "/tmp/extend-base"
unlock_policy = "self-contained"
shard_threshold = 3
shard_count = 5
signing_key_mode = "sharded"
signing_key_shard_threshold = 2
signing_key_shard_count = 4
qr_payload_codec = "base64"

[ui]
quiet = true
no_color = true
no_animations = true
show_internals = true

[debug]
max_bytes = 4096

[runtime]
render_jobs = 6
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.cli_defaults.backup.base_dir, "/tmp/base")
        self.assertEqual(config.cli_defaults.backup.output_dir, "/tmp/out")
        self.assertEqual(config.cli_defaults.backup.shard_threshold, 2)
        self.assertEqual(config.cli_defaults.backup.shard_count, 3)
        self.assertEqual(config.cli_defaults.backup.signing_key_mode, "sharded")
        self.assertEqual(config.cli_defaults.backup.signing_key_shard_threshold, 2)
        self.assertEqual(config.cli_defaults.backup.signing_key_shard_count, 3)
        self.assertEqual(config.cli_defaults.backup.payload_codec, "raw")
        self.assertEqual(config.cli_defaults.backup.qr_payload_codec, "base64")
        self.assertEqual(config.cli_defaults.recover.output, "/tmp/recovered")
        self.assertEqual(config.cli_defaults.extend.base_dir, "/tmp/extend-base")
        self.assertEqual(config.cli_defaults.extend.unlock_policy, "self-contained")
        self.assertEqual(config.cli_defaults.extend.shard_threshold, 3)
        self.assertEqual(config.cli_defaults.extend.shard_count, 5)
        self.assertEqual(config.cli_defaults.extend.signing_key_mode, "sharded")
        self.assertEqual(config.cli_defaults.extend.signing_key_shard_threshold, 2)
        self.assertEqual(config.cli_defaults.extend.signing_key_shard_count, 4)
        self.assertEqual(config.cli_defaults.extend.qr_payload_codec, "base64")
        self.assertTrue(config.cli_defaults.ui.quiet)
        self.assertTrue(config.cli_defaults.ui.no_color)
        self.assertTrue(config.cli_defaults.ui.no_animations)
        self.assertTrue(config.cli_defaults.ui.show_internals)
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
qr_payload_codec = "raw"

[defaults.recover]
output = ""

[defaults.extend]
base_dir = ""
unlock_policy = ""
shard_threshold = 0
shard_count = 0
signing_key_mode = ""
signing_key_shard_threshold = 0
signing_key_shard_count = 0
qr_payload_codec = "raw"

[debug]
max_bytes = 0

[runtime]
render_jobs = "auto"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            defaults = load_cli_defaults(path=path)

        self.assertIsNone(defaults.backup.base_dir)
        self.assertIsNone(defaults.backup.output_dir)
        self.assertIsNone(defaults.backup.shard_threshold)
        self.assertIsNone(defaults.backup.shard_count)
        self.assertIsNone(defaults.backup.signing_key_mode)
        self.assertIsNone(defaults.backup.signing_key_shard_threshold)
        self.assertIsNone(defaults.backup.signing_key_shard_count)
        self.assertEqual(defaults.backup.payload_codec, "auto")
        self.assertEqual(defaults.backup.qr_payload_codec, "raw")
        self.assertIsNone(defaults.recover.output)
        self.assertIsNone(defaults.extend.base_dir)
        self.assertIsNone(defaults.extend.unlock_policy)
        self.assertIsNone(defaults.extend.shard_threshold)
        self.assertIsNone(defaults.extend.shard_count)
        self.assertIsNone(defaults.extend.signing_key_mode)
        self.assertIsNone(defaults.extend.signing_key_shard_threshold)
        self.assertIsNone(defaults.extend.signing_key_shard_count)
        self.assertEqual(defaults.extend.qr_payload_codec, "raw")
        self.assertIsNone(defaults.debug.max_bytes)
        self.assertEqual(defaults.runtime.render_jobs, "auto")

    def test_load_cli_defaults_rejects_missing_qr_payload_codec(self) -> None:
        toml = """
[defaults.backup]
payload_codec = "auto"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "defaults.backup.qr_payload_codec is required and must be 'raw' or 'base64'",
            ):
                load_cli_defaults(path=path)

    def test_load_cli_defaults_rejects_empty_qr_payload_codec(self) -> None:
        toml = """
[defaults.backup]
qr_payload_codec = ""
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "defaults.backup.qr_payload_codec must be 'raw' or 'base64'",
            ):
                load_cli_defaults(path=path)

    def test_load_cli_defaults_rejects_invalid_qr_payload_codec(self) -> None:
        toml = """
[defaults.backup]
qr_payload_codec = "hex"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "defaults.backup.qr_payload_codec must be 'raw' or 'base64'",
            ):
                load_cli_defaults(path=path)

    def test_load_cli_defaults_accepts_base64_qr_payload_codec(self) -> None:
        toml = """
[defaults.backup]
qr_payload_codec = "base64"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            defaults = load_cli_defaults(path=path)
        self.assertEqual(defaults.backup.qr_payload_codec, "base64")

    def test_load_cli_defaults_rejects_invalid_payload_codec(self) -> None:
        toml = """
[defaults.backup]
payload_codec = "brotli"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "defaults.backup.payload_codec must be 'auto', 'raw', or 'gzip'",
            ):
                load_cli_defaults(path=path)

    def test_load_cli_defaults_rejects_empty_payload_codec(self) -> None:
        toml = """
[defaults.backup]
payload_codec = ""
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "defaults.backup.payload_codec must be 'auto', 'raw', or 'gzip'",
            ):
                load_cli_defaults(path=path)

    def test_load_cli_defaults_rejects_invalid_signing_key_mode(self) -> None:
        toml = """
[defaults.backup]
signing_key_mode = "invalid"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
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
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
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
            path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ui.no_color must be a boolean"):
                load_cli_defaults(path=path)

    def test_load_cli_defaults_rejects_malformed_section_types(self) -> None:
        cases = (("runtime = 3", "runtime must be a table"),)
        for toml, expected_error in cases:
            with self.subTest(toml=toml):
                with tempfile.TemporaryDirectory() as tmpdir:
                    path = Path(tmpdir) / "config.toml"
                    path.write_text(self._with_required_qr_payload_codec(toml), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, expected_error):
                        load_cli_defaults(path=path)

    def test_load_cli_defaults_rejects_malformed_defaults_section_type(self) -> None:
        toml = "defaults = 3"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "defaults must be a table"):
                load_cli_defaults(path=path)


if __name__ == "__main__":
    unittest.main()
