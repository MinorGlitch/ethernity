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

from ethernity.cli.flows.backup_flow import (
    _create_auth_frame,
    _prepare_envelope,
)
from ethernity.core.models import DocumentPlan
from ethernity.crypto.signing import (
    decode_auth_payload,
    generate_signing_keypair,
    verify_auth,
)
from ethernity.encoding.framing import DOC_ID_LEN, FrameType
from ethernity.formats.envelope_codec import decode_envelope
from ethernity.formats.envelope_types import PayloadPart


class MockInputFile:
    """Mock InputFile for testing."""

    def __init__(self, relative_path: str, data: bytes, mtime: int | None = None) -> None:
        self.relative_path = relative_path
        self.data = data
        self.mtime = mtime


class TestPrepareEnvelope(unittest.TestCase):
    """Tests for _prepare_envelope function."""

    def test_basic_envelope_creation(self) -> None:
        """Test basic envelope creation from input files."""
        sign_priv, sign_pub = generate_signing_keypair()
        input_files = [
            MockInputFile("test.txt", b"hello world", mtime=1234),
        ]
        plan = DocumentPlan(version=1, sealed=False, sharding=None, signing_seed_sharding=None)

        envelope, payload = _prepare_envelope(input_files, plan, sign_priv)

        # Verify envelope can be decoded
        manifest, decoded_payload = decode_envelope(envelope)
        self.assertEqual(decoded_payload, b"hello world")
        self.assertEqual(len(manifest.files), 1)
        self.assertEqual(manifest.files[0].path, "test.txt")
        self.assertEqual(manifest.signing_seed, sign_priv)

    def test_sealed_envelope(self) -> None:
        """Test sealed envelope creation."""
        sign_priv, sign_pub = generate_signing_keypair()
        input_files = [
            MockInputFile("sealed.txt", b"sealed content"),
        ]
        plan = DocumentPlan(version=1, sealed=True, sharding=None, signing_seed_sharding=None)

        envelope, payload = _prepare_envelope(input_files, plan, sign_priv)

        manifest, _ = decode_envelope(envelope)
        self.assertTrue(manifest.sealed)
        self.assertIsNone(manifest.signing_seed)

    def test_multiple_files(self) -> None:
        """Test envelope with multiple files."""
        sign_priv, sign_pub = generate_signing_keypair()
        input_files = [
            MockInputFile("file1.txt", b"content1", mtime=100),
            MockInputFile("dir/file2.txt", b"content2", mtime=200),
            MockInputFile("file3.bin", b"content3", mtime=300),
        ]
        plan = DocumentPlan(version=1, sealed=False, sharding=None, signing_seed_sharding=None)

        envelope, payload = _prepare_envelope(input_files, plan, sign_priv)

        manifest, decoded_payload = decode_envelope(envelope)
        self.assertEqual(len(manifest.files), 3)
        self.assertEqual(decoded_payload, b"content2content1content3")
        paths = [f.path for f in manifest.files]
        self.assertEqual(paths, ["dir/file2.txt", "file1.txt", "file3.bin"])


class TestCreateAuthFrame(unittest.TestCase):
    """Tests for _create_auth_frame function."""

    def test_auth_frame_creation(self) -> None:
        """Test basic auth frame creation."""
        sign_priv, sign_pub = generate_signing_keypair()
        doc_id = b"\x10" * DOC_ID_LEN
        doc_hash = hashlib.blake2b(b"test", digest_size=32).digest()

        frame = _create_auth_frame(doc_id, doc_hash, sign_priv, sign_pub)

        self.assertEqual(frame.frame_type, FrameType.AUTH)
        self.assertEqual(frame.doc_id, doc_id)
        self.assertEqual(frame.index, 0)
        self.assertEqual(frame.total, 1)

    def test_auth_frame_verifiable(self) -> None:
        """Test that auth frame signature can be verified."""
        sign_priv, sign_pub = generate_signing_keypair()
        doc_id = b"\x20" * DOC_ID_LEN
        doc_hash = hashlib.blake2b(b"important data", digest_size=32).digest()

        frame = _create_auth_frame(doc_id, doc_hash, sign_priv, sign_pub)

        # Decode the auth payload and verify signature
        auth_payload = decode_auth_payload(frame.data)
        self.assertEqual(auth_payload.doc_hash, doc_hash)
        self.assertEqual(auth_payload.sign_pub, sign_pub)

        # Verify the signature is valid
        is_valid = verify_auth(doc_hash, sign_pub=sign_pub, signature=auth_payload.signature)
        self.assertTrue(is_valid)

    def test_auth_frame_invalid_signature_fails(self) -> None:
        """Test that wrong signature fails verification."""
        sign_priv, sign_pub = generate_signing_keypair()
        other_priv, other_pub = generate_signing_keypair()
        doc_id = b"\x30" * DOC_ID_LEN
        doc_hash = hashlib.blake2b(b"data", digest_size=32).digest()

        frame = _create_auth_frame(doc_id, doc_hash, sign_priv, sign_pub)
        auth_payload = decode_auth_payload(frame.data)

        # Verify with wrong public key fails
        is_valid = verify_auth(doc_hash, sign_pub=other_pub, signature=auth_payload.signature)
        self.assertFalse(is_valid)


class TestRecoverFlow(unittest.TestCase):
    """Tests for recover flow functions."""

    def test_decrypt_and_extract_integration(self) -> None:
        """Test decrypt_and_extract with real encryption using full RecoveryPlan."""
        from ethernity.cli.core.crypto import _doc_id_and_hash_from_ciphertext
        from ethernity.cli.flows.recover_flow import decrypt_and_extract
        from ethernity.cli.flows.recover_plan import RecoveryPlan
        from ethernity.crypto import encrypt_bytes_with_passphrase
        from ethernity.formats.envelope_codec import (
            build_manifest_and_payload,
            encode_envelope,
        )

        # Create test data
        payload = b"test recovery content"
        parts = [PayloadPart(path="recovered.txt", data=payload, mtime=None)]
        signing_seed, _ = generate_signing_keypair()
        manifest, payload_out = build_manifest_and_payload(
            parts,
            sealed=False,
            created_at=0.0,
            signing_seed=signing_seed,
        )
        envelope = encode_envelope(payload_out, manifest)

        # Encrypt the envelope
        ciphertext, passphrase = encrypt_bytes_with_passphrase(envelope, passphrase=None)

        # Get doc_id and doc_hash from ciphertext
        doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)

        # Create recovery plan with all required fields
        plan = RecoveryPlan(
            ciphertext=ciphertext,
            doc_id=doc_id,
            doc_hash=doc_hash,
            passphrase=passphrase,
            auth_payload=None,
            auth_status="unsigned",
            allow_unsigned=True,
            output_path=None,
            input_label=None,
            input_detail=None,
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
        )

        # Decrypt and extract
        extracted = decrypt_and_extract(plan, quiet=True)

        self.assertEqual(len(extracted), 1)
        manifest_file, data = extracted[0]
        self.assertEqual(manifest_file.path, "recovered.txt")
        self.assertEqual(data, payload)


if __name__ == "__main__":
    unittest.main()
