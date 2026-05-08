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

import dataclasses
import unittest
from unittest import mock

from ethernity.cli.features.recover.chain import (
    ImportedRecoveryDocument,
    recover_chain_entries,
)
from ethernity.cli.features.recover.planning import RecoveryPlan
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.crypto import _doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import InputFile
from ethernity.crypto.signing import AuthPayload, derive_public_key, encode_auth_payload, sign_auth
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.extensions.build import build_extension_document
from ethernity.formats.envelope_codec import (
    build_manifest_and_payload,
    encode_envelope,
    encode_extension_envelope,
)
from ethernity.formats.envelope_types import PayloadPart
from ethernity.formats.extension_envelope import ExtensionChunkingProfile
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC


def _root_ciphertext(data: bytes = b"root") -> tuple[bytes, bytes, bytes]:
    manifest, payload = build_manifest_and_payload(
        (PayloadPart(path="a.txt", data=data, mtime=1),),
        sealed=False,
        signing_seed=b"\x33" * 32,
        input_origin="file",
        input_roots=(),
    )
    envelope = encode_envelope(payload, manifest)
    doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(envelope)
    return envelope, doc_id, doc_hash


def _extension_ciphertext(
    root_doc_hash: bytes,
    *,
    index: int = 1,
    parent_doc_hash: bytes | None = None,
    data: bytes = b"root!",
) -> bytes:
    built = build_extension_document(
        index=index,
        parent_doc_hash=parent_doc_hash or root_doc_hash,
        root_doc_hash=root_doc_hash,
        chunking=ExtensionChunkingProfile(
            algorithm_id=CHUNK_ALGORITHM_FASTCDC,
            target_size=64 * 1024,
            min_size=16 * 1024,
            max_size=256 * 1024,
        ),
        input_files=(
            InputFile(
                source_path=None,
                relative_path="a.txt",
                data=data,
                mtime=2,
            ),
        ),
        input_origin="file",
        input_roots=(),
        chunker=lambda data, _profile: (data,),
    )
    return encode_extension_envelope(built.document)


def _extension_auth_frame(
    extension_doc_id: bytes,
    extension_doc_hash: bytes,
    *,
    signing_seed: bytes = b"\x33" * 32,
) -> Frame:
    sign_pub = derive_public_key(signing_seed)
    return Frame(
        version=VERSION,
        frame_type=FrameType.AUTH,
        doc_id=extension_doc_id,
        index=0,
        total=1,
        data=encode_auth_payload(
            extension_doc_hash,
            sign_pub=sign_pub,
            signature=sign_auth(
                extension_doc_hash,
                sign_pub=sign_pub,
                sign_priv=signing_seed,
            ),
        ),
    )


def _imported_document(
    ciphertext: bytes,
    *,
    auth_frames: tuple[Frame, ...] = (),
    source_label: str = "scan",
) -> ImportedRecoveryDocument:
    doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)
    return ImportedRecoveryDocument(
        doc_id=doc_id,
        doc_hash=doc_hash,
        ciphertext=ciphertext,
        auth_frames=auth_frames,
        source_label=source_label,
    )


def _recovery_plan(
    root_ciphertext: bytes,
    root_doc_id: bytes,
    root_doc_hash: bytes,
    *,
    extension_index: int | None = None,
    extension_doc_hash: str | None = None,
) -> RecoveryPlan:
    root_sign_pub = derive_public_key(b"\x33" * 32)
    return RecoveryPlan(
        ciphertext=root_ciphertext,
        doc_id=root_doc_id,
        doc_hash=root_doc_hash,
        passphrase="secret",
        auth_payload=AuthPayload(
            version=1,
            doc_hash=root_doc_hash,
            sign_pub=root_sign_pub,
            signature=b"\x99" * 64,
        ),
        auth_status="verified",
        allow_unsigned=False,
        output_path=None,
        input_label="Backup PDF or images",
        input_detail="loose scans",
        main_frames=(),
        auth_frames=(),
        shard_frames=(),
        shard_fallback_files=(),
        shard_payloads_file=(),
        shard_scan=(),
        root_dir=None,
        extension_index=extension_index,
        extension_doc_hash=extension_doc_hash,
    )


