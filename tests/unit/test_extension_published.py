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

from ethernity.cli.shared import api_codes
from ethernity.crypto import sharding as sharding_module
from ethernity.crypto.signing import derive_public_key, encode_auth_payload, sign_auth
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions.identity import doc_id_and_hash_from_ciphertext
from ethernity.extensions.published import (
    inspect_published_extension_chain,
    inspect_published_extension_inventory,
)
from ethernity.extensions.recovery import ImportedRecoveryDocument, RecoveryExtensionInventory
from ethernity.formats.envelope_codec import build_manifest_and_payload
from ethernity.formats.envelope_types import PayloadPart


def _auth_frame(
    doc_id: bytes,
    doc_hash: bytes,
    *,
    signing_seed: bytes,
) -> Frame:
    sign_pub = derive_public_key(signing_seed)
    return Frame(
        version=1,
        frame_type=FrameType.AUTH,
        doc_id=doc_id,
        index=0,
        total=1,
        data=encode_auth_payload(
            doc_hash,
            sign_pub=sign_pub,
            signature=sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=signing_seed),
        ),
    )


def _imported_document(
    *,
    doc_id: bytes,
    doc_hash: bytes,
    signing_seed: bytes,
) -> ImportedRecoveryDocument:
    ciphertext = b"ciphertext"
    return ImportedRecoveryDocument(
        doc_id=doc_id,
        doc_hash=doc_hash,
        ciphertext=ciphertext,
        auth_frames=(_auth_frame(doc_id, doc_hash, signing_seed=signing_seed),),
        source_label="qr",
    )


