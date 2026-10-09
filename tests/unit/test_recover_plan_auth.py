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

import tempfile
import unittest
from dataclasses import dataclass, replace
from pathlib import Path
from unittest import mock

import pytest

from ethernity.crypto.age_policy import RecoveryResourceLimitError
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.sharding import encode_shard_payload, split_passphrase
from ethernity.crypto.signing import derive_public_key, encode_auth_payload, sign_auth
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.extensions.build import _build_extension_document
from ethernity.extensions.recovery import recover_chain_entries
from ethernity.formats.document_codec import (
    build_manifest_and_payload,
    encode_backup_document,
    encode_extension_document,
)
from ethernity.formats.extension_constants import CHUNK_ALGORITHM_FASTCDC
from ethernity.formats.extension_document import ExtensionChunkingProfile
from ethernity.formats.manifest import BackupFile
from ethernity.workflows.recovery.frame_inputs import FrameInputResult
from ethernity.workflows.recovery.inputs import load_recovery_frames, load_shard_frames
from ethernity.workflows.recovery.inspection import _inspect_auth_payload
from ethernity.workflows.recovery.models import RecoveryInspection
from ethernity.workflows.recovery.planning import (
    RecoveryPlan,
    _resolve_passphrase,
    build_recovery_plan,
    inspect_from_request,
    inspect_recovery_inputs,
    plan_from_request,
)
from ethernity.workflows.replacement_recovery import service as replacement_service
from ethernity.workflows.shared.operation_types import InputFile
from ethernity.workflows.shared.requests import (
    RecoveryRequest,
    ReplacementRecoveryRequest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
V1_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "v1_0" / "golden" / "base64" / "file_no_shard"
V1_1_SHARDED_EMBEDDED_FIXTURE_ROOT = (
    REPO_ROOT / "tests" / "fixtures" / "v1_1" / "golden" / "base64" / "sharded_embedded"
)
TEST_SIGNING_SEED = b"\x33" * 32


def _main_frame(ciphertext: bytes) -> Frame:
    doc_id, _doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    return Frame(
        version=1,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=doc_id,
        index=0,
        total=1,
        data=ciphertext,
    )


def _auth_frame(ciphertext: bytes, *, signing_seed: bytes = TEST_SIGNING_SEED) -> Frame:
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
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


def _root_document(data: bytes = b"root") -> bytes:
    manifest, payload = build_manifest_and_payload(
        (BackupFile(path="a.txt", data=data, mtime=1),),
        sealed=False,
        signing_seed=TEST_SIGNING_SEED,
        input_origin="file",
        input_roots=(),
    )
    return encode_backup_document(payload, manifest)


def _extension_document(root_doc_hash: bytes) -> bytes:
    built = _build_extension_document(
        index=1,
        parent_doc_hash=root_doc_hash,
        root_doc_hash=root_doc_hash,
        chunking=ExtensionChunkingProfile(
            algorithm_id=CHUNK_ALGORITHM_FASTCDC,
            target_size=16 * 1024,
            min_size=4 * 1024,
            max_size=64 * 1024,
        ),
        input_files=(
            InputFile(
                source_path=None,
                relative_path="a.txt",
                data=b"root!",
                mtime=2,
            ),
        ),
        existing_file_sizes={},
    )
    return encode_extension_document(built.document)


def _passphrase_shard_frames(
    *,
    doc_id: bytes,
    doc_hash: bytes,
    passphrase: str = "secret",
) -> list[Frame]:
    sign_pub = derive_public_key(TEST_SIGNING_SEED)
    shards = split_passphrase(
        passphrase,
        threshold=2,
        shares=3,
        doc_hash=doc_hash,
        sign_priv=TEST_SIGNING_SEED,
        sign_pub=sign_pub,
    )
    return [
        Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=encode_shard_payload(shard),
        )
        for shard in shards[:2]
    ]


