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

import hashlib
import unittest
from unittest import mock

import cbor2

from ethernity.cli.core.types import InputFile
from ethernity.cli.ui import debug as debug_module
from ethernity.core.models import DocumentPlan, ShardingConfig
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile


class TestUIDebugHelpers(unittest.TestCase):
    def test_normalize_debug_max_bytes(self) -> None:
        self.assertIsNone(debug_module._normalize_debug_max_bytes(None))
        self.assertIsNone(debug_module._normalize_debug_max_bytes(0))
        self.assertIsNone(debug_module._normalize_debug_max_bytes(-5))
        self.assertEqual(debug_module._normalize_debug_max_bytes(16), 16)

    def test_format_grouped_lines_empty_and_wrapped(self) -> None:
        self.assertEqual(
            debug_module._format_grouped_lines("", group_size=4, line_length=8),
            [],
        )
        wrapped = debug_module._format_grouped_lines("abcdefghijkl", group_size=2, line_length=5)
        self.assertEqual(wrapped, ["ab cd", "ef gh", "ij kl"])

    def test_format_zbase32_lines_with_truncation(self) -> None:
        lines = debug_module._format_zbase32_lines(
            b"0123456789",
            group_size=4,
            line_length=80,
            max_bytes=4,
        )
        self.assertTrue(lines)
        self.assertIn("truncated 6 bytes", lines[-1])

    def test_format_hex_lines(self) -> None:
        lines = debug_module._format_hex_lines(b"\x01\x02\x03\x04", group_size=2, line_length=5)
        self.assertEqual(lines, ["01 02", "03 04"])

    def test_append_signing_key_lines_variants(self) -> None:
        sign_pub = b"\x11" * 32

        sealed_lines: list[str] = []
        debug_module._append_signing_key_lines(
            sealed_lines,
            sign_pub=sign_pub,
            sealed=True,
            stored_in_main=False,
        )
        self.assertIn("Signing private key not stored (sealed backup).", sealed_lines)

        stored_lines: list[str] = []
        debug_module._append_signing_key_lines(
            stored_lines,
            sign_pub=sign_pub,
            sealed=False,
            stored_in_main=True,
            stored_as_shards=True,
        )
        self.assertIn("Signing private key stored in main document.", stored_lines)
        self.assertIn("Signing private key stored in separate shard documents.", stored_lines)

        absent_lines: list[str] = []
        debug_module._append_signing_key_lines(
            absent_lines,
            sign_pub=sign_pub,
            sealed=False,
            stored_in_main=False,
            stored_as_shards=False,
        )
        self.assertIn("Signing private key not stored.", absent_lines)

    def test_hexdump_empty_and_truncated(self) -> None:
        self.assertEqual(debug_module._hexdump(b"", max_bytes=None), "(empty)")
        output = debug_module._hexdump(b"abcdef", max_bytes=3)
        self.assertIn("00000000", output)
        self.assertIn("truncated 3 bytes", output)

    def test_json_safe_nested_values(self) -> None:
        payload = {
            "a": b"\x01\x02",
            "b": [b"\x03", {"c": (b"\x04", "x")}],
        }
        safe = debug_module._json_safe(payload)
        self.assertEqual(safe["a"], "0102")
        self.assertEqual(safe["b"][0], "03")
        self.assertEqual(safe["b"][1]["c"][0], "04")

    def test_decode_manifest_raw_cbor_json_and_invalid(self) -> None:
        decoded_cbor = debug_module._decode_manifest_raw(cbor2.dumps({"a": b"\x01"}))
        self.assertEqual(decoded_cbor, {"a": "01"})

        decoded_json = debug_module._decode_manifest_raw(b'{"v": [1, 2, 3]}')
        self.assertEqual(decoded_json, {"v": [1, 2, 3]})

        self.assertIsNone(debug_module._decode_manifest_raw(b"\x81"))


