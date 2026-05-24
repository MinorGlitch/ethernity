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
    imported_documents_from_recovery_frames,
    recover_chain_entries,
    select_root_import_document,
)
from ethernity.cli.features.recover.planning import RecoveryPlan
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.crypto import doc_id_and_hash_from_ciphertext
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
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(envelope)
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
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
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
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
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
        self.assertEqual(result.manifest.input_origin, "directory")
        self.assertEqual(result.manifest.input_roots, ("reconstructed-state",))

    def test_recover_chain_entries_rejects_imported_doc_id_collision(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        _extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash),
            import_documents=(
                _imported_document(root_ciphertext, source_label="scan0001.pdf"),
                ImportedRecoveryDocument(
                    doc_id=root_doc_id,
                    doc_hash=extension_doc_hash,
                    ciphertext=extension_ciphertext,
                    auth_frames=(_extension_auth_frame(root_doc_id, extension_doc_hash),),
                    source_label="colliding-extension.pdf",
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
        self.assertIn("doc_id collides", str(caught.exception))
        self.assertEqual(caught.exception.details["stage"], "selection")
        self.assertEqual(caught.exception.details["root_doc_id"], root_doc_id.hex())
        self.assertEqual(caught.exception.details["colliding_doc_hash"], extension_doc_hash.hex())

    def test_imported_documents_reject_raw_main_frame_doc_id_collision(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        frames = [
            Frame(
                version=VERSION,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=root_doc_id,
                index=0,
                total=1,
                data=root_ciphertext,
            ),
            Frame(
                version=VERSION,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=root_doc_id,
                index=0,
                total=1,
                data=extension_ciphertext,
            ),
        ]

        with self.assertRaisesRegex(ValueError, "conflicting duplicate frames"):
            imported_documents_from_recovery_frames(frames)

    def test_imported_documents_reject_orphan_auth_frame(self) -> None:
        _root_ciphertext_bytes, _root_doc_id, root_doc_hash = _root_ciphertext()
        auth_frame = _extension_auth_frame(b"\xaa" * 8, root_doc_hash)

        with self.assertRaisesRegex(ValueError, "AUTH frame.*without matching MAIN"):
            imported_documents_from_recovery_frames([auth_frame])

    def test_recover_chain_entries_rejects_duplicate_authenticated_extension_index(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        first_ciphertext = _extension_ciphertext(root_doc_hash, index=1, data=b"one")
        first_doc_id, first_doc_hash = doc_id_and_hash_from_ciphertext(first_ciphertext)
        second_ciphertext = _extension_ciphertext(root_doc_hash, index=1, data=b"two")
        second_doc_id, second_doc_hash = doc_id_and_hash_from_ciphertext(second_ciphertext)
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash),
            import_documents=(
                _imported_document(root_ciphertext, source_label="scan0001.pdf"),
                _imported_document(
                    first_ciphertext,
                    auth_frames=(_extension_auth_frame(first_doc_id, first_doc_hash),),
                    source_label="extension-one.pdf",
                ),
                _imported_document(
                    second_ciphertext,
                    auth_frames=(_extension_auth_frame(second_doc_id, second_doc_hash),),
                    source_label="extension-two.pdf",
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
        self.assertIn("multiple authenticated extensions for index 1", str(caught.exception))
        self.assertEqual(caught.exception.details["stage"], "selection")
        self.assertEqual(caught.exception.details["extension_index"], 1)

    def test_recover_chain_entries_wraps_replay_topology_failure_as_untrusted_head(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
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

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain."
                "reconstruct_authenticated_latest_logical_state",
                side_effect=ValueError(
                    "extension parent_doc_hash does not match previous document"
                ),
            ),
            self.assertRaises(ApiCommandError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn("recovery head could not be trusted", str(caught.exception))
        self.assertEqual(caught.exception.details["stage"], "replay")
        self.assertEqual(caught.exception.details["failure_stage"], "chain")
        self.assertEqual(
            caught.exception.details["failure_message"],
            "extension parent_doc_hash does not match previous document",
        )
        self.assertEqual(caught.exception.details["failure_head_index"], 1)
        self.assertEqual(
            caught.exception.details["failure_head_doc_hash"], extension_doc_hash.hex()
        )
        self.assertEqual(caught.exception.details["validated_head_index"], 0)
        self.assertEqual(caught.exception.details["validated_head_doc_hash"], root_doc_hash.hex())
        self.assertFalse(caught.exception.details["explicit_selection"])

    def test_recover_chain_entries_reports_first_replay_failure_not_latest_head(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        first_ciphertext = _extension_ciphertext(root_doc_hash, index=1, data=b"one")
        first_doc_id, first_doc_hash = doc_id_and_hash_from_ciphertext(first_ciphertext)
        second_ciphertext = _extension_ciphertext(
            root_doc_hash,
            index=2,
            parent_doc_hash=b"\x88" * 32,
            data=b"two",
        )
        second_doc_id, second_doc_hash = doc_id_and_hash_from_ciphertext(second_ciphertext)
        third_ciphertext = _extension_ciphertext(
            root_doc_hash,
            index=3,
            parent_doc_hash=second_doc_hash,
            data=b"three",
        )
        third_doc_id, third_doc_hash = doc_id_and_hash_from_ciphertext(third_ciphertext)
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash),
            import_documents=(
                _imported_document(root_ciphertext),
                _imported_document(
                    first_ciphertext,
                    auth_frames=(_extension_auth_frame(first_doc_id, first_doc_hash),),
                ),
                _imported_document(
                    second_ciphertext,
                    auth_frames=(_extension_auth_frame(second_doc_id, second_doc_hash),),
                ),
                _imported_document(
                    third_ciphertext,
                    auth_frames=(_extension_auth_frame(third_doc_id, third_doc_hash),),
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
        self.assertEqual(caught.exception.details["failure_head_index"], 2)
        self.assertEqual(
            caught.exception.details["failure_head_doc_hash"],
            second_doc_hash.hex(),
        )
        self.assertEqual(caught.exception.details["latest_head_index"], 3)
        self.assertEqual(
            caught.exception.details["latest_head_doc_hash"],
            third_doc_hash.hex(),
        )
        self.assertEqual(caught.exception.details["validated_head_index"], 1)
        self.assertEqual(
            caught.exception.details["validated_head_doc_hash"],
            first_doc_hash.hex(),
        )

    def test_recover_chain_entries_selects_root_only_despite_broken_later_extension(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
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
        self.assertEqual(result.manifest.input_origin, "file")
        self.assertEqual(result.manifest.input_roots, ())
        self.assertEqual(
            [(entry.path, data) for entry, data in result.extracted],
            [("a.txt", b"root")],
        )

    def test_recover_chain_entries_allows_internal_unsigned_root_only_selection(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash, extension_index=0),
            allow_unsigned=True,
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
        self.assertEqual(
            [(entry.path, data) for entry, data in result.extracted],
            [("a.txt", b"root")],
        )

    def test_recover_chain_entries_rejects_internal_unsigned_extension_replay(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash),
            allow_unsigned=True,
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
            self.assertRaises(ApiCommandError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn(
            "unsigned recovery is not supported for extension replay",
            caught.exception.message,
        )
        self.assertEqual(caught.exception.details["unsigned_recovery"], True)

    def test_recover_chain_entries_requires_verified_root_auth_for_extension_replay(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
        base_plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash),
            import_documents=(
                _imported_document(root_ciphertext),
                _imported_document(
                    extension_ciphertext,
                    auth_frames=(_extension_auth_frame(extension_doc_id, extension_doc_hash),),
                ),
            ),
        )

        plan_variants = (
            dataclasses.replace(base_plan, auth_payload=None, auth_status="missing"),
            dataclasses.replace(base_plan, auth_status="skipped"),
        )
        for plan in plan_variants:
            with (
                self.subTest(auth_status=plan.auth_status, has_auth=plan.auth_payload is not None),
                mock.patch(
                    "ethernity.cli.features.recover.chain.decrypt_bytes",
                    side_effect=lambda data, *, passphrase, debug=False: data,
                ),
                self.assertRaises(ApiCommandError) as caught,
            ):
                recover_chain_entries(plan, quiet=True)

            self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
            self.assertIn("requires verified root AUTH", caught.exception.message)
            self.assertEqual(caught.exception.details["stage"], "auth")
            self.assertEqual(caught.exception.details["root_auth_status"], plan.auth_status)

    def test_recover_chain_entries_selects_earlier_index_despite_broken_later_extension(
        self,
    ) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        first_ciphertext = _extension_ciphertext(root_doc_hash, index=1, data=b"root!")
        first_doc_id, first_doc_hash = doc_id_and_hash_from_ciphertext(first_ciphertext)
        second_ciphertext = _extension_ciphertext(
            root_doc_hash,
            index=2,
            parent_doc_hash=first_doc_hash,
            data=b"root!!",
        )
        second_doc_id, second_doc_hash = doc_id_and_hash_from_ciphertext(second_ciphertext)
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
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
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
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
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

    def test_select_root_import_document_rejects_missing_decryptable_root(self) -> None:
        root_ciphertext, _root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        documents = (_imported_document(extension_ciphertext),)

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaisesRegex(ValueError, "did not contain a decryptable root backup"),
        ):
            select_root_import_document(documents, passphrase="secret", debug=False)

    def test_select_root_import_document_rejects_multiple_decryptable_roots(self) -> None:
        first_ciphertext, _first_doc_id, _first_doc_hash = _root_ciphertext(b"one")
        second_ciphertext, _second_doc_id, _second_doc_hash = _root_ciphertext(b"two")
        documents = (_imported_document(first_ciphertext), _imported_document(second_ciphertext))

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaisesRegex(ValueError, "contains multiple root backups"),
        ):
            select_root_import_document(documents, passphrase="secret", debug=False)


if __name__ == "__main__":
    unittest.main()
