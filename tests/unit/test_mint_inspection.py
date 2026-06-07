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

import hashlib
import unittest
from types import SimpleNamespace
from unittest import mock

from ethernity.cli.features.mint.workflow import (
    _decode_mint_extension_candidates,
    _resolve_mint_chain_target,
    execute_mint,
    inspect_mint_inputs,
)
from ethernity.cli.features.recover.planning import (
    RecoveryInspection,
    RecoveryPlan,
    RecoveryUnlockStatus,
)
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import MintArgs
from ethernity.crypto.sharding import KEY_TYPE_PASSPHRASE
from ethernity.crypto.signing import (
    AuthPayload,
    derive_public_key,
    encode_auth_payload,
    sign_auth,
)
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.extensions.recovery import ImportedRecoveryDocument
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
    ExtensionEnvelope,
    ExtensionEnvelopeHeader,
    ExtensionFile,
)
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC

ROOT_SIGNING_SEED = b"\x33" * 32
ROOT_SIGN_PUB = derive_public_key(ROOT_SIGNING_SEED)


def _root_auth(doc_hash: bytes = b"\x77" * 32) -> AuthPayload:
    return AuthPayload(
        version=1,
        doc_hash=doc_hash,
        sign_pub=ROOT_SIGN_PUB,
        signature=sign_auth(doc_hash, sign_pub=ROOT_SIGN_PUB, sign_priv=ROOT_SIGNING_SEED),
    )


def _auth_frame(doc_id: bytes, doc_hash: bytes) -> Frame:
    return Frame(
        version=VERSION,
        frame_type=FrameType.AUTH,
        doc_id=doc_id,
        index=0,
        total=1,
        data=encode_auth_payload(
            doc_hash,
            sign_pub=ROOT_SIGN_PUB,
            signature=sign_auth(
                doc_hash,
                sign_pub=ROOT_SIGN_PUB,
                sign_priv=ROOT_SIGNING_SEED,
            ),
        ),
    )


def _extension_envelope(index: int, *, root_doc_hash: bytes) -> ExtensionEnvelope:
    return ExtensionEnvelope(
        header=ExtensionEnvelopeHeader(
            version=1,
            index=index,
            parent_doc_hash=b"\x77" * 32,
            root_doc_hash=root_doc_hash,
            created_at=1,
            chunking=ExtensionChunkingProfile(
                algorithm_id=CHUNK_ALGORITHM_FASTCDC,
                target_size=64 * 1024,
                min_size=16 * 1024,
                max_size=256 * 1024,
            ),
            input_origin="file",
            input_roots=(),
        ),
        files=(
            ExtensionFile(
                path="empty.txt",
                size=0,
                sha256=hashlib.sha256(b"").digest(),
                mtime=None,
                chunk_refs=(),
            ),
        ),
        chunks=(),
    )


def _mint_candidate(document: ImportedRecoveryDocument, *, index: int) -> SimpleNamespace:
    return SimpleNamespace(
        document=document,
        envelope=SimpleNamespace(header=SimpleNamespace(index=index)),
    )


def _imported_document(
    *,
    doc_id: bytes,
    doc_hash: bytes,
    ciphertext: bytes,
    source_label: str,
) -> ImportedRecoveryDocument:
    return ImportedRecoveryDocument(
        doc_id=doc_id,
        doc_hash=doc_hash,
        ciphertext=ciphertext,
        auth_frames=(),
        source_label=source_label,
    )


def _mint_recovery_plan(
    *,
    extension_index: int | None = None,
    extension_doc_hash: str | None = None,
    expected_head_doc_hash: str | None = None,
    import_documents: tuple[ImportedRecoveryDocument, ...] = (),
) -> RecoveryPlan:
    root_auth = _root_auth()
    return RecoveryPlan(
        ciphertext=b"root-ciphertext",
        doc_id=b"\x66" * 8,
        doc_hash=b"\x77" * 32,
        passphrase="passphrase",
        auth_payload=root_auth,
        auth_status="verified",
        allow_unsigned=False,
        output_path=None,
        input_label="Scan",
        input_detail="/tmp/root",
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
        import_documents=import_documents,
    )