class TestDebugRenderers(unittest.TestCase):
    def _manifest_direct(self) -> EnvelopeManifest:
        entry = ManifestFile(
            path="doc.txt",
            size=3,
            sha256=hashlib.sha256(b"abc").digest(),
            mtime=123,
        )
        return EnvelopeManifest(
            format_version=1,
            created_at=1.0,
            sealed=False,
            signing_seed=b"\x22" * 32,
            files=(entry,),
            input_origin="file",
            input_roots=(),
        )

    def _manifest_prefix_table(self) -> EnvelopeManifest:
        files = tuple(
            ManifestFile(
                path=f"very/long/common/prefix/segment/for/testing/{index:03d}.txt",
                size=3,
                sha256=hashlib.sha256(f"f{index}".encode("utf-8")).digest(),
                mtime=123 + index,
            )
            for index in range(8)
        )
        return EnvelopeManifest(
            format_version=1,
            created_at=1.0,
            sealed=False,
            signing_seed=b"\x11" * 32,
            files=files,
            input_origin="directory",
            input_roots=("testing",),
        )

    def _input_file(self) -> InputFile:
        return InputFile(source_path=None, relative_path="doc.txt", data=b"abc", mtime=123)

    @mock.patch("ethernity.cli.ui.debug.console.print")
    def test_print_backup_debug_masks_secrets_by_default(
        self,
        console_print: mock.MagicMock,
    ) -> None:
        plan = DocumentPlan(
            version=1,
            sealed=False,
            sharding=ShardingConfig(threshold=2, shares=3),
            signing_seed_sharding=None,
        )
        debug_module.print_backup_debug(
            payload=b"payload-bytes",
            input_files=[self._input_file()],
            base_dir=None,
            manifest=self._manifest_prefix_table(),
            envelope=b"envelope-bytes",
            plan=plan,
            passphrase="secret words",
            signing_seed=b"\x33" * 32,
            signing_pub=b"\x44" * 32,
            signing_seed_stored=True,
            debug_max_bytes=32,
            reveal_secrets=False,
        )
        rendered = "\n".join(
            str(call.args[0]) for call in console_print.call_args_list if call.args
        )
        self.assertIn("[bold]Debug Summary:[/bold]", rendered)
        self.assertIn("- mode: backup", rendered)
        self.assertIn("- signing seed stored in envelope: yes", rendered)
        self.assertIn("- passphrase: <masked chars=", rendered)
        self.assertIn("Signing private key: <masked bytes=", rendered)
        self.assertNotIn("secret words", rendered)
        self.assertNotIn("33333333", rendered)
        self.assertIn("[bold]Manifest CBOR map JSON:[/bold]", rendered)
        self.assertIn('"path_encoding": "prefix_table"', rendered)
        self.assertIn('"path_prefixes"', rendered)
        self.assertIn("[bold]Payload Preview (hex):[/bold]", rendered)
        self.assertIn("[bold]Envelope Preview (hex):[/bold]", rendered)
        literal_calls = [
            call for call in console_print.call_args_list if call.kwargs.get("markup") is False
        ]
        self.assertGreaterEqual(len(literal_calls), 3)
        self.assertTrue(any("00000000" in str(call.args[0]) for call in literal_calls if call.args))

    @mock.patch("ethernity.cli.ui.debug.console.print")
    def test_print_backup_debug_reveals_secrets_when_requested(
        self,
        console_print: mock.MagicMock,
    ) -> None:
        plan = DocumentPlan(version=1, sealed=False, sharding=None, signing_seed_sharding=None)
        debug_module.print_backup_debug(
            payload=b"payload-bytes",
            input_files=[self._input_file()],
            base_dir=None,
            manifest=self._manifest_direct(),
            envelope=b"envelope-bytes",
            plan=plan,
            passphrase="reveal me",
            signing_seed=b"\x33" * 32,
            signing_pub=b"\x44" * 32,
            signing_seed_stored=True,
            debug_max_bytes=32,
            reveal_secrets=True,
        )
        rendered = "\n".join(
            str(call.args[0]) for call in console_print.call_args_list if call.args
        )
        self.assertIn("- passphrase: reveal me", rendered)
        self.assertIn("Signing private key (hex, revealed):", rendered)
        self.assertNotIn("<masked chars=", rendered)
        self.assertIn('"path_encoding": "direct"', rendered)

    @mock.patch("ethernity.cli.ui.debug._decode_manifest_raw", return_value=None)
    @mock.patch("ethernity.cli.ui.debug.console.print")
    def test_print_backup_debug_decode_failure_message(
        self,
        console_print: mock.MagicMock,
        _decode_manifest_raw: mock.MagicMock,
    ) -> None:
        plan = DocumentPlan(version=1, sealed=True, sharding=None, signing_seed_sharding=None)
        debug_module.print_backup_debug(
            payload=b"abc",
            input_files=[self._input_file()],
            base_dir=None,
            manifest=b"not-cbor-or-json",
            envelope=b"xyz",
            plan=plan,
            passphrase=None,
            signing_seed=None,
            signing_pub=b"\x55" * 32,
            signing_seed_stored=False,
            debug_max_bytes=8,
            reveal_secrets=False,
        )
        rendered = "\n".join(
            str(call.args[0]) for call in console_print.call_args_list if call.args
        )
        self.assertIn("(unable to decode manifest CBOR map)", rendered)
        self.assertIn("- signing seed stored in envelope: no", rendered)

    @mock.patch("ethernity.cli.ui.debug.console.print")
    def test_print_recover_debug_masks_passphrase_and_shows_entries(
        self,
        console_print: mock.MagicMock,
    ) -> None:
        manifest = self._manifest_prefix_table()
        extracted = [
            (manifest.files[0], b"abc"),
            (manifest.files[1], b"def"),
        ]
        debug_module.print_recover_debug(
            manifest=manifest,
            extracted=extracted,
            ciphertext=b"\xaa\xbb\xcc",
            passphrase="recover secret",
            auth_status="verified",
            allow_unsigned=False,
            output_path="restored-output",
            debug_max_bytes=16,
            reveal_secrets=False,
        )
        rendered = "\n".join(
            str(call.args[0]) for call in console_print.call_args_list if call.args
        )
        self.assertIn("- mode: recover", rendered)
        self.assertIn("- auth status: verified", rendered)
        self.assertIn("- rescue mode: disabled", rendered)
        self.assertIn("- output target: restored-output", rendered)
        self.assertIn("- passphrase: <masked chars=", rendered)
        self.assertNotIn("recover secret", rendered)
        self.assertIn("[bold]Recovered Entries:[/bold]", rendered)
        self.assertIn("very/long/common/prefix/segment/for/testing/000.txt (3 bytes)", rendered)
        self.assertIn("[bold]Manifest CBOR map JSON:[/bold]", rendered)
        self.assertIn('"path_encoding": "prefix_table"', rendered)

    @mock.patch("ethernity.cli.ui.debug.console.print")
    def test_print_recover_debug_reveals_passphrase_and_handles_no_entries(
        self,
        console_print: mock.MagicMock,
    ) -> None:
        manifest = self._manifest_direct()
        debug_module.print_recover_debug(
            manifest=manifest,
            extracted=[],
            ciphertext=b"\xaa",
            passphrase="open sesame",
            auth_status="unsigned",
            allow_unsigned=True,
            output_path=None,
            debug_max_bytes=8,
            reveal_secrets=True,
        )
        rendered = "\n".join(
            str(call.args[0]) for call in console_print.call_args_list if call.args
        )
        self.assertIn("- output target: stdout", rendered)
        self.assertIn("- rescue mode: enabled", rendered)
        self.assertIn("- passphrase: open sesame", rendered)
        self.assertIn("(no entries)", rendered)


if __name__ == "__main__":
    unittest.main()
