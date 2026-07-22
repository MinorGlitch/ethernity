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
from collections.abc import Callable
from unittest import mock

from ethernity.cli.features.recover.planning import RecoveryPlan
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.types import InputFile
from ethernity.crypto import AgeError, age_runtime
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.signing import AuthPayload, derive_public_key, encode_auth_payload, sign_auth
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.extensions.build import _build_extension_document
from ethernity.extensions.chain import ExtensionReplayError
from ethernity.extensions.errors import ExtensionRecoveryError
from ethernity.extensions.recovery import (
    ImportedRecoveryDocument,
    decode_imported_extension_link,
    imported_documents_from_recovery_frames,
    recover_chain_entries,
    select_root_import_document,
    select_root_import_session,
)
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
    built = _build_extension_document(
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
        chunker=lambda data, _profile: ((0, len(data)),),
        existing_file_sizes={},
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
    expected_head_doc_hash: str | None = None,
) -> RecoveryPlan:
    root_signing_seed = b"\x33" * 32
    root_sign_pub = derive_public_key(root_signing_seed)
    return RecoveryPlan(
        ciphertext=root_ciphertext,
        doc_id=root_doc_id,
        doc_hash=root_doc_hash,
        passphrase="secret",
        auth_payload=AuthPayload(
            version=1,
            doc_hash=root_doc_hash,
            sign_pub=root_sign_pub,
            signature=sign_auth(root_doc_hash, sign_pub=root_sign_pub, sign_priv=root_signing_seed),
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
        expected_head_doc_hash=expected_head_doc_hash,
    )


def _candidate_locked_chain_plan(
    *,
    passphrase: str,
) -> tuple[RecoveryPlan, bytes, bytes, bytes]:
    root_plaintext = _root_ciphertext()[0]
    root_ciphertext = b"candidate-locked-root-ciphertext"
    root_doc_id, root_doc_hash = doc_id_and_hash_from_ciphertext(root_ciphertext)
    extension_plaintext = _extension_ciphertext(root_doc_hash)
    extension_ciphertext = b"candidate-locked-extension-ciphertext"
    extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
    plan = dataclasses.replace(
        _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash),
        passphrase=passphrase,
        import_documents=(
            _imported_document(root_ciphertext, source_label="root.pdf"),
            _imported_document(
                extension_ciphertext,
                auth_frames=(_extension_auth_frame(extension_doc_id, extension_doc_hash),),
                source_label="extension.pdf",
            ),
        ),
    )
    return plan, root_plaintext, extension_plaintext, extension_doc_hash


def _candidate_decrypt_side_effect(
    plaintext_by_candidate: dict[tuple[bytes, str], bytes],
) -> Callable[[bytes, str], bytes]:
    def decrypt(ciphertext: bytes, passphrase: str) -> bytes:
        plaintext = plaintext_by_candidate.get((ciphertext, passphrase))
        if plaintext is None:
            raise AgeError(backend="pyrage", detail="Decryption failed")
        return plaintext

    return decrypt