class TestMintInspection(unittest.TestCase):
    def test_inspect_mint_inputs_deduplicates_auth_required_blockers(self) -> None:
        args = MintArgs(payloads_file="main.txt", quiet=True)
        state = SimpleNamespace(
            frames=(),
            extra_auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            signing_key_frames=(),
            input_label="QR payloads",
            input_detail="main.txt",
        )
        auth_required = {
            "code": "AUTH_REQUIRED",
            "message": "minting requires an authenticated backup input with an AUTH payload",
            "details": {},
        }
        recovery = SimpleNamespace(
            auth_payload=None,
            blocking_issues=(),
            unlock=SimpleNamespace(satisfied=False, resolved_passphrase=None),
            ciphertext=b"",
            doc_id=b"\x01" * 8,
            doc_hash=b"\x02" * 32,
        )

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._load_mint_input_state",
                return_value=state,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._recovery_shard_inputs_for_plan",
                return_value=([], [], []),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.inspect_recovery_inputs",
                return_value=recovery,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_signing_key_state",
                return_value=(0, None, False, "signing-key shards", [auth_required]),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_replacement_blockers",
                return_value=[],
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_capabilities",
                return_value={
                    "can_mint_passphrase_shards": False,
                    "can_mint_signing_key_shards": False,
                },
            ),
        ):
            inspection = inspect_mint_inputs(args)

        auth_required_issues = [
            issue for issue in inspection.blocking_issues if issue.get("code") == "AUTH_REQUIRED"
        ]
        self.assertEqual(len(auth_required_issues), 1)

    def test_inspect_mint_inputs_resolves_extension_chain_target_for_readiness(self) -> None:
        args = MintArgs(scan=["/tmp/root"], passphrase="passphrase", quiet=True)
        root_auth = _root_auth()
        extension_auth = AuthPayload(
            version=1,
            doc_hash=b"\x44" * 32,
            sign_pub=ROOT_SIGN_PUB,
            signature=b"\x55" * 64,
        )
        state = SimpleNamespace(
            frames=(),
            extra_auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            signing_key_frames=(),
            input_label="Scan",
            input_detail="/tmp/root",
            recover_args=SimpleNamespace(),
            config=SimpleNamespace(),
        )
        recovery = RecoveryInspection(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            unlock=RecoveryUnlockStatus(
                mode="passphrase",
                passphrase_provided=True,
                validated_shard_count=0,
                required_shard_threshold=None,
                satisfied=True,
                resolved_passphrase="passphrase",
            ),
            blocking_issues=(),
        )
        root_plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            passphrase="passphrase",
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            root_dir=None,
            import_documents=(object(), object()),
        )
        extension_plan = root_plan.__class__(
            **{
                **root_plan.__dict__,
                "ciphertext": b"extension-ciphertext",
                "doc_id": b"\x88" * 8,
                "doc_hash": b"\x44" * 32,
                "auth_payload": extension_auth,
                "auth_status": "verified",
            }
        )
        manifest = SimpleNamespace(
            format_version=1,
            input_origin="file",
            input_roots=(),
            sealed=False,
            payload_codec="raw",
            payload_raw_len=0,
            files=(),
        )
        captured: dict[str, RecoveryInspection] = {}

        def _capture_replacement_blockers(**kwargs):
            captured["recovery"] = kwargs["recovery"]
            return []

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._load_mint_input_state",
                return_value=state,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._recovery_shard_inputs_for_plan",
                return_value=([], [], []),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.build_recovery_plan",
                return_value=root_plan,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.inspect_recovery_inputs",
                return_value=recovery,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._resolve_mint_chain_target",
                return_value=extension_plan,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.recover_chain_entries",
                return_value=SimpleNamespace(
                    manifest=manifest,
                    selected_extension_index=1,
                    selected_extension_doc_hash="44" * 32,
                ),
            ) as recover_chain_entries,
            mock.patch(
                "ethernity.cli.features.mint.workflow.decrypt_bytes",
                return_value=b"root-plaintext",
            ) as decrypt_bytes,
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_envelope",
                return_value=(manifest, b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_signing_key_state",
                return_value=(0, None, True, "embedded", []),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_replacement_blockers",
                side_effect=_capture_replacement_blockers,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_capabilities",
                return_value={
                    "can_mint_passphrase_shards": True,
                    "can_mint_signing_key_shards": True,
                },
            ),
        ):
            inspection = inspect_mint_inputs(args)

        self.assertEqual(inspection.recovery.doc_hash, b"\x44" * 32)
        self.assertEqual(inspection.recovery.auth_payload, extension_auth)
        self.assertEqual(inspection.source_summary["input_origin"], "file")
        self.assertEqual(inspection.selected_extension_index, 1)
        self.assertEqual(inspection.selected_extension_doc_hash, "44" * 32)
        self.assertEqual(captured["recovery"].doc_hash, b"\x44" * 32)
        recover_chain_entries.assert_called_once_with(root_plan, quiet=True, debug=False)
        decrypt_bytes.assert_not_called()

    def test_inspect_mint_inputs_does_not_report_unlock_failure_after_chain_trust_failure(
        self,
    ) -> None:
        args = MintArgs(scan=["/tmp/root"], passphrase="passphrase", quiet=True)
        root_auth = _root_auth()
        state = SimpleNamespace(
            frames=(),
            extra_auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            signing_key_frames=(),
            input_label="Scan",
            input_detail="/tmp/root",
            recover_args=SimpleNamespace(),
            config=SimpleNamespace(),
        )
        recovery = RecoveryInspection(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            unlock=RecoveryUnlockStatus(
                mode="passphrase",
                passphrase_provided=True,
                validated_shard_count=0,
                required_shard_threshold=None,
                satisfied=True,
                resolved_passphrase="passphrase",
            ),
            blocking_issues=(),
        )
        root_plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            passphrase="passphrase",
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            root_dir=None,
            import_documents=(object(), object()),
        )

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._load_mint_input_state",
                return_value=state,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._recovery_shard_inputs_for_plan",
                return_value=([], [], []),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.build_recovery_plan",
                return_value=root_plan,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.inspect_recovery_inputs",
                return_value=recovery,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._resolve_mint_chain_target",
                side_effect=ValueError("imported extension chain could not be trusted"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.recover_chain_entries",
            ) as recover_chain_entries,
            mock.patch(
                "ethernity.cli.features.mint.workflow.decrypt_bytes",
            ) as decrypt_bytes,
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_signing_key_state",
                return_value=(0, None, False, "signing-key shards", []),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_replacement_blockers",
                return_value=[],
            ),
        ):
            inspection = inspect_mint_inputs(args)

        issue_codes = [issue["code"] for issue in inspection.blocking_issues]
        self.assertIn(api_codes.RECOVERY_HEAD_UNTRUSTED, issue_codes)
        self.assertNotIn("UNLOCK_FAILED", issue_codes)
        self.assertIsNone(inspection.manifest)
        self.assertIsNone(inspection.source_summary)
        self.assertIsNone(inspection.selected_extension_index)
        self.assertIsNone(inspection.selected_extension_doc_hash)
        recover_chain_entries.assert_not_called()
        decrypt_bytes.assert_not_called()

    def test_inspect_mint_inputs_uses_plan_passphrase_for_extension_shard_unlock(self) -> None:
        args = MintArgs(scan=["/tmp/root"], quiet=True)
        root_auth = _root_auth()
        shard_frame = Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x66" * 8,
            index=1,
            total=1,
            data=b"shard",
        )
        state = SimpleNamespace(
            frames=(),
            extra_auth_frames=(),
            shard_frames=(shard_frame,),
            shard_fallback_files=("shard.txt",),
            shard_payloads_file=("payloads.txt",),
            shard_scan=(),
            signing_key_frames=(),
            input_label="Scan",
            input_detail="/tmp/root",
            recover_args=SimpleNamespace(),
            config=SimpleNamespace(),
        )
        root_plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            passphrase="derived-passphrase",
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(shard_frame,),
            shard_fallback_files=("shard.txt",),
            shard_payloads_file=("payloads.txt",),
            shard_scan=(),
            root_dir=None,
        )
        recovery = RecoveryInspection(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            unlock=RecoveryUnlockStatus(
                mode="passphrase",
                passphrase_provided=True,
                validated_shard_count=0,
                required_shard_threshold=None,
                satisfied=False,
                resolved_passphrase=None,
            ),
            blocking_issues=(),
        )

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._load_mint_input_state",
                return_value=state,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._recovery_shard_inputs_for_plan",
                return_value=([shard_frame], ["shard.txt"], ["payloads.txt"]),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.build_recovery_plan",
                return_value=root_plan,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.inspect_recovery_inputs",
                return_value=recovery,
            ) as inspect_recovery_inputs,
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_shard_payload",
                return_value=SimpleNamespace(
                    key_type=KEY_TYPE_PASSPHRASE,
                    threshold=2,
                    share_count=3,
                    share_index=1,
                ),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_signing_key_state",
                return_value=(0, None, True, "embedded", []),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_replacement_blockers",
                return_value=[],
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_capabilities",
                return_value={
                    "can_mint_passphrase_shards": True,
                    "can_mint_signing_key_shards": True,
                },
            ),
        ):
            inspection = inspect_mint_inputs(args)

        self.assertEqual(
            inspect_recovery_inputs.call_args.kwargs["passphrase"],
            "derived-passphrase",
        )
        self.assertEqual(inspect_recovery_inputs.call_args.kwargs["shard_frames"], [])
        self.assertEqual(inspect_recovery_inputs.call_args.kwargs["shard_fallback_files"], [])
        self.assertEqual(inspect_recovery_inputs.call_args.kwargs["shard_payloads_file"], [])
        self.assertEqual(inspection.recovery.unlock.mode, "shards")
        self.assertEqual(inspection.recovery.unlock.validated_shard_count, 1)
        self.assertEqual(inspection.recovery.unlock.required_shard_threshold, 2)
        self.assertEqual(inspection.recovery.unlock.shard_share_count, 3)
        self.assertEqual(inspection.recovery.unlock.resolved_passphrase, "derived-passphrase")
        self.assertEqual(inspection.recovery.shard_frames, (shard_frame,))

    def test_execute_mint_passes_target_selection_without_root_dir_to_recovery_plan(self) -> None:
        args = MintArgs(
            scan=["/tmp/root"],
            extension_index=0,
            expected_head_doc_hash="ab" * 32,
            quiet=True,
        )
        state = SimpleNamespace(
            config=SimpleNamespace(),
            recover_args=SimpleNamespace(),
            frames=(),
            extra_auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            signing_key_frames=(),
            input_label="Scan",
            input_detail="/tmp/root",
            root_dir="/tmp/root",
        )
        captured: dict[str, object] = {}

        def _capture_build_recovery_plan(**kwargs):
            captured.update(kwargs)
            raise RuntimeError("stop")

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._load_mint_input_state",
                return_value=state,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._recovery_shard_inputs_for_plan",
                return_value=([], [], []),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.build_recovery_plan",
                side_effect=_capture_build_recovery_plan,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                execute_mint(args)

        self.assertIsNone(captured["root_dir"])
        self.assertEqual(captured["extension_index"], 0)
        self.assertIsNone(captured["extension_doc_hash"])
        self.assertEqual(captured["expected_head_doc_hash"], "ab" * 32)

    def test_execute_mint_missing_auth_raises_stable_api_code(self) -> None:
        args = MintArgs(payloads_file="main.txt", quiet=True)
        state = SimpleNamespace(
            config=SimpleNamespace(),
            frames=(),
            extra_auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            signing_key_frames=(),
            input_label="QR payloads",
            input_detail="main.txt",
            root_dir=None,
        )
        plan = SimpleNamespace(auth_payload=None)

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._load_mint_input_state",
                return_value=state,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._build_recovery_plan_for_mint",
                return_value=plan,
            ),
            self.assertRaises(ApiCommandError) as caught,
        ):
            execute_mint(args)

        self.assertEqual(caught.exception.code, api_codes.AUTH_REQUIRED)

    def test_resolve_mint_chain_target_uses_latest_extension(self) -> None:
        root_auth = _root_auth()
        extension_auth = AuthPayload(
            version=1,
            doc_hash=b"\x44" * 32,
            sign_pub=ROOT_SIGN_PUB,
            signature=b"\x55" * 64,
        )
        plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            passphrase="passphrase",
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            root_dir=None,
            import_documents=(
                ImportedRecoveryDocument(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    auth_frames=(),
                    source_label="root",
                ),
                ImportedRecoveryDocument(
                    doc_id=b"\x88" * 8,
                    doc_hash=b"\x44" * 32,
                    ciphertext=b"extension-ciphertext",
                    auth_frames=(),
                    source_label="extension",
                ),
            ),
        )
        decoded = SimpleNamespace(
            auth_payload=extension_auth,
            auth_status="verified",
            link=SimpleNamespace(
                doc_hash=b"\x44" * 32,
                document=SimpleNamespace(
                    header=SimpleNamespace(
                        index=1,
                        parent_doc_hash=plan.doc_hash,
                        root_doc_hash=plan.doc_hash,
                        chunking=object(),
                    )
                ),
            ),
        )
        candidate = _mint_candidate(plan.import_documents[1], index=1)

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._decode_mint_extension_candidates",
                return_value=(candidate,),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
                return_value=decoded,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(signing_seed=ROOT_SIGNING_SEED), b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.validate_authenticated_extension_chain",
                return_value=None,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow."
                "reconstruct_authenticated_latest_logical_state",
                return_value=(),
            ) as reconstruct_authenticated_latest_logical_state,
        ):
            resolved = _resolve_mint_chain_target(
                plan,
                quiet=True,
                debug=False,
                allow_stale_head=True,
            )

        self.assertEqual(resolved.ciphertext, b"extension-ciphertext")
        self.assertEqual(resolved.auth_payload, extension_auth)
        self.assertEqual(resolved.auth_status, "verified")
        self.assertEqual(resolved.import_documents, ())
        self.assertNotEqual(resolved.doc_id, plan.doc_id)
        reconstruct_authenticated_latest_logical_state.assert_called_once()

    def test_resolve_mint_chain_target_rejects_unacknowledged_imported_head(self) -> None:
        plan = _mint_recovery_plan(
            import_documents=(
                _imported_document(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    source_label="root",
                ),
                _imported_document(
                    doc_id=b"\x88" * 8,
                    doc_hash=b"\x44" * 32,
                    ciphertext=b"extension-ciphertext",
                    source_label="extension",
                ),
            ),
        )
        decoded = SimpleNamespace(
            auth_payload=_root_auth(b"\x44" * 32),
            auth_status="verified",
            link=SimpleNamespace(
                doc_hash=b"\x44" * 32,
                document=SimpleNamespace(
                    header=SimpleNamespace(
                        index=1,
                        parent_doc_hash=plan.doc_hash,
                        root_doc_hash=plan.doc_hash,
                        chunking=object(),
                    )
                ),
            ),
        )
        candidate = _mint_candidate(plan.import_documents[1], index=1)

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._decode_mint_extension_candidates",
                return_value=(candidate,),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
                return_value=decoded,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(signing_seed=ROOT_SIGNING_SEED), b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.validate_authenticated_extension_chain",
                return_value=None,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow."
                "reconstruct_authenticated_latest_logical_state",
                return_value=(),
            ),
            self.assertRaises(ApiCommandError) as caught,
        ):
            _resolve_mint_chain_target(plan, quiet=True, debug=False)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(caught.exception.details["required_acknowledgement"], "--allow-stale-head")
        self.assertEqual(caught.exception.details["validated_head_index"], 1)
        self.assertEqual(caught.exception.details["validated_head_doc_hash"], "44" * 32)

    def test_decode_mint_extension_candidates_skips_unauthenticated_docs_before_decrypt(
        self,
    ) -> None:
        plan = _mint_recovery_plan()
        unsigned_document = ImportedRecoveryDocument(
            doc_id=b"\x88" * 8,
            doc_hash=b"\x44" * 32,
            ciphertext=b"extension-ciphertext",
            auth_frames=(),
            source_label="unsigned",
        )

        with mock.patch("ethernity.cli.features.mint.workflow.decrypt_bytes") as decrypt_bytes:
            candidates = _decode_mint_extension_candidates(
                plan,
                import_documents=(unsigned_document,),
                passphrase="passphrase",
                root_sign_pub=ROOT_SIGN_PUB,
                fail_on_root_authority_errors=False,
                quiet=True,
                debug=False,
            )

        self.assertEqual(candidates, ())
        decrypt_bytes.assert_not_called()

    def test_decode_mint_extension_candidates_rejects_selected_bad_auth_before_decrypt(
        self,
    ) -> None:
        plan = _mint_recovery_plan()
        selected_doc_hash = b"\x44" * 32
        selected_document = ImportedRecoveryDocument(
            doc_id=b"\x88" * 8,
            doc_hash=selected_doc_hash,
            ciphertext=b"extension-ciphertext",
            auth_frames=(),
            source_label="selected",
        )

        with (
            mock.patch("ethernity.cli.features.mint.workflow.decrypt_bytes") as decrypt_bytes,
            self.assertRaisesRegex(
                ValueError,
                "selected extension doc_hash .* could not be trusted: "
                "imported extension AUTH could not be trusted",
            ),
        ):
            _decode_mint_extension_candidates(
                plan,
                import_documents=(selected_document,),
                passphrase="passphrase",
                root_sign_pub=ROOT_SIGN_PUB,
                requested_doc_hash=selected_doc_hash,
                fail_on_root_authority_errors=False,
                quiet=True,
                debug=False,
            )

        decrypt_bytes.assert_not_called()

    def test_decode_mint_extension_candidates_rejects_selected_malformed_extension(
        self,
    ) -> None:
        plan = _mint_recovery_plan()
        selected_doc_hash = b"\x44" * 32
        selected_document = ImportedRecoveryDocument(
            doc_id=b"\x88" * 8,
            doc_hash=selected_doc_hash,
            ciphertext=b"extension-ciphertext",
            auth_frames=(_auth_frame(b"\x88" * 8, selected_doc_hash),),
            source_label="selected",
        )

        with (
            mock.patch("ethernity.cli.features.mint.workflow.decrypt_bytes", return_value=b"plain"),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_any_envelope",
                side_effect=ValueError("bad extension envelope"),
            ),
            self.assertRaisesRegex(
                ValueError,
                "selected extension doc_hash .* could not be trusted: "
                "imported root-authority document could not be trusted: bad extension envelope",
            ),
        ):
            _decode_mint_extension_candidates(
                plan,
                import_documents=(selected_document,),
                passphrase="passphrase",
                root_sign_pub=ROOT_SIGN_PUB,
                requested_doc_hash=selected_doc_hash,
                fail_on_root_authority_errors=False,
                quiet=True,
                debug=False,
            )

    def test_decode_mint_extension_candidates_rejects_selected_wrong_root_extension(
        self,
    ) -> None:
        plan = _mint_recovery_plan()
        selected_doc_hash = b"\x44" * 32
        selected_document = ImportedRecoveryDocument(
            doc_id=b"\x88" * 8,
            doc_hash=selected_doc_hash,
            ciphertext=b"extension-ciphertext",
            auth_frames=(_auth_frame(b"\x88" * 8, selected_doc_hash),),
            source_label="selected",
        )

        with (
            mock.patch("ethernity.cli.features.mint.workflow.decrypt_bytes", return_value=b"plain"),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_any_envelope",
                return_value=(
                    2,
                    _extension_envelope(1, root_doc_hash=b"\x99" * 32),
                ),
            ),
            self.assertRaisesRegex(
                ValueError,
                "selected extension doc_hash .* could not be trusted: "
                "imported root-authority extension targets a different root backup",
            ),
        ):
            _decode_mint_extension_candidates(
                plan,
                import_documents=(selected_document,),
                passphrase="passphrase",
                root_sign_pub=ROOT_SIGN_PUB,
                requested_doc_hash=selected_doc_hash,
                fail_on_root_authority_errors=False,
                quiet=True,
                debug=False,
            )

    def test_resolve_mint_chain_target_rejects_duplicate_authenticated_extension_index(
        self,
    ) -> None:
        plan = _mint_recovery_plan(
            import_documents=(
                _imported_document(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    source_label="root",
                ),
                _imported_document(
                    doc_id=b"\x88" * 8,
                    doc_hash=b"\x44" * 32,
                    ciphertext=b"extension-one",
                    source_label="extension-one",
                ),
                _imported_document(
                    doc_id=b"\x99" * 8,
                    doc_hash=b"\x55" * 32,
                    ciphertext=b"extension-two",
                    source_label="extension-two",
                ),
            ),
        )
        first = _mint_candidate(plan.import_documents[1], index=1)
        second = _mint_candidate(plan.import_documents[2], index=1)

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(signing_seed=ROOT_SIGNING_SEED), b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._decode_mint_extension_candidates",
                return_value=(first, second),
            ),
            self.assertRaisesRegex(
                ValueError,
                "multiple authenticated extensions for index 1",
            ),
        ):
            _resolve_mint_chain_target(plan, quiet=True, debug=False, allow_stale_head=True)

    def test_resolve_mint_chain_target_rejects_unexpected_latest_head(self) -> None:
        plan = _mint_recovery_plan(
            expected_head_doc_hash="aa" * 32,
            import_documents=(
                _imported_document(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    source_label="root",
                ),
                _imported_document(
                    doc_id=b"\x88" * 8,
                    doc_hash=b"\x44" * 32,
                    ciphertext=b"extension-ciphertext",
                    source_label="extension",
                ),
            ),
        )
        decoded = SimpleNamespace(
            auth_payload=_root_auth(b"\x44" * 32),
            auth_status="verified",
            link=SimpleNamespace(
                doc_hash=b"\x44" * 32,
                document=SimpleNamespace(
                    header=SimpleNamespace(
                        index=1,
                        parent_doc_hash=plan.doc_hash,
                        root_doc_hash=plan.doc_hash,
                        chunking=object(),
                    )
                ),
            ),
        )
        candidate = _mint_candidate(plan.import_documents[1], index=1)

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._decode_mint_extension_candidates",
                return_value=(candidate,),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
                return_value=decoded,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(signing_seed=ROOT_SIGNING_SEED), b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.validate_authenticated_extension_chain",
                return_value=None,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow."
                "reconstruct_authenticated_latest_logical_state",
                return_value=(),
            ),
            self.assertRaises(ApiCommandError) as caught,
        ):
            _resolve_mint_chain_target(plan, quiet=True, debug=False)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(caught.exception.details["validated_head_index"], 1)
        self.assertEqual(caught.exception.details["validated_head_doc_hash"], "44" * 32)

    def test_resolve_mint_chain_target_can_select_root(self) -> None:
        plan = _mint_recovery_plan(
            extension_index=0,
            import_documents=(
                _imported_document(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    source_label="root",
                ),
                _imported_document(
                    doc_id=b"\x88" * 8,
                    doc_hash=b"\x44" * 32,
                    ciphertext=b"bad-extension",
                    source_label="extension",
                ),
            ),
        )

        with mock.patch(
            "ethernity.cli.features.mint.workflow.decode_root_manifest"
        ) as decode_root_manifest:
            resolved = _resolve_mint_chain_target(
                plan,
                quiet=True,
                debug=False,
                allow_stale_head=True,
            )

        decode_root_manifest.assert_not_called()
        self.assertEqual(resolved.doc_hash, plan.doc_hash)
        self.assertEqual(resolved.import_documents, ())
        self.assertIsNone(resolved.extension_index)
        self.assertIsNone(resolved.extension_doc_hash)

    def test_resolve_mint_chain_target_rejects_unexpected_root_head(self) -> None:
        plan = _mint_recovery_plan(
            extension_index=0,
            expected_head_doc_hash="aa" * 32,
            import_documents=(
                _imported_document(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    source_label="root",
                ),
            ),
        )

        with self.assertRaises(ApiCommandError) as caught:
            _resolve_mint_chain_target(plan, quiet=True, debug=False)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(caught.exception.details["validated_head_index"], 0)
        self.assertEqual(caught.exception.details["validated_head_doc_hash"], "77" * 32)

    def test_resolve_mint_chain_target_can_select_prior_extension_by_doc_hash(self) -> None:
        root_document = _imported_document(
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            ciphertext=b"root-ciphertext",
            source_label="root",
        )
        first_document = _imported_document(
            doc_id=b"\x88" * 8,
            doc_hash=b"\x44" * 32,
            ciphertext=b"extension-one",
            source_label="extension-1",
        )
        second_document = _imported_document(
            doc_id=b"\x99" * 8,
            doc_hash=b"\x55" * 32,
            ciphertext=b"extension-two",
            source_label="extension-2",
        )
        plan = _mint_recovery_plan(
            extension_doc_hash="44" * 32,
            import_documents=(root_document, first_document, second_document),
        )
        first_auth = AuthPayload(
            version=1,
            doc_hash=b"\x44" * 32,
            sign_pub=ROOT_SIGN_PUB,
            signature=b"\x55" * 64,
        )
        first_decoded = SimpleNamespace(
            auth_payload=first_auth,
            auth_status="verified",
            link=SimpleNamespace(
                doc_hash=b"\x44" * 32,
                document=SimpleNamespace(
                    header=SimpleNamespace(
                        index=1,
                        parent_doc_hash=plan.doc_hash,
                        root_doc_hash=plan.doc_hash,
                        chunking=object(),
                    )
                ),
            ),
        )
        candidates = (
            _mint_candidate(first_document, index=1),
            _mint_candidate(second_document, index=2),
        )

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._decode_mint_extension_candidates",
                return_value=candidates,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
                return_value=first_decoded,
            ) as decode_imported_extension_link,
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(signing_seed=ROOT_SIGNING_SEED), b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.validate_authenticated_extension_chain",
                return_value=None,
            ) as validate_authenticated_extension_chain,
            mock.patch(
                "ethernity.cli.features.mint.workflow."
                "reconstruct_authenticated_latest_logical_state",
                return_value=(),
            ) as reconstruct_authenticated_latest_logical_state,
        ):
            resolved = _resolve_mint_chain_target(
                plan,
                quiet=True,
                debug=False,
                allow_stale_head=True,
            )

        decode_imported_extension_link.assert_called_once()
        selected_links = validate_authenticated_extension_chain.call_args.kwargs["extensions"]
        self.assertEqual(len(selected_links), 1)
        replay_links = reconstruct_authenticated_latest_logical_state.call_args.kwargs["extensions"]
        self.assertEqual(len(replay_links), 1)
        self.assertEqual(resolved.ciphertext, b"extension-one")
        self.assertEqual(resolved.extension_index, 1)
        self.assertEqual(resolved.extension_doc_hash, "44" * 32)

    def test_resolve_mint_chain_target_rejects_root_authority_extension_for_wrong_root(
        self,
    ) -> None:
        root_auth = _root_auth()
        extension_auth = AuthPayload(
            version=1,
            doc_hash=b"\x44" * 32,
            sign_pub=ROOT_SIGN_PUB,
            signature=b"\x55" * 64,
        )
        plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            passphrase="passphrase",
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            root_dir=None,
            import_documents=(
                ImportedRecoveryDocument(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    auth_frames=(),
                    source_label="root",
                ),
                ImportedRecoveryDocument(
                    doc_id=b"\x88" * 8,
                    doc_hash=b"\x44" * 32,
                    ciphertext=b"extension-ciphertext",
                    auth_frames=(),
                    source_label="extension",
                ),
            ),
        )
        _ = extension_auth

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._decode_mint_extension_candidates",
                side_effect=ValueError(
                    "imported root-authority extension targets a different root backup"
                ),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(signing_seed=ROOT_SIGNING_SEED), b"payload"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "different root backup"):
                _resolve_mint_chain_target(plan, quiet=True, debug=False)

    def test_resolve_mint_chain_target_rejects_imported_doc_id_collision(self) -> None:
        root_auth = _root_auth()
        plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            passphrase="passphrase",
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            root_dir=None,
            import_documents=(
                ImportedRecoveryDocument(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    auth_frames=(),
                    source_label="root",
                ),
                ImportedRecoveryDocument(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x44" * 32,
                    ciphertext=b"extension-ciphertext",
                    auth_frames=(),
                    source_label="extension",
                ),
            ),
        )

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(signing_seed=ROOT_SIGNING_SEED), b"payload"),
            ),
            self.assertRaisesRegex(ValueError, "doc_id collides"),
        ):
            _resolve_mint_chain_target(plan, quiet=True, debug=False)

    def test_resolve_mint_chain_target_rejects_orphan_extension_head(self) -> None:
        root_auth = _root_auth()
        plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            passphrase="passphrase",
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            root_dir=None,
            import_documents=(
                ImportedRecoveryDocument(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    auth_frames=(),
                    source_label="root",
                ),
                ImportedRecoveryDocument(
                    doc_id=b"\x88" * 8,
                    doc_hash=b"\x44" * 32,
                    ciphertext=b"extension-ciphertext",
                    auth_frames=(),
                    source_label="extension",
                ),
            ),
        )
        decoded = SimpleNamespace(
            auth_payload=root_auth,
            auth_status="verified",
            link=SimpleNamespace(
                doc_hash=b"\x44" * 32,
                document=SimpleNamespace(
                    header=SimpleNamespace(
                        index=2,
                        parent_doc_hash=plan.doc_hash,
                        root_doc_hash=plan.doc_hash,
                        chunking=object(),
                    )
                ),
            ),
        )
        candidate = _mint_candidate(plan.import_documents[1], index=2)

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._decode_mint_extension_candidates",
                return_value=(candidate,),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
                return_value=decoded,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(signing_seed=ROOT_SIGNING_SEED), b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.validate_authenticated_extension_chain",
                side_effect=ValueError("extension index sequence is invalid"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "extension index sequence is invalid"):
                _resolve_mint_chain_target(plan, quiet=True, debug=False)

    def test_resolve_mint_chain_target_rejects_degraded_latest_head(self) -> None:
        root_auth = _root_auth()
        plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            passphrase="passphrase",
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            root_dir=None,
            import_documents=(
                ImportedRecoveryDocument(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    auth_frames=(),
                    source_label="root",
                ),
                ImportedRecoveryDocument(
                    doc_id=b"\x88" * 8,
                    doc_hash=b"\x44" * 32,
                    ciphertext=b"extension-ciphertext",
                    auth_frames=(),
                    source_label="extension",
                ),
            ),
        )
        candidate = _mint_candidate(plan.import_documents[1], index=1)

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._decode_mint_extension_candidates",
                return_value=(candidate,),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
                side_effect=ValueError("missing extension AUTH"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(signing_seed=ROOT_SIGNING_SEED), b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._mint_document_targets_current_root",
                return_value=True,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "could not be trusted"):
                _resolve_mint_chain_target(plan, quiet=True, debug=False)

    def test_resolve_mint_chain_target_rejects_extension_head_that_cannot_replay(self) -> None:
        root_auth = _root_auth()
        extension_auth = AuthPayload(
            version=1,
            doc_hash=b"\x44" * 32,
            sign_pub=ROOT_SIGN_PUB,
            signature=b"\x55" * 64,
        )
        plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            passphrase="passphrase",
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            root_dir=None,
            import_documents=(
                ImportedRecoveryDocument(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    auth_frames=(),
                    source_label="root",
                ),
                ImportedRecoveryDocument(
                    doc_id=b"\x88" * 8,
                    doc_hash=b"\x44" * 32,
                    ciphertext=b"extension-ciphertext",
                    auth_frames=(),
                    source_label="extension",
                ),
            ),
        )
        decoded = SimpleNamespace(
            auth_payload=extension_auth,
            auth_status="verified",
            link=SimpleNamespace(
                doc_hash=b"\x44" * 32,
                document=SimpleNamespace(
                    header=SimpleNamespace(
                        index=1,
                        parent_doc_hash=plan.doc_hash,
                        root_doc_hash=plan.doc_hash,
                        chunking=object(),
                    )
                ),
            ),
        )
        candidate = _mint_candidate(plan.import_documents[1], index=1)

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._decode_mint_extension_candidates",
                return_value=(candidate,),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
                return_value=decoded,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(signing_seed=ROOT_SIGNING_SEED), b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.validate_authenticated_extension_chain",
                return_value=None,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow."
                "reconstruct_authenticated_latest_logical_state",
                side_effect=ValueError("extension file references unresolved chunk_id"),
            ),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "imported extension chain could not be trusted: .*unresolved chunk_id",
            ):
                _resolve_mint_chain_target(plan, quiet=True, debug=False)

    def test_resolve_mint_chain_target_rejects_malformed_root_authority_document(
        self,
    ) -> None:
        root_auth = _root_auth()
        bad_doc_id = b"\x88" * 8
        bad_doc_hash = b"\x44" * 32
        bad_auth_frame = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=bad_doc_id,
            index=0,
            total=1,
            data=encode_auth_payload(
                bad_doc_hash,
                sign_pub=ROOT_SIGN_PUB,
                signature=sign_auth(
                    bad_doc_hash,
                    sign_pub=ROOT_SIGN_PUB,
                    sign_priv=ROOT_SIGNING_SEED,
                ),
            ),
        )
        plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            passphrase="passphrase",
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            root_dir=None,
            import_documents=(
                ImportedRecoveryDocument(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    auth_frames=(),
                    source_label="root",
                ),
                ImportedRecoveryDocument(
                    doc_id=bad_doc_id,
                    doc_hash=bad_doc_hash,
                    ciphertext=b"not-an-extension-envelope",
                    auth_frames=(bad_auth_frame,),
                    source_label="bad",
                ),
            ),
        )

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(signing_seed=ROOT_SIGNING_SEED), b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
                side_effect=ValueError("imported document did not decode as an extension envelope"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "root-authority document could not be trusted"):
                _resolve_mint_chain_target(plan, quiet=True, debug=False)

    def test_resolve_mint_chain_target_rejects_extension_without_unsealed_root_authority(
        self,
    ) -> None:
        root_auth = _root_auth()
        plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 8,
            doc_hash=b"\x77" * 32,
            passphrase="passphrase",
            auth_payload=root_auth,
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            root_dir=None,
            import_documents=(
                ImportedRecoveryDocument(
                    doc_id=b"\x66" * 8,
                    doc_hash=b"\x77" * 32,
                    ciphertext=b"root-ciphertext",
                    auth_frames=(),
                    source_label="root",
                ),
                ImportedRecoveryDocument(
                    doc_id=b"\x88" * 8,
                    doc_hash=b"\x44" * 32,
                    ciphertext=b"extension-ciphertext",
                    auth_frames=(),
                    source_label="extension",
                ),
            ),
        )
        decoded = SimpleNamespace(
            auth_payload=root_auth,
            auth_status="verified",
            link=SimpleNamespace(
                doc_hash=b"\x44" * 32,
                document=SimpleNamespace(
                    header=SimpleNamespace(
                        index=1,
                        parent_doc_hash=plan.doc_hash,
                        root_doc_hash=plan.doc_hash,
                        chunking=object(),
                    )
                ),
            ),
        )

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(signing_seed=None), b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
                return_value=decoded,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._mint_document_targets_current_root",
                return_value=True,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow."
                "reconstruct_authenticated_latest_logical_state",
                return_value=(),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "unsealed root signing authority"):
                _resolve_mint_chain_target(plan, quiet=True, debug=False)


if __name__ == "__main__":
    unittest.main()
