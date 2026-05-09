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

import unittest
from types import SimpleNamespace
from unittest import mock

from ethernity.cli.features.mint.workflow import (
    _resolve_mint_chain_target,
    execute_mint,
    inspect_mint_inputs,
)
from ethernity.cli.features.recover.chain import ImportedRecoveryDocument
from ethernity.cli.features.recover.planning import RecoveryPlan
from ethernity.cli.shared.types import MintArgs
from ethernity.crypto.signing import AuthPayload


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

    def test_execute_mint_does_not_pass_root_dir_to_recovery_plan(self) -> None:
        args = MintArgs(scan=["/tmp/root"], quiet=True)
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

    def test_resolve_mint_chain_target_uses_latest_extension(self) -> None:
        root_auth = AuthPayload(
            version=1,
            doc_hash=b"\x11" * 32,
            sign_pub=b"\x22" * 32,
            signature=b"\x33" * 64,
        )
        extension_auth = AuthPayload(
            version=1,
            doc_hash=b"\x44" * 32,
            sign_pub=b"\x22" * 32,
            signature=b"\x55" * 64,
        )
        plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 16,
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

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
                return_value=decoded,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(), b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.reconstruct_latest_logical_state",
                return_value=(),
            ) as reconstruct_latest_logical_state,
        ):
            resolved = _resolve_mint_chain_target(plan, quiet=True, debug=False)

        self.assertEqual(resolved.ciphertext, b"extension-ciphertext")
        self.assertEqual(resolved.auth_payload, extension_auth)
        self.assertEqual(resolved.auth_status, "verified")
        self.assertNotEqual(resolved.doc_id, plan.doc_id)
        reconstruct_latest_logical_state.assert_called_once()

    def test_resolve_mint_chain_target_rejects_orphan_extension_head(self) -> None:
        root_auth = AuthPayload(
            version=1,
            doc_hash=b"\x11" * 32,
            sign_pub=b"\x22" * 32,
            signature=b"\x33" * 64,
        )
        plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 16,
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

        with mock.patch(
            "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
            return_value=decoded,
        ):
            with self.assertRaisesRegex(ValueError, "extension index sequence is invalid"):
                _resolve_mint_chain_target(plan, quiet=True, debug=False)

    def test_resolve_mint_chain_target_rejects_degraded_latest_head(self) -> None:
        root_auth = AuthPayload(
            version=1,
            doc_hash=b"\x11" * 32,
            sign_pub=b"\x22" * 32,
            signature=b"\x33" * 64,
        )
        plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 16,
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

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
                side_effect=ValueError("missing extension AUTH"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._mint_document_targets_current_root",
                return_value=True,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "could not be trusted"):
                _resolve_mint_chain_target(plan, quiet=True, debug=False)

    def test_resolve_mint_chain_target_rejects_extension_head_that_cannot_replay(self) -> None:
        root_auth = AuthPayload(
            version=1,
            doc_hash=b"\x11" * 32,
            sign_pub=b"\x22" * 32,
            signature=b"\x33" * 64,
        )
        extension_auth = AuthPayload(
            version=1,
            doc_hash=b"\x44" * 32,
            sign_pub=b"\x22" * 32,
            signature=b"\x55" * 64,
        )
        plan = RecoveryPlan(
            ciphertext=b"root-ciphertext",
            doc_id=b"\x66" * 16,
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

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_imported_extension_link",
                return_value=decoded,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.decode_root_manifest",
                return_value=(SimpleNamespace(), b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.reconstruct_latest_logical_state",
                side_effect=ValueError("extension file references unresolved chunk_id"),
            ),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "imported extension chain could not be trusted: .*unresolved chunk_id",
            ):
                _resolve_mint_chain_target(plan, quiet=True, debug=False)


if __name__ == "__main__":
    unittest.main()
