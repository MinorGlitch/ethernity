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

import base64
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ethernity.formats.envelope_codec import build_manifest_and_payload, encode_envelope
from ethernity.formats.envelope_types import PayloadPart

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / "kit" / "scripts" / "run_extract_envelope.mjs"
_KIT_HASHES_PACKAGE = _PROJECT_ROOT / "kit" / "node_modules" / "@noble" / "hashes" / "package.json"


class TestKitInterop(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not _KIT_HASHES_PACKAGE.exists():
            raise RuntimeError(
                "kit node dependencies are missing; run 'cd kit && npm ci' before "
                "running tests/unit/test_kit_interop.py"
            )

    @unittest.skipIf(shutil.which("node") is None, "node runtime is required")
    def test_python_envelope_extracts_in_kit_direct_mode(self) -> None:
        parts = (
            PayloadPart(path="plain.txt", data=b"hello", mtime=1700000000),
            PayloadPart(path="notes.bin", data=b"\x01\x02\x03", mtime=None),
        )
        manifest, payload = build_manifest_and_payload(
            parts,
            sealed=True,
            input_origin="file",
            input_roots=(),
        )
        manifest_map = manifest.to_cbor()
        self.assertEqual(
            manifest_map["path_encoding"],
            "direct",
            msg="fixture must exercise direct-mode manifests",
        )
        envelope = encode_envelope(payload, manifest)
        extracted = self._extract_with_kit(envelope)
        self.assertEqual(
            extracted,
            {
                "notes.bin": b"\x01\x02\x03",
                "plain.txt": b"hello",
            },
        )

    @unittest.skipIf(shutil.which("node") is None, "node runtime is required")
    def test_python_envelope_extracts_in_kit_prefix_table_mode(self) -> None:
        parts = tuple(
            PayloadPart(
                path=f"vault/customer_{idx:02d}/record_{idx:02d}.txt",
                data=f"entry-{idx}".encode("utf-8"),
                mtime=1700000000 + idx,
            )
            for idx in range(10)
        )
        manifest, payload = build_manifest_and_payload(
            parts,
            sealed=True,
            input_origin="directory",
            input_roots=("vault",),
        )
        manifest_map = manifest.to_cbor()
        self.assertEqual(
            manifest_map["path_encoding"],
            "prefix_table",
            msg="fixture must exercise prefix-table manifests",
        )
        envelope = encode_envelope(payload, manifest)
        extracted = self._extract_with_kit(envelope)
        expected = {part.path: part.data for part in parts}
        self.assertEqual(extracted, expected)

    def _extract_with_kit(self, envelope_bytes: bytes) -> dict[str, bytes]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            envelope_path = Path(tmp_dir) / "envelope.bin"
            envelope_path.write_bytes(envelope_bytes)
            result = subprocess.run(
                ["node", str(_SCRIPT_PATH), str(envelope_path)],
                cwd=_PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=result.stderr.strip() or result.stdout.strip(),
            )
            payload = json.loads(result.stdout)
            extracted: dict[str, bytes] = {}
            for file_entry in payload.get("files", []):
                extracted[file_entry["path"]] = base64.b64decode(file_entry["data_base64"])
            return extracted


if __name__ == "__main__":
    unittest.main()