class TestRecoverChain(unittest.TestCase):
    def test_recover_chain_entries_replays_content_import_without_directory_layout(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash),
            import_documents=(
                _imported_document(root_ciphertext, source_label="scan0001.pdf"),
                _imported_document(
                    extension_ciphertext,
                    auth_frames=(_extension_auth_frame(extension_doc_id, extension_doc_hash),),
                    source_label="renamed-extension.pdf",
                ),
            ),
        )

        with mock.patch(
            "ethernity.cli.features.recover.chain.decrypt_bytes",
            side_effect=lambda data, *, passphrase, debug=False: data,
        ):
            result = recover_chain_entries(plan, quiet=True)

        self.assertEqual(result.selected_extension_index, 1)
        self.assertEqual(result.selected_extension_doc_hash, extension_doc_hash.hex())
        self.assertEqual(
            [(entry.path, data) for entry, data in result.extracted],
            [("a.txt", b"root!")],
        )

    def test_recover_chain_entries_selects_root_only_despite_broken_later_extension(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash, extension_index=0),
            import_documents=(
                _imported_document(root_ciphertext),
                _imported_document(
                    extension_ciphertext,
                    auth_frames=(
                        _extension_auth_frame(
                            extension_doc_id,
                            extension_doc_hash,
                            signing_seed=b"\x77" * 32,
                        ),
                    ),
                ),
            ),
        )

        with mock.patch(
            "ethernity.cli.features.recover.chain.decrypt_bytes",
            side_effect=lambda data, *, passphrase, debug=False: data,
        ):
            result = recover_chain_entries(plan, quiet=True)

        self.assertIsNone(result.selected_extension_index)
        self.assertIsNone(result.selected_extension_doc_hash)
        self.assertEqual(
            [(entry.path, data) for entry, data in result.extracted],
            [("a.txt", b"root")],
        )

    def test_recover_chain_entries_selects_earlier_index_despite_broken_later_extension(
        self,
    ) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        first_ciphertext = _extension_ciphertext(root_doc_hash, index=1, data=b"root!")
        first_doc_id, first_doc_hash = _doc_id_and_hash_from_ciphertext(first_ciphertext)
        second_ciphertext = _extension_ciphertext(
            root_doc_hash,
            index=2,
            parent_doc_hash=first_doc_hash,
            data=b"root!!",
        )
        second_doc_id, second_doc_hash = _doc_id_and_hash_from_ciphertext(second_ciphertext)
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash, extension_index=1),
            import_documents=(
                _imported_document(root_ciphertext),
                _imported_document(
                    first_ciphertext,
                    auth_frames=(_extension_auth_frame(first_doc_id, first_doc_hash),),
                ),
                _imported_document(
                    second_ciphertext,
                    auth_frames=(
                        _extension_auth_frame(
                            second_doc_id,
                            second_doc_hash,
                            signing_seed=b"\x77" * 32,
                        ),
                    ),
                ),
            ),
        )

        with mock.patch(
            "ethernity.cli.features.recover.chain.decrypt_bytes",
            side_effect=lambda data, *, passphrase, debug=False: data,
        ):
            result = recover_chain_entries(plan, quiet=True)

        self.assertEqual(result.selected_extension_index, 1)
        self.assertEqual(result.selected_extension_doc_hash, first_doc_hash.hex())
        self.assertEqual(
            [(entry.path, data) for entry, data in result.extracted],
            [("a.txt", b"root!")],
        )

    def test_recover_chain_entries_rejects_missing_selected_extension_index(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash, index=1)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash, extension_index=2),
            import_documents=(
                _imported_document(root_ciphertext),
                _imported_document(
                    extension_ciphertext,
                    auth_frames=(_extension_auth_frame(extension_doc_id, extension_doc_hash),),
                ),
            ),
        )

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaisesRegex(ValueError, "extension index 2 was not found"),
        ):
            recover_chain_entries(plan, quiet=True)

    def test_recover_chain_entries_rejects_missing_selected_extension_for_root_only(
        self,
    ) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash, extension_index=1),
            import_documents=(_imported_document(root_ciphertext),),
        )

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaisesRegex(ValueError, "extension index 1 was not found"),
        ):
            recover_chain_entries(plan, quiet=True)

    def test_recover_chain_entries_rejects_content_import_with_bad_extension_auth(
        self,
    ) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash),
            import_documents=(
                _imported_document(root_ciphertext),
                _imported_document(
                    extension_ciphertext,
                    auth_frames=(
                        _extension_auth_frame(
                            extension_doc_id,
                            extension_doc_hash,
                            signing_seed=b"\x77" * 32,
                        ),
                    ),
                ),
            ),
        )

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaises(ApiCommandError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn("signing key does not match", caught.exception.message)

    def test_recover_chain_entries_rejects_root_authority_non_extension_document(
        self,
    ) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        unrelated_ciphertext, unrelated_doc_id, unrelated_doc_hash = _root_ciphertext(b"other")
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash),
            import_documents=(
                _imported_document(root_ciphertext),
                _imported_document(
                    unrelated_ciphertext,
                    auth_frames=(_extension_auth_frame(unrelated_doc_id, unrelated_doc_hash),),
                ),
            ),
        )

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaises(ApiCommandError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn("did not decode as an extension envelope", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
