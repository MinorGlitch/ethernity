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

from ethernity.crypto.signing import derive_public_key, encode_auth_payload, sign_auth
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions.published import inspect_published_extension_inventory
from ethernity.extensions.recovery import ImportedRecoveryDocument


class TestPublishedExtensionInventory(unittest.TestCase):
    def test_inventory_identity_comes_from_carrier_content_not_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            extension_dir = root_dir / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            stale_doc_id_hex = "deadbeefcafebabe"
            content_doc_id = bytes.fromhex("cafebabedeadbeef")
            content_doc_hash = b"\x44" * 32
            (extension_dir / f"qr_document-01-{stale_doc_id_hex}.pdf").write_bytes(b"qr")
            (extension_dir / f"recovery_document-01-{stale_doc_id_hex}.pdf").write_bytes(
                b"recovery"
            )

            signing_seed = b"\x33" * 32
            sign_pub = derive_public_key(signing_seed)
            auth_frame = Frame(
                version=1,
                frame_type=FrameType.AUTH,
                doc_id=content_doc_id,
                index=0,
                total=1,
                data=encode_auth_payload(
                    content_doc_hash,
                    sign_pub=sign_pub,
                    signature=sign_auth(
                        content_doc_hash, sign_pub=sign_pub, sign_priv=signing_seed
                    ),
                ),
            )

            inventory = inspect_published_extension_inventory(
                root_dir,
                read_carrier_document=lambda _carrier: ImportedRecoveryDocument(
                    doc_id=content_doc_id,
                    doc_hash=content_doc_hash,
                    ciphertext=b"ciphertext",
                    auth_frames=(auth_frame,),
                    source_label="qr",
                ),
            )

        self.assertIsNone(inventory.failure)
        self.assertEqual(len(inventory.extensions), 1)
        self.assertEqual(inventory.extensions[0].doc_id, content_doc_id)
        self.assertEqual(inventory.latest_head_doc_hash, content_doc_hash.hex())


if __name__ == "__main__":
    unittest.main()
