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
from types import SimpleNamespace

from ethernity.cli.shared.crypto import doc_id_and_hash_from_ciphertext
from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.crypto.signing import derive_public_key, sign_auth
from ethernity.extensions.build import build_extension_document
from ethernity.extensions.chain import build_chain_available_chunks, extract_root_logical_state
from ethernity.formats.envelope_codec import (
    build_manifest_and_payload,
    encode_envelope,
    encode_extension_envelope,
)
from ethernity.formats.envelope_types import PayloadPart
from ethernity.formats.extension_chunking import default_extension_chunker
from ethernity.formats.extension_envelope import ExtensionChunkingProfile
from tests.test_support import cli_subprocess_timeout_seconds

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / "kit" / "scripts" / "run_extract_envelope.mjs"
_RECOVER_SCRIPT_PATH = _PROJECT_ROOT / "kit" / "scripts" / "run_recover_documents.mjs"
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

    @unittest.skipIf(shutil.which("node") is None, "node runtime is required")
    def test_python_extension_chain_recovers_in_kit(self) -> None:
        passphrase = "kit interop passphrase"
        signing_seed = b"\x42" * 32
        sign_pub = derive_public_key(signing_seed)
        root_parts = (PayloadPart(path="plain.txt", data=b"root value", mtime=1_700_000_000),)
        root_manifest, root_payload = build_manifest_and_payload(
            root_parts,
            sealed=False,
            signing_seed=signing_seed,
            input_origin="directory",
            input_roots=("vault",),
        )
        root_plaintext = encode_envelope(root_payload, root_manifest)
        root_ciphertext, _ = encrypt_bytes_with_passphrase(
            root_plaintext,
            passphrase=passphrase,
        )
        _root_doc_id, root_doc_hash = doc_id_and_hash_from_ciphertext(root_ciphertext)

        root_state = extract_root_logical_state(root_manifest, root_payload)
        chunking = ExtensionChunkingProfile(
            algorithm_id=1,
            target_size=16 * 1024,
            min_size=4 * 1024,
            max_size=64 * 1024,
        )
        extension = build_extension_document(
            index=1,
            parent_doc_hash=root_doc_hash,
            root_doc_hash=root_doc_hash,
            chunking=chunking,
            input_files=(
                SimpleNamespace(relative_path="plain.txt", data=b"updated value", mtime=1),
                SimpleNamespace(relative_path="extra.txt", data=b"added value", mtime=2),
            ),
            input_origin="directory",
            input_roots=("vault",),
            chunker=default_extension_chunker,
            existing_file_sizes={item.path: item.size for item in root_state},
            existing_chunks=build_chain_available_chunks(root_state, chunking),
            existing_logical_bytes=sum(item.size for item in root_state),
        ).document
        extension_plaintext = encode_extension_envelope(extension)
        extension_ciphertext, _ = encrypt_bytes_with_passphrase(
            extension_plaintext,
            passphrase=passphrase,
        )
        _extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )

        result = self._recover_documents_with_kit(
            {
                "passphrase": passphrase,
                "documents": [
                    self._document_json(root_ciphertext, root_doc_hash, sign_pub, signing_seed),
                    self._document_json(
                        extension_ciphertext,
                        extension_doc_hash,
                        sign_pub,
                        signing_seed,
                    ),
                ],
            }
        )

        self.assertEqual(result["selected_extension_index"], 1)
        self.assertEqual(result["selected_extension_doc_hash"], extension_doc_hash.hex())
        self.assertEqual(result["freshness_scope"], "supplied_carriers_only")
        self.assertEqual(result["manifest"]["input_origin"], "directory")
        self.assertEqual(result["manifest"]["input_roots"], ["reconstructed-state"])
        recovered = {
            file_entry["path"]: base64.b64decode(file_entry["data_base64"])
            for file_entry in result["files"]
        }
        self.assertEqual(
            recovered,
            {
                "extra.txt": b"added value",
                "plain.txt": b"updated value",
            },
        )

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
                timeout=cli_subprocess_timeout_seconds(),
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

    def _recover_documents_with_kit(self, fixture: dict[str, object]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture_path = Path(tmp_dir) / "documents.json"
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            result = subprocess.run(
                ["node", str(_RECOVER_SCRIPT_PATH), str(fixture_path)],
                cwd=_PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=cli_subprocess_timeout_seconds(),
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=result.stderr.strip() or result.stdout.strip(),
            )
            payload = json.loads(result.stdout)
            self.assertIsInstance(payload, dict)
            return payload

    def _document_json(
        self,
        ciphertext: bytes,
        doc_hash: bytes,
        sign_pub: bytes,
        signing_seed: bytes,
    ) -> dict[str, object]:
        return {
            "ciphertext": self._base64(ciphertext),
            "doc_hash": self._base64(doc_hash),
            "auth": {
                "version": 1,
                "doc_hash": self._base64(doc_hash),
                "sign_pub": self._base64(sign_pub),
                "signature": self._base64(
                    sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=signing_seed)
                ),
            },
        }

    def _base64(self, data: bytes) -> str:
        return base64.b64encode(data).decode("ascii")


if __name__ == "__main__":
    unittest.main()