class TestRecoverChain(unittest.TestCase):
    def test_import_rejects_more_than_128_documents_before_reassembly(self) -> None:
        frames = [
            Frame(
                version=VERSION,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=index.to_bytes(8, "big"),
                index=0,
                total=1,
                data=b"ciphertext",
            )
            for index in range(1, 130)
        ]

        with self.assertRaisesRegex(ValueError, "MAX_RECOVERY_DOCUMENTS"):
            imported_documents_from_recovery_frames(frames)

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
            "ethernity.extensions.recovery.decrypt_bytes",
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

    def test_multi_document_recovery_locks_exact_passphrase_for_complete_chain(self) -> None:
        exact = "  " + "  ".join(["abandon"] * 11 + ["about"]) + "  "
        plan, root_plaintext, extension_plaintext, extension_doc_hash = (
            _candidate_locked_chain_plan(passphrase=exact)
        )
        root_document, extension_document = plan.import_documents

        with mock.patch.object(
            age_runtime,
            "_decrypt_with_pyrage",
            side_effect=_candidate_decrypt_side_effect(
                {
                    (root_document.ciphertext, exact): root_plaintext,
                    (extension_document.ciphertext, exact): extension_plaintext,
                }
            ),
        ) as decrypt_candidate:
            result = recover_chain_entries(plan, quiet=True)

        self.assertEqual(result.selected_extension_doc_hash, extension_doc_hash.hex())
        self.assertEqual(
            [(call.args[0], call.args[1]) for call in decrypt_candidate.call_args_list],
            [
                (root_document.ciphertext, exact),
                (extension_document.ciphertext, exact),
            ],
        )

    def test_multi_document_recovery_retries_complete_chain_with_canonical_bip39(self) -> None:
        exact = "  " + "  ".join(["abandon"] * 11 + ["about"]) + "  "
        canonical = " ".join(["abandon"] * 11 + ["about"])
        plan, root_plaintext, extension_plaintext, extension_doc_hash = (
            _candidate_locked_chain_plan(passphrase=exact)
        )
        root_document, extension_document = plan.import_documents

        with mock.patch.object(
            age_runtime,
            "_decrypt_with_pyrage",
            side_effect=_candidate_decrypt_side_effect(
                {
                    (root_document.ciphertext, canonical): root_plaintext,
                    (extension_document.ciphertext, canonical): extension_plaintext,
                }
            ),
        ) as decrypt_candidate:
            result = recover_chain_entries(plan, quiet=True)

        self.assertEqual(result.selected_extension_doc_hash, extension_doc_hash.hex())
        self.assertEqual(
            [(call.args[0], call.args[1]) for call in decrypt_candidate.call_args_list],
            [
                (root_document.ciphertext, exact),
                (extension_document.ciphertext, exact),
                (root_document.ciphertext, canonical),
                (extension_document.ciphertext, canonical),
            ],
        )

    def test_multi_document_recovery_rejects_mixed_exact_and_canonical_chain(self) -> None:
        exact = "  " + "  ".join(["abandon"] * 11 + ["about"]) + "  "
        canonical = " ".join(["abandon"] * 11 + ["about"])
        plan, root_plaintext, extension_plaintext, _extension_doc_hash = (
            _candidate_locked_chain_plan(passphrase=exact)
        )
        root_document, extension_document = plan.import_documents

        with (
            mock.patch.object(
                age_runtime,
                "_decrypt_with_pyrage",
                side_effect=_candidate_decrypt_side_effect(
                    {
                        (root_document.ciphertext, exact): root_plaintext,
                        (extension_document.ciphertext, canonical): extension_plaintext,
                    }
                ),
            ) as decrypt_candidate,
            self.assertRaisesRegex(ValueError, "one consistent passphrase candidate"),
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(
            [(call.args[0], call.args[1]) for call in decrypt_candidate.call_args_list],
            [
                (root_document.ciphertext, exact),
                (extension_document.ciphertext, exact),
                (root_document.ciphertext, canonical),
                (extension_document.ciphertext, canonical),
            ],
        )

    def test_recover_chain_entries_reuses_root_selection_decrypt_session(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
        documents = (
            _imported_document(root_ciphertext, source_label="scan0001.pdf"),
            _imported_document(
                extension_ciphertext,
                auth_frames=(_extension_auth_frame(extension_doc_id, extension_doc_hash),),
                source_label="scan0002.pdf",
            ),
        )

        with mock.patch(
            "ethernity.extensions.recovery.decrypt_bytes",
            side_effect=lambda data, *, passphrase, debug=False: data,
        ) as decrypt_bytes:
            decoded_import_session = select_root_import_session(
                documents,
                passphrase="secret",
                debug=False,
            )
            plan = dataclasses.replace(
                _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash),
                import_documents=documents,
                decoded_import_session=decoded_import_session,
            )
            result = recover_chain_entries(plan, quiet=True)

        self.assertEqual(result.selected_extension_index, 1)
        self.assertEqual(
            [call.args[0] for call in decrypt_bytes.call_args_list],
            [root_ciphertext, extension_ciphertext],
        )

    def test_recover_chain_entries_reverifies_root_auth_signature_at_replay_boundary(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
        base_plan = _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash)
        assert base_plan.auth_payload is not None
        forged_auth = dataclasses.replace(base_plan.auth_payload, signature=b"\x99" * 64)
        plan = dataclasses.replace(
            base_plan,
            auth_payload=forged_auth,
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
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.AUTH_SIGNATURE_INVALID)

    def test_recover_chain_entries_rejects_unexpected_default_head_doc_hash(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
        plan = dataclasses.replace(
            _recovery_plan(
                root_ciphertext,
                root_doc_id,
                root_doc_hash,
                expected_head_doc_hash="aa" * 32,
            ),
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
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn("does not match expected head", caught.exception.message)
        self.assertEqual(caught.exception.details["expected_head_doc_hash"], "aa" * 32)
        self.assertEqual(
            caught.exception.details["validated_head_doc_hash"], extension_doc_hash.hex()
        )
        self.assertEqual(caught.exception.details["freshness_scope"], "supplied_carriers_only")

    def test_imported_document_rejects_doc_id_not_derived_from_ciphertext(self) -> None:
        _root_ciphertext_bytes, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        _extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        with self.assertRaisesRegex(ValueError, "doc_id does not match ciphertext"):
            ImportedRecoveryDocument(
                doc_id=root_doc_id,
                doc_hash=extension_doc_hash,
                ciphertext=extension_ciphertext,
                auth_frames=(_extension_auth_frame(root_doc_id, extension_doc_hash),),
                source_label="colliding-extension.pdf",
            )

    def test_imported_document_rejects_doc_hash_not_derived_from_ciphertext(self) -> None:
        ciphertext = b"extension-ciphertext"
        doc_id, _doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)

        with self.assertRaisesRegex(ValueError, "doc_hash does not match ciphertext"):
            ImportedRecoveryDocument(
                doc_id=doc_id,
                doc_hash=b"\xff" * 32,
                ciphertext=ciphertext,
                auth_frames=(),
                source_label="spoofed-extension.pdf",
            )

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
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
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
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            mock.patch(
                "ethernity.extensions.recovery.reconstruct_authenticated_latest_logical_state",
                side_effect=ExtensionReplayError(
                    "extension parent_doc_hash does not match previous document",
                    failure_phase="lineage",
                    failing_index=1,
                    failing_hash=extension_doc_hash,
                    last_validated_head_index=0,
                    last_validated_head_hash=root_doc_hash,
                ),
            ) as replay,
            self.assertRaises(ExtensionRecoveryError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn("recovery head could not be trusted", str(caught.exception))
        self.assertEqual(caught.exception.details["stage"], "replay")
        replay.assert_called_once()
        self.assertEqual(caught.exception.details["failure_stage"], "lineage")
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
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(caught.exception.details["failure_stage"], "lineage")
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
            "ethernity.extensions.recovery.decrypt_bytes",
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

    def test_recover_chain_entries_rejects_root_index_with_extension_doc_hash(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        plan = dataclasses.replace(
            _recovery_plan(
                root_ciphertext,
                root_doc_id,
                root_doc_hash,
                extension_index=0,
                extension_doc_hash="11" * 32,
            ),
            import_documents=(_imported_document(root_ciphertext),),
        )

        with self.assertRaisesRegex(
            ValueError,
            "use either --extension-index or --extension-doc-hash",
        ):
            recover_chain_entries(plan, quiet=True)

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
            "ethernity.extensions.recovery.decrypt_bytes",
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
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
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
                    "ethernity.extensions.recovery.decrypt_bytes",
                    side_effect=lambda data, *, passphrase, debug=False: data,
                ),
                self.assertRaises(ExtensionRecoveryError) as caught,
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
            "ethernity.extensions.recovery.decrypt_bytes",
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
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn("extension index 2 was not found", caught.exception.message)
        self.assertEqual(caught.exception.details["stage"], "selection")
        self.assertEqual(caught.exception.details["latest_head_index"], 1)
        self.assertEqual(caught.exception.details["latest_head_doc_hash"], extension_doc_hash.hex())
        self.assertEqual(caught.exception.details["requested_head_index"], 2)
        self.assertIsNone(caught.exception.details["requested_head_doc_hash"])
        self.assertEqual(caught.exception.details["validated_head_index"], 0)
        self.assertEqual(caught.exception.details["validated_head_doc_hash"], root_doc_hash.hex())
        self.assertTrue(caught.exception.details["explicit_selection"])

    def test_recover_chain_entries_rejects_missing_selected_extension_doc_hash_as_untrusted(
        self,
    ) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
        requested_doc_hash = "aa" * 32
        plan = dataclasses.replace(
            _recovery_plan(
                root_ciphertext,
                root_doc_id,
                root_doc_hash,
                extension_doc_hash=requested_doc_hash,
            ),
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
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn(
            f"extension doc_hash {requested_doc_hash} was not found", caught.exception.message
        )
        self.assertEqual(caught.exception.details["stage"], "selection")
        self.assertEqual(caught.exception.details["latest_head_index"], 1)
        self.assertEqual(caught.exception.details["latest_head_doc_hash"], extension_doc_hash.hex())
        self.assertIsNone(caught.exception.details["requested_head_index"])
        self.assertEqual(caught.exception.details["requested_head_doc_hash"], requested_doc_hash)
        self.assertEqual(caught.exception.details["validated_head_index"], 0)
        self.assertEqual(caught.exception.details["validated_head_doc_hash"], root_doc_hash.hex())
        self.assertTrue(caught.exception.details["explicit_selection"])

    def test_recover_chain_entries_rejects_bad_selected_extension_doc_hash_as_untrusted(
        self,
    ) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        selected_ciphertext = b"not an extension envelope"
        selected_doc_id, selected_doc_hash = doc_id_and_hash_from_ciphertext(selected_ciphertext)
        plan = dataclasses.replace(
            _recovery_plan(
                root_ciphertext,
                root_doc_id,
                root_doc_hash,
                extension_doc_hash=selected_doc_hash.hex(),
            ),
            import_documents=(
                _imported_document(root_ciphertext),
                _imported_document(
                    selected_ciphertext,
                    auth_frames=(_extension_auth_frame(selected_doc_id, selected_doc_hash),),
                ),
            ),
        )

        with (
            mock.patch(
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn("could not be decoded", caught.exception.message)
        self.assertNotIn("was not found", caught.exception.message)
        self.assertEqual(caught.exception.details["stage"], "decode")
        self.assertEqual(caught.exception.details["extension_doc_hash"], selected_doc_hash.hex())
        self.assertTrue(caught.exception.details["explicit_selection"])

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
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn("extension index 1 was not found", caught.exception.message)
        self.assertEqual(caught.exception.details["stage"], "selection")
        self.assertIsNone(caught.exception.details["latest_head_index"])
        self.assertIsNone(caught.exception.details["latest_head_doc_hash"])
        self.assertEqual(caught.exception.details["requested_head_index"], 1)
        self.assertIsNone(caught.exception.details["requested_head_doc_hash"])
        self.assertEqual(caught.exception.details["validated_head_index"], 0)
        self.assertEqual(caught.exception.details["validated_head_doc_hash"], root_doc_hash.hex())
        self.assertTrue(caught.exception.details["explicit_selection"])

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
        decrypt_calls: list[bytes] = []

        def _decrypt(data: bytes, *, passphrase: str, debug: bool = False) -> bytes:
            _ = (passphrase, debug)
            decrypt_calls.append(data)
            if data == extension_ciphertext:
                raise AssertionError("extension body was decrypted before AUTH verification")
            return data

        with (
            mock.patch(
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=_decrypt,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn("signing key does not match", caught.exception.message)
        self.assertNotIn(extension_ciphertext, decrypt_calls)

    def test_recover_chain_entries_rejects_malformed_extension_auth_before_decrypt(
        self,
    ) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, _extension_doc_hash = doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        malformed_auth_frame = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=extension_doc_id,
            index=0,
            total=1,
            data=b"\xff",
        )
        plan = dataclasses.replace(
            _recovery_plan(root_ciphertext, root_doc_id, root_doc_hash),
            import_documents=(
                _imported_document(root_ciphertext),
                _imported_document(
                    extension_ciphertext,
                    auth_frames=(malformed_auth_frame,),
                ),
            ),
        )
        decrypt_calls: list[bytes] = []

        def _decrypt(data: bytes, *, passphrase: str, debug: bool = False) -> bytes:
            _ = (passphrase, debug)
            decrypt_calls.append(data)
            if data == extension_ciphertext:
                raise AssertionError("extension body was decrypted before AUTH verification")
            return data

        with (
            mock.patch(
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=_decrypt,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn("imported extension AUTH could not be verified", caught.exception.message)
        self.assertEqual(caught.exception.details["stage"], "auth")
        self.assertNotIn(extension_ciphertext, decrypt_calls)

    def test_recover_chain_entries_rejects_selected_bad_auth_before_decrypt(
        self,
    ) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
        plan = dataclasses.replace(
            _recovery_plan(
                root_ciphertext,
                root_doc_id,
                root_doc_hash,
                extension_doc_hash=extension_doc_hash.hex(),
            ),
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
        decrypt_calls: list[bytes] = []

        def _decrypt(data: bytes, *, passphrase: str, debug: bool = False) -> bytes:
            _ = (passphrase, debug)
            decrypt_calls.append(data)
            if data == extension_ciphertext:
                raise AssertionError("extension body was decrypted before AUTH verification")
            return data

        with (
            mock.patch(
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=_decrypt,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
        ):
            recover_chain_entries(plan, quiet=True)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn("signing key does not match", caught.exception.message)
        self.assertEqual(caught.exception.details["stage"], "auth")
        self.assertEqual(caught.exception.details["extension_doc_hash"], extension_doc_hash.hex())
        self.assertTrue(caught.exception.details["explicit_selection"])
        self.assertNotIn(extension_ciphertext, decrypt_calls)

    def test_decode_imported_extension_link_rejects_bad_auth_before_decrypt(
        self,
    ) -> None:
        _root_ciphertext_bytes, _root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
        document = _imported_document(
            extension_ciphertext,
            auth_frames=(
                _extension_auth_frame(
                    extension_doc_id,
                    extension_doc_hash,
                    signing_seed=b"\x77" * 32,
                ),
            ),
        )

        with (
            mock.patch(
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=AssertionError("extension body was decrypted before AUTH verification"),
            ) as decrypt_bytes,
            self.assertRaisesRegex(ValueError, "signing key does not match"),
        ):
            decode_imported_extension_link(
                document,
                passphrase="secret",
                expected_sign_pub=derive_public_key(b"\x33" * 32),
                quiet=True,
                debug=False,
            )

        decrypt_bytes.assert_not_called()

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
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaises(ExtensionRecoveryError) as caught,
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
                "ethernity.extensions.recovery.decrypt_bytes",
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
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
            self.assertRaisesRegex(ValueError, "contains multiple root backups"),
        ):
            select_root_import_document(documents, passphrase="secret", debug=False)


if __name__ == "__main__":
    unittest.main()