class TestInspectAuthPayload(unittest.TestCase):
    def test_direct_custom_passphrase_stays_exact_until_decrypt(self) -> None:
        exact = "  " + "  ".join(["abandon"] * 11 + ["above"]) + "  "

        resolved = _resolve_passphrase(
            passphrase=exact,
            shard_frames=[],
            doc_id=b"\x11" * DOC_ID_LEN,
            doc_hash=b"\x22" * 32,
            sign_pub=None,
            allow_unsigned=False,
            args=None,
        )

        self.assertEqual(resolved, exact)

    def test_frames_from_args_decodes_sources_before_content_version_selection(self) -> None:
        main = _main_frame(b"root")
        with mock.patch(
            "ethernity.workflows.recovery.inputs.frame_inputs.recovery_frames_from_scan",
            return_value=FrameInputResult(frames=(main,)),
        ) as scan_mock:
            frames, label, detail = load_recovery_frames(
                RecoveryRequest(scan_paths=["backup-root"], extension_index=1),
                allow_unsigned=False,
                quiet=True,
            )

        self.assertEqual(frames, [main])
        self.assertEqual((label, detail), ("Backup PDF or images", "backup-root"))
        scan_mock.assert_called_once_with(
            ["backup-root"],
            notice_sink=mock.ANY,
        )

    @staticmethod
    def _auth_frame(*, doc_id: bytes) -> Frame:
        return Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"auth",
        )

    def test_doc_id_mismatch_is_ignored_in_allow_unsigned_mode(self) -> None:
        frame = self._auth_frame(doc_id=b"\x11" * DOC_ID_LEN)
        notices = []
        payload, status, blocking_issues = _inspect_auth_payload(
            [frame],
            doc_id=b"\x12" * DOC_ID_LEN,
            doc_hash=b"\x20" * 32,
            allow_unsigned=True,
            require_auth=False,
            notice_sink=notices.append,
        )
        self.assertIsNone(payload)
        self.assertEqual(status, "ignored")
        self.assertEqual(blocking_issues, ())
        self.assertEqual(len(notices), 1)

    def test_doc_id_mismatch_is_blocking_in_strict_mode(self) -> None:
        frame = self._auth_frame(doc_id=b"\x11" * DOC_ID_LEN)
        payload, status, blocking_issues = _inspect_auth_payload(
            [frame],
            doc_id=b"\x12" * DOC_ID_LEN,
            doc_hash=b"\x20" * 32,
            allow_unsigned=False,
            require_auth=True,
            notice_sink=None,
        )
        self.assertIsNone(payload)
        self.assertEqual(status, "invalid")
        self.assertEqual(len(blocking_issues), 1)
        self.assertEqual(blocking_issues[0]["code"], "AUTH_PAYLOAD_DOC_ID_MISMATCH")

    def test_inspect_recovery_is_not_ready_when_optional_auth_input_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_payloads_path = Path(tmpdir) / "auth-only.txt"
            auth_line = [
                line
                for line in (V1_FIXTURE_ROOT / "main_payloads.txt")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ][-1]
            auth_payloads_path.write_text(auth_line + "\n", encoding="utf-8")
            args = RecoveryRequest(
                payloads_file=str(V1_1_SHARDED_EMBEDDED_FIXTURE_ROOT / "main_payloads.txt"),
                shard_payload_files=[
                    str(V1_1_SHARDED_EMBEDDED_FIXTURE_ROOT / "shard_payloads_threshold.txt")
                ],
                auth_payloads_file=str(auth_payloads_path),
            )

            inspection = inspect_from_request(args)

            self.assertFalse(inspection.unlock.satisfied)
            self.assertIsNone(inspection.unlock.resolved_passphrase)
            self.assertIn(
                "AUTH_PAYLOAD_MULTIPLE",
                {issue["code"] for issue in inspection.blocking_issues},
            )
            with self.assertRaisesRegex(ValueError, "multiple auth payloads provided"):
                plan_from_request(args)

    def test_inspect_filters_separate_auth_to_selected_root_document(self) -> None:
        root_ciphertext = _root_document()
        _root_doc_id, root_doc_hash = doc_id_and_hash_from_ciphertext(root_ciphertext)
        extension_ciphertext = _extension_document(root_doc_hash)
        frames = [_main_frame(root_ciphertext), _main_frame(extension_ciphertext)]
        extra_auth_frames = [_auth_frame(root_ciphertext), _auth_frame(extension_ciphertext)]
        args = RecoveryRequest(passphrase="secret", quiet=True)

        with (
            mock.patch(
                "ethernity.workflows.recovery.inputs.load_recovery_frames",
                return_value=(frames, "Recovery input", "inline"),
            ),
            mock.patch(
                "ethernity.workflows.recovery.inputs.load_extra_auth_frames",
                return_value=extra_auth_frames,
            ),
            mock.patch(
                "ethernity.workflows.recovery.inputs.load_shard_frames",
                return_value=([], [], [], []),
            ),
            mock.patch(
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            inspection = inspect_from_request(args)

        self.assertEqual(inspection.doc_hash, root_doc_hash)
        self.assertEqual(inspection.auth_status, "verified")
        self.assertEqual(len(inspection.auth_frames), 1)
        self.assertNotIn(
            "AUTH_PAYLOAD_MULTIPLE",
            {issue["code"] for issue in inspection.blocking_issues},
        )

    def test_extension_local_shards_select_root_and_replay_imported_chain(self) -> None:
        root_ciphertext = _root_document()
        root_doc_id, root_doc_hash = doc_id_and_hash_from_ciphertext(root_ciphertext)
        extension_ciphertext = _extension_document(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
        frames = [
            _main_frame(root_ciphertext),
            _auth_frame(root_ciphertext),
            _main_frame(extension_ciphertext),
            _auth_frame(extension_ciphertext),
        ]
        shard_frames = _passphrase_shard_frames(
            doc_id=extension_doc_id,
            doc_hash=extension_doc_hash,
        )

        with mock.patch(
            "ethernity.extensions.recovery.decrypt_bytes",
            side_effect=lambda data, *, passphrase, debug=False: data,
        ):
            plan = build_recovery_plan(
                frames=frames,
                extra_auth_frames=[],
                shard_frames=shard_frames,
                passphrase=None,
                allow_unsigned=False,
                input_label="Recovery input",
                input_detail="inline",
                shard_fallback_files=[],
                shard_payloads_file=[],
                shard_scan=[],
                output_path=None,
                extension_index=None,
                extension_doc_hash=None,
                expected_head_doc_hash=None,
                args=None,
                quiet=True,
            )
            result = recover_chain_entries(plan)

        self.assertEqual(plan.doc_id, root_doc_id)
        self.assertEqual(plan.doc_hash, root_doc_hash)
        self.assertEqual(plan.passphrase, "secret")
        self.assertEqual(plan.shard_frames, tuple(shard_frames))
        self.assertEqual(len(plan.import_documents), 2)
        self.assertEqual(result.selected_extension_index, 1)
        self.assertEqual(result.selected_extension_doc_hash, extension_doc_hash.hex())
        self.assertEqual(
            [(entry.path, data) for entry, data in result.extracted],
            [("a.txt", b"root!")],
        )

    def test_arg_resolved_passphrase_selects_root_from_multiple_imported_docs(self) -> None:
        root_ciphertext = _root_document()
        root_doc_id, root_doc_hash = doc_id_and_hash_from_ciphertext(root_ciphertext)
        extension_ciphertext = _extension_document(root_doc_hash)
        frames = [
            _main_frame(root_ciphertext),
            _auth_frame(root_ciphertext),
            _main_frame(extension_ciphertext),
            _auth_frame(extension_ciphertext),
        ]
        args = RecoveryRequest(passphrase="secret", quiet=True)

        with mock.patch(
            "ethernity.extensions.recovery.decrypt_bytes",
            side_effect=lambda data, *, passphrase, debug=False: data,
        ):
            plan = build_recovery_plan(
                frames=frames,
                extra_auth_frames=[],
                shard_frames=[],
                passphrase=None,
                allow_unsigned=False,
                input_label="Recovery input",
                input_detail="inline",
                shard_fallback_files=[],
                shard_payloads_file=[],
                shard_scan=[],
                output_path=None,
                extension_index=None,
                extension_doc_hash=None,
                expected_head_doc_hash=None,
                args=args,
                quiet=True,
            )

        self.assertEqual(plan.doc_id, root_doc_id)
        self.assertEqual(plan.doc_hash, root_doc_hash)
        self.assertEqual(plan.passphrase, "secret")
        self.assertEqual(len(plan.import_documents), 2)

    def test_inspect_reports_extension_local_shards_as_root_unlock(self) -> None:
        root_ciphertext = _root_document()
        root_doc_id, root_doc_hash = doc_id_and_hash_from_ciphertext(root_ciphertext)
        extension_ciphertext = _extension_document(root_doc_hash)
        extension_doc_id, extension_doc_hash = doc_id_and_hash_from_ciphertext(extension_ciphertext)
        frames = [
            _main_frame(root_ciphertext),
            _auth_frame(root_ciphertext),
            _main_frame(extension_ciphertext),
            _auth_frame(extension_ciphertext),
        ]
        shard_frames = _passphrase_shard_frames(
            doc_id=extension_doc_id,
            doc_hash=extension_doc_hash,
        )
        args = RecoveryRequest(quiet=True)

        with (
            mock.patch(
                "ethernity.workflows.recovery.inputs.load_recovery_frames",
                return_value=(frames, "Recovery input", "inline"),
            ),
            mock.patch(
                "ethernity.workflows.recovery.inputs.load_extra_auth_frames",
                return_value=[],
            ),
            mock.patch(
                "ethernity.workflows.recovery.inputs.load_shard_frames",
                return_value=(shard_frames, [], [], []),
            ),
            mock.patch(
                "ethernity.extensions.recovery.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            inspection = inspect_from_request(args)

        self.assertEqual(inspection.doc_id, root_doc_id)
        self.assertEqual(inspection.doc_hash, root_doc_hash)
        self.assertEqual(inspection.auth_status, "verified")
        self.assertEqual(inspection.unlock.mode, "shards")
        self.assertTrue(inspection.unlock.satisfied)
        self.assertEqual(inspection.unlock.resolved_passphrase, "secret")
        self.assertEqual(inspection.unlock.validated_shard_count, 2)
        self.assertEqual(inspection.unlock.required_shard_threshold, 2)
        self.assertEqual(inspection.unlock.shard_share_count, 3)
        self.assertEqual(inspection.shard_frames, tuple(shard_frames))

    def test_shard_payload_file_errors_use_qr_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_path = Path(tmpdir) / "invalid-shard-payloads.txt"
            payload_path.write_text("not-a-valid-shard-payload\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "QR payload"):
                load_shard_frames(
                    RecoveryRequest(shard_payload_files=[str(payload_path)], quiet=True),
                    quiet=True,
                )

    def test_signing_key_shard_payload_file_errors_use_qr_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_path = Path(tmpdir) / "invalid-signing-shard-payloads.txt"
            payload_path.write_text("not-a-valid-shard-payload\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "QR payload"):
                replacement_service._signing_key_shard_frames_from_args(
                    ReplacementRecoveryRequest(
                        signing_key_shard_payload_files=[str(payload_path)], quiet=True
                    ),
                    quiet=True,
                )

    def test_build_recovery_plan_requires_auth_even_with_shards_in_strict_mode(self) -> None:
        doc_id, _doc_hash = doc_id_and_hash_from_ciphertext(b"ciphertext")
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        shard_frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"shard",
        )

        with mock.patch(
            "ethernity.workflows.recovery.planning._resolve_auth_payload",
            return_value=(None, "missing"),
        ) as resolve_auth_mock:
            with mock.patch(
                "ethernity.workflows.recovery.planning._resolve_passphrase",
                return_value="passphrase",
            ):
                build_recovery_plan(
                    frames=[main_frame],
                    extra_auth_frames=[],
                    shard_frames=[shard_frame],
                    passphrase="passphrase",
                    allow_unsigned=False,
                    input_label=None,
                    input_detail=None,
                    shard_fallback_files=[],
                    shard_payloads_file=[],
                    shard_scan=[],
                    output_path=None,
                    extension_index=None,
                    extension_doc_hash=None,
                    expected_head_doc_hash=None,
                    args=None,
                    quiet=True,
                )

        self.assertTrue(resolve_auth_mock.call_args.kwargs["require_auth"])

    def test_inspect_recovery_inputs_requires_auth_even_with_shards_in_strict_mode(self) -> None:
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        shard_frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"shard",
        )

        with mock.patch(
            "ethernity.workflows.recovery.inspection._inspect_auth_payload",
            return_value=(None, "missing", ()),
        ) as inspect_auth_mock:
            with mock.patch(
                "ethernity.workflows.recovery.inspection._inspect_unlock_status",
                return_value=mock.Mock(
                    satisfied=False,
                    resolved_passphrase=None,
                    blocking_issues=(),
                ),
            ):
                inspect_recovery_inputs(
                    frames=[main_frame],
                    extra_auth_frames=[],
                    shard_frames=[shard_frame],
                    passphrase=None,
                    allow_unsigned=False,
                    input_label=None,
                    input_detail=None,
                    shard_fallback_files=[],
                    shard_payloads_file=[],
                    shard_scan=[],
                    quiet=True,
                )

        self.assertTrue(inspect_auth_mock.call_args.kwargs["require_auth"])


@dataclass
class ImportedChainInputs:
    frames: list[Frame]
    auth_frames: list[Frame]
    shard_frames: list[Frame]
    decrypt: mock.Mock


@pytest.fixture
def imported_chain(monkeypatch: pytest.MonkeyPatch) -> ImportedChainInputs:
    root = _root_document()
    _, root_hash = doc_id_and_hash_from_ciphertext(root)
    extension = _extension_document(root_hash)
    chain = ImportedChainInputs(
        frames=[_main_frame(extension), _main_frame(root)],
        auth_frames=[_auth_frame(extension), _auth_frame(root)],
        shard_frames=[],
        decrypt=mock.Mock(side_effect=lambda data, *, passphrase, debug=False: data),
    )
    monkeypatch.setattr(
        "ethernity.workflows.recovery.inputs.load_recovery_frames",
        lambda *args, **kwargs: (chain.frames, "Recovery input", "inline"),
    )
    monkeypatch.setattr(
        "ethernity.workflows.recovery.inputs.load_extra_auth_frames",
        lambda *args, **kwargs: chain.auth_frames,
    )
    monkeypatch.setattr(
        "ethernity.workflows.recovery.inputs.load_shard_frames",
        lambda *args, **kwargs: (
            chain.shard_frames,
            [],
            ["extension-sheets.txt"] if chain.shard_frames else [],
            [],
        ),
    )
    monkeypatch.setattr("ethernity.extensions.recovery.decrypt_bytes", chain.decrypt)
    return chain


def _add_extension_shards(chain: ImportedChainInputs) -> None:
    extension = chain.frames[0]
    _, doc_hash = doc_id_and_hash_from_ciphertext(extension.data)
    chain.shard_frames.extend(_passphrase_shard_frames(doc_id=extension.doc_id, doc_hash=doc_hash))


@pytest.mark.parametrize("inspect_only", [False, True], ids=["execution", "inspection"])
@pytest.mark.parametrize("use_shards", [False, True], ids=["passphrase", "extension-shards"])
def test_root_selection_preserves_sources_and_decoded_session(
    imported_chain: ImportedChainInputs, inspect_only: bool, use_shards: bool
) -> None:
    if use_shards:
        _add_extension_shards(imported_chain)
    request = RecoveryRequest(passphrase=None if use_shards else "secret", quiet=True)
    result = inspect_from_request(request) if inspect_only else plan_from_request(request)
    root = imported_chain.frames[1]
    assert result.doc_id == root.doc_id
    assert result.auth_status == "verified"
    assert result.main_frames == (root,)
    assert result.auth_frames == (imported_chain.auth_frames[1],)
    assert result.shard_frames == tuple(imported_chain.shard_frames)
    assert result.shard_payloads_file == (("extension-sheets.txt",) if use_shards else ())
    session = result.decoded_import_session
    assert session is not None
    assert session.root_document.doc_id == root.doc_id
    assert imported_chain.decrypt.call_count == 2
    if isinstance(result, RecoveryPlan):
        recovered = recover_chain_entries(result)
        assert [(entry.path, data) for entry, data in recovered.extracted] == [("a.txt", b"root!")]
        assert result.passphrase == "secret"
        assert {document.doc_id for document in result.import_documents} == {
            frame.doc_id for frame in imported_chain.frames
        }
    else:
        assert isinstance(result, RecoveryInspection)
        assert result.source_frames == tuple(imported_chain.frames)
        assert result.source_extra_auth_frames == tuple(imported_chain.auth_frames)
        assert result.unlock.satisfied
        assert result.unlock.mode == ("shards" if use_shards else "passphrase")
        assert result.unlock.resolved_passphrase == "secret"
    assert imported_chain.decrypt.call_count == 2


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        ("missing", "PASSPHRASE_REQUIRED"),
        ("passphrase", "UNLOCK_FAILED"),
        ("shards", "PASSPHRASE_SHARDS_INVALID"),
        ("ambiguous", "UNLOCK_FAILED"),
    ],
)
def test_selection_failures_are_inspection_blockers_and_execution_errors(
    imported_chain: ImportedChainInputs, failure: str, code: str
) -> None:
    passphrase = None
    if failure == "passphrase":
        passphrase = "wrong"
        imported_chain.decrypt.side_effect = ValueError("decryption failed")
    elif failure == "shards":
        _add_extension_shards(imported_chain)
        imported_chain.shard_frames[:] = [replace(imported_chain.shard_frames[0], data=b"invalid")]
    elif failure == "ambiguous":
        passphrase = "secret"
        second_root = _root_document(b"other backup")
        imported_chain.frames[0] = _main_frame(second_root)
        imported_chain.auth_frames[0] = _auth_frame(second_root)
    request = RecoveryRequest(passphrase=passphrase, quiet=True)
    inspection = inspect_from_request(request)
    assert not inspection.unlock.satisfied
    assert inspection.unlock.resolved_passphrase is None
    assert inspection.decoded_import_session is None
    assert inspection.source_frames == tuple(imported_chain.frames)
    assert inspection.source_extra_auth_frames == tuple(imported_chain.auth_frames)
    assert inspection.shard_frames == tuple(imported_chain.shard_frames)
    issue = next(issue for issue in inspection.blocking_issues if issue["code"] == code)
    assert issue["details"]["stage"] == "root_selection"
    assert issue["details"]["main_document_count"] == 2
    with pytest.raises(ValueError):
        plan_from_request(request)


@pytest.mark.parametrize("inspect_only", [False, True], ids=["execution", "inspection"])
@pytest.mark.parametrize("use_shards", [False, True], ids=["passphrase", "extension-shards"])
def test_root_selection_never_swallows_resource_limits(
    imported_chain: ImportedChainInputs, inspect_only: bool, use_shards: bool
) -> None:
    if use_shards:
        _add_extension_shards(imported_chain)
    error = RecoveryResourceLimitError("recovery budget exceeded")
    imported_chain.decrypt.side_effect = error
    request = RecoveryRequest(passphrase=None if use_shards else "secret", quiet=True)
    recover = inspect_from_request if inspect_only else plan_from_request
    with pytest.raises(RecoveryResourceLimitError) as raised:
        recover(request)
    assert raised.value is error


if __name__ == "__main__":
    unittest.main()
