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

import unittest

from ethernity.cli.features.recover.execution import decrypt_manifest_and_extract
from ethernity.cli.features.recover.planning import RecoveryPlan
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.crypto import doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.crypto.signing import AuthPayload, derive_public_key, sign_auth
from ethernity.formats.envelope_codec import build_manifest_and_payload, encode_envelope
from ethernity.formats.envelope_types import PayloadPart


class TestRecoverExecution(unittest.TestCase):
    def test_decrypt_manifest_and_extract_rejects_root_authority_mismatch(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="a.txt", data=b"root", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            input_origin="file",
            input_roots=(),
        )
        plaintext = encode_envelope(payload, manifest)
        ciphertext, _resolved_passphrase = encrypt_bytes_with_passphrase(
            plaintext,
            passphrase="secret",
        )
        doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        wrong_seed = b"\x77" * 32
        wrong_sign_pub = derive_public_key(wrong_seed)
        plan = RecoveryPlan(
            ciphertext=ciphertext,
            doc_id=doc_id,
            doc_hash=doc_hash,
            passphrase="secret",
            auth_payload=AuthPayload(
                version=1,
                doc_hash=doc_hash,
                sign_pub=wrong_sign_pub,
                signature=sign_auth(doc_hash, sign_pub=wrong_sign_pub, sign_priv=wrong_seed),
            ),
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="QR payloads",
            input_detail="payloads.txt",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
        )

        with self.assertRaisesRegex(
            ValueError,
            "embedded signing seed does not match the verified root AUTH authority",
        ):
            decrypt_manifest_and_extract(plan, quiet=True, debug=False)

    def test_decrypt_manifest_and_extract_rejects_unexpected_root_head(self) -> None:
        signing_seed = b"\x33" * 32
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="a.txt", data=b"root", mtime=1),),
            sealed=False,
            signing_seed=signing_seed,
            input_origin="file",
            input_roots=(),
        )
        plaintext = encode_envelope(payload, manifest)
        ciphertext, _resolved_passphrase = encrypt_bytes_with_passphrase(
            plaintext,
            passphrase="secret",
        )
        doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        sign_pub = derive_public_key(signing_seed)
        plan = RecoveryPlan(
            ciphertext=ciphertext,
            doc_id=doc_id,
            doc_hash=doc_hash,
            passphrase="secret",
            auth_payload=AuthPayload(
                version=1,
                doc_hash=doc_hash,
                sign_pub=sign_pub,
                signature=sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=signing_seed),
            ),
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="QR payloads",
            input_detail="payloads.txt",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            expected_head_doc_hash="aa" * 32,
        )

        with self.assertRaises(ApiCommandError) as caught:
            decrypt_manifest_and_extract(plan, quiet=True, debug=False)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(caught.exception.details["validated_head_index"], 0)
        self.assertEqual(caught.exception.details["validated_head_doc_hash"], doc_hash.hex())
