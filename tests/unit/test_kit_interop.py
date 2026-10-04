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
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.signing import derive_public_key, sign_auth
from ethernity.extensions.build import _build_extension_document
from ethernity.extensions.chain import extract_root_files
from ethernity.formats.document_codec import (
    build_manifest_and_payload,
    encode_backup_document,
    encode_extension_document,
)
from ethernity.formats.extension_chunking import default_extension_chunker
from ethernity.formats.extension_document import ExtensionChunkingProfile
from ethernity.formats.manifest import BackupFile
from tests.test_support import cli_subprocess_timeout_seconds

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / "kit" / "scripts" / "run_extract_backup.mjs"
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
    def test_python_backup_extracts_in_kit_direct_mode(self) -> None:
        input_files = (
            BackupFile(path="plain.txt", data=b"hello", mtime=1700000000),
            BackupFile(path="notes.bin", data=b"\x01\x02\x03", mtime=None),
        )
        manifest, payload = build_manifest_and_payload(
            input_files,
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
        backup_document = encode_backup_document(payload, manifest)
        extracted = self._extract_files_with_kit(backup_document)
        self.assertEqual(
            extracted,
            {
                "notes.bin": b"\x01\x02\x03",
                "plain.txt": b"hello",
            },
        )

    @unittest.skipIf(shutil.which("node") is None, "node runtime is required")
    def test_python_backup_extracts_in_kit_prefix_table_mode(self) -> None:
        input_files = tuple(
            BackupFile(
                path=f"vault/customer_{idx:02d}/record_{idx:02d}.txt",
                data=f"entry-{idx}".encode("utf-8"),
                mtime=1700000000 + idx,
            )
            for idx in range(10)
        )
        manifest, payload = build_manifest_and_payload(
            input_files,
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
        backup_document = encode_backup_document(payload, manifest)
        extracted = self._extract_files_with_kit(backup_document)
        expected = {part.path: part.data for part in input_files}
        self.assertEqual(extracted, expected)

    @unittest.skipIf(shutil.which("node") is None, "node runtime is required")
    def test_python_extension_chain_recovers_in_kit(self) -> None:
        passphrase = "kit interop passphrase"
        signing_seed = b"\x42" * 32
        sign_pub = derive_public_key(signing_seed)
        root_input_files = (BackupFile(path="plain.txt", data=b"root value", mtime=1_700_000_000),)
        root_manifest, root_payload = build_manifest_and_payload(
            root_input_files,
            sealed=False,
            signing_seed=signing_seed,
            input_origin="directory",
            input_roots=("vault",),
        )
        root_plaintext = encode_backup_document(root_payload, root_manifest)
        root_ciphertext, _ = encrypt_bytes_with_passphrase(
            root_plaintext,
            passphrase=passphrase,
        )
        _root_doc_id, root_doc_hash = doc_id_and_hash_from_ciphertext(root_ciphertext)

        restored_root_files = extract_root_files(root_manifest, root_payload)
        chunking = ExtensionChunkingProfile(
            algorithm_id=1,
            target_size=16 * 1024,
            min_size=4 * 1024,
            max_size=64 * 1024,
        )
        existing_chunks: dict[bytes, bytes] = {}
        for item in restored_root_files:
            for start, end in default_extension_chunker(item.data, chunking):
                chunk = item.data[start:end]
                existing_chunks.setdefault(hashlib.sha256(chunk).digest(), chunk)
        extension = _build_extension_document(
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
            existing_file_sizes={item.path: item.size for item in restored_root_files},
            existing_chunks=existing_chunks,
            existing_file_bytes=sum(item.size for item in restored_root_files),
        ).document
        extension_plaintext = encode_extension_document(extension)
        extension_ciphertext, _ = encrypt_bytes_with_passphrase(
            extension_plaintext,
            passphrase=passphrase,
        )
        _extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )

        fixture = {
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

        fixture["freshness_unknown_acknowledged"] = True
        result = self._recover_documents_with_kit(fixture)
        self._assert_recover_documents_result(
            result,
            {
                "selected_extension_index": 1,
                "selected_extension_doc_hash": extension_doc_hash.hex(),
                "freshness_scope": "supplied_carriers_only",
                "freshness_decision": "supplied_pages_freshness_unknown",
                "replay_target": "latest",
                "input_roots": ["reconstructed-state"],
                "files": {
                    "extra.txt": b"added value",
                    "plain.txt": b"updated value",
                },
            },
        )

    def _assert_recover_documents_result(
        self,
        result: dict[str, object],
        expected: dict[str, object],
    ) -> None:
        self.assertEqual(
            result["selected_extension_index"],
            expected["selected_extension_index"],
        )
        self.assertEqual(
            result["selected_extension_doc_hash"],
            expected["selected_extension_doc_hash"],
        )
        self.assertEqual(result["freshness_scope"], expected["freshness_scope"])
        self.assertEqual(result["freshness_decision"], expected["freshness_decision"])
        self.assertEqual(result["replay_target"], expected["replay_target"])
        self.assertEqual(result["manifest"]["input_origin"], "directory")
        self.assertEqual(result["manifest"]["input_roots"], expected["input_roots"])
        recovered = {
            file_entry["path"]: base64.b64decode(file_entry["data_base64"])
            for file_entry in result["files"]
        }
        self.assertEqual(recovered, expected["files"])

    def _extract_files_with_kit(self, backup_bytes: bytes) -> dict[str, bytes]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            backup_path = Path(tmp_dir) / "backup_document.bin"
            backup_path.write_bytes(backup_bytes)
            result = subprocess.run(
                ["node", str(_SCRIPT_PATH), str(backup_path)],
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

    def _recover_documents_with_kit_raw(
        self, fixture: dict[str, object]
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture_path = Path(tmp_dir) / "documents.json"
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            return subprocess.run(
                ["node", str(_RECOVER_SCRIPT_PATH), str(fixture_path)],
                cwd=_PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=cli_subprocess_timeout_seconds(),
            )

    def _recover_documents_with_kit(self, fixture: dict[str, object]) -> dict[str, object]:
        result = self._recover_documents_with_kit_raw(fixture)
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