class TestPublishedExtensionInventory(unittest.TestCase):
    def test_inventory_validates_published_shard_carrier_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            extension_dir = root_dir / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            doc_id, doc_hash = doc_id_and_hash_from_ciphertext(b"ciphertext")
            doc_id_hex = doc_id.hex()
            signing_seed = b"\x33" * 32
            sign_pub = derive_public_key(signing_seed)
            (extension_dir / f"qr_document-01-{doc_id_hex}.pdf").write_bytes(b"qr")
            (extension_dir / f"recovery_document-01-{doc_id_hex}.pdf").write_bytes(b"recovery")
            payloads = sharding_module.split_passphrase(
                "secret",
                threshold=2,
                shares=2,
                doc_hash=doc_hash,
                sign_priv=signing_seed,
                sign_pub=sign_pub,
            )
            frames_by_index: dict[int, Frame] = {}
            for payload in payloads:
                (
                    extension_dir / (f"shard-01-{doc_id_hex}-{payload.share_index}-of-2.pdf")
                ).write_bytes(b"shard")
                frames_by_index[payload.share_index] = Frame(
                    version=1,
                    frame_type=FrameType.KEY_DOCUMENT,
                    doc_id=doc_id,
                    index=0,
                    total=1,
                    data=sharding_module.encode_shard_payload(payload),
                )

            inventory = inspect_published_extension_inventory(
                root_dir,
                read_carrier_document=lambda _carrier: _imported_document(
                    doc_id=doc_id,
                    doc_hash=doc_hash,
                    signing_seed=signing_seed,
                ),
                read_shard_frames=lambda carrier: [frames_by_index[carrier.share_index]],
                validate_recovery_document_carrier=lambda _carrier, _document, _sign_pub: None,
            )
            corrupted = inspect_published_extension_inventory(
                root_dir,
                read_carrier_document=lambda _carrier: _imported_document(
                    doc_id=doc_id,
                    doc_hash=doc_hash,
                    signing_seed=signing_seed,
                ),
                read_shard_frames=lambda _carrier: [],
                validate_recovery_document_carrier=lambda _carrier, _document, _sign_pub: None,
            )

        self.assertIsNone(inventory.failure)
        self.assertIsNotNone(corrupted.failure)
        assert corrupted.failure is not None
        self.assertIn("must contain exactly one shard payload", corrupted.failure.message)

    def test_inventory_identity_comes_from_carrier_content_not_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            extension_dir = root_dir / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            stale_doc_id_hex = "deadbeefcafebabe"
            content_doc_id, content_doc_hash = doc_id_and_hash_from_ciphertext(b"ciphertext")
            (extension_dir / f"qr_document-01-{stale_doc_id_hex}.pdf").write_bytes(b"qr")
            (extension_dir / f"recovery_document-01-{stale_doc_id_hex}.pdf").write_bytes(
                b"recovery"
            )

            signing_seed = b"\x33" * 32

            inventory = inspect_published_extension_inventory(
                root_dir,
                read_carrier_document=lambda _carrier: _imported_document(
                    doc_id=content_doc_id,
                    doc_hash=content_doc_hash,
                    signing_seed=signing_seed,
                ),
                read_shard_frames=lambda _carrier: [],
                validate_recovery_document_carrier=lambda _carrier, _document, _sign_pub: None,
            )

        self.assertIsNone(inventory.failure)
        self.assertEqual(len(inventory.extensions), 1)
        self.assertEqual(inventory.extensions[0].doc_id, content_doc_id)
        self.assertEqual(inventory.latest_head_doc_hash, content_doc_hash.hex())

    def test_inventory_validates_recovery_document_against_qr_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            extension_dir = root_dir / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            doc_id, doc_hash = doc_id_and_hash_from_ciphertext(b"ciphertext")
            signing_seed = b"\x33" * 32
            (extension_dir / "qr_document-01-cafebabedeadbeef.pdf").write_bytes(b"qr")
            recovery_path = extension_dir / "recovery_document-01-cafebabedeadbeef.pdf"
            recovery_path.write_bytes(b"recovery")
            calls: list[tuple[str, bytes, bytes, bytes]] = []

            def _validate(carrier, document, sign_pub):
                calls.append(
                    (
                        carrier.filename,
                        document.doc_id,
                        document.doc_hash,
                        sign_pub,
                    )
                )

            inventory = inspect_published_extension_inventory(
                root_dir,
                read_carrier_document=lambda _carrier: _imported_document(
                    doc_id=doc_id,
                    doc_hash=doc_hash,
                    signing_seed=signing_seed,
                ),
                read_shard_frames=lambda _carrier: [],
                validate_recovery_document_carrier=_validate,
            )

        self.assertIsNone(inventory.failure)
        self.assertEqual(
            calls,
            [
                (
                    recovery_path.name,
                    doc_id,
                    doc_hash,
                    derive_public_key(signing_seed),
                )
            ],
        )

    def test_inventory_reports_recovery_document_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            extension_dir = root_dir / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            doc_id, doc_hash = doc_id_and_hash_from_ciphertext(b"ciphertext")
            signing_seed = b"\x33" * 32
            (extension_dir / "qr_document-01-cafebabedeadbeef.pdf").write_bytes(b"qr")
            (extension_dir / "recovery_document-01-cafebabedeadbeef.pdf").write_bytes(b"recovery")

            def _reject(_carrier, _document, _sign_pub):
                raise ValueError("stale recovery document")

            inventory = inspect_published_extension_inventory(
                root_dir,
                read_carrier_document=lambda _carrier: _imported_document(
                    doc_id=doc_id,
                    doc_hash=doc_hash,
                    signing_seed=signing_seed,
                ),
                read_shard_frames=lambda _carrier: [],
                validate_recovery_document_carrier=_reject,
            )

        self.assertIsNotNone(inventory.failure)
        self.assertEqual(inventory.failure.head_index, 1)
        self.assertIn("stale recovery document", inventory.failure.message)

    def test_published_chain_refuses_extensions_when_root_auth_is_not_verified(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="a.txt", data=b"root", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            input_origin="file",
            input_roots=(),
        )
        extension = ImportedRecoveryDocument.from_ciphertext(
            ciphertext=b"not decoded when root auth is missing",
            auth_frames=(),
            source_label="01",
            extension_index=1,
            extension_dir_name="01",
        )
        inventory = RecoveryExtensionInventory(
            extensions=(extension,),
            latest_head_index=1,
            latest_head_doc_hash=extension.doc_hash.hex(),
            latest_head_dir_name="01",
        )

        inspection = inspect_published_extension_chain(
            manifest=manifest,
            payload=payload,
            root_doc_hash=b"\x44" * 32,
            passphrase="secret",
            expected_sign_pub=derive_public_key(b"\x33" * 32),
            root_auth_status="missing",
            quiet=True,
            debug=False,
            inventory=inventory,
        )

        self.assertIsNotNone(inspection.refusal)
        assert inspection.refusal is not None
        self.assertEqual(inspection.refusal.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(inspection.refusal.details["root_auth_status"], "missing")
        self.assertEqual(inspection.links, ())
        self.assertEqual(inspection.validated_head_index, 0)
        self.assertFalse(inspection.validated_head_root_authority_verified)


if __name__ == "__main__":
    unittest.main()
