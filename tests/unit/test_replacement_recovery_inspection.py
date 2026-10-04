# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from ethernity.crypto.sharding import KEY_TYPE_PASSPHRASE
from ethernity.crypto.signing import AuthPayload, derive_public_key, sign_auth
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.extensions.recovery import ValidatedRecoveryHead
from ethernity.workflows.recovery.planning import (
    RecoveryInspection,
    RecoveryPlan,
    RecoveryUnlockStatus,
)
from ethernity.workflows.replacement_recovery.service import (
    _recover_replacement_chain,
    execute_replacement_recovery_operation,
    inspect_replacement_recovery_inputs,
)
from ethernity.workflows.shared import api_codes
from ethernity.workflows.shared.events import CommandError as ApiCommandError
from ethernity.workflows.shared.operation_types import ReplacementRecoveryOperationRequest

ROOT_SIGNING_SEED = b"\x33" * 32
ROOT_SIGN_PUB = derive_public_key(ROOT_SIGNING_SEED)


def _root_auth(doc_hash: bytes = b"\x77" * 32) -> AuthPayload:
    return AuthPayload(
        version=1,
        doc_hash=doc_hash,
        sign_pub=ROOT_SIGN_PUB,
        signature=sign_auth(doc_hash, sign_pub=ROOT_SIGN_PUB, sign_priv=ROOT_SIGNING_SEED),
    )


def _state(*, shard_frames: tuple[Frame, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(),
        recover_args=SimpleNamespace(),
        frames=(),
        extra_auth_frames=(),
        shard_frames=shard_frames,
        shard_fallback_files=(),
        shard_payloads_file=(),
        shard_scan=(),
        signing_key_frames=(),
        input_label="Scan",
        input_detail="/tmp/root",
    )


def _recovery(
    *,
    auth_payload: AuthPayload | None = None,
    satisfied: bool = True,
    passphrase: str | None = "passphrase",
) -> RecoveryInspection:
    return RecoveryInspection(
        ciphertext=b"root-ciphertext",
        doc_id=b"\x66" * 8,
        doc_hash=b"\x77" * 32,
        auth_payload=auth_payload,
        auth_status="verified" if auth_payload is not None else "missing",
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
            mode="passphrase" if passphrase is not None else "missing",
            passphrase_provided=passphrase is not None,
            validated_shard_count=0,
            required_shard_threshold=None,
            satisfied=satisfied,
            resolved_passphrase=passphrase if satisfied else None,
        ),
        blocking_issues=(),
    )


def _plan(
    *,
    import_documents: tuple[object, ...] = (),
    expected_head_doc_hash: str | None = None,
) -> RecoveryPlan:
    return RecoveryPlan(
        ciphertext=b"root-ciphertext",
        doc_id=b"\x66" * 8,
        doc_hash=b"\x77" * 32,
        passphrase="passphrase",
        auth_payload=_root_auth(),
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
        expected_head_doc_hash=expected_head_doc_hash,
        import_documents=import_documents,
    )


def _manifest() -> SimpleNamespace:
    return SimpleNamespace(
        format_version=1,
        input_origin="file",
        input_roots=(),
        sealed=False,
        signing_seed=ROOT_SIGNING_SEED,
        payload_codec="raw",
        payload_raw_len=0,
        files=(),
    )


def _chain(*, extension: bool = True) -> SimpleNamespace:
    doc_hash = b"\x44" * 32 if extension else b"\x77" * 32
    return SimpleNamespace(
        manifest=_manifest(),
        head=ValidatedRecoveryHead(
            doc_id=b"\x88" * 8 if extension else b"\x66" * 8,
            doc_hash=doc_hash,
            ciphertext=b"extension-ciphertext" if extension else b"root-ciphertext",
            auth_payload=_root_auth(doc_hash),
            auth_status="verified",
            extension_index=1 if extension else None,
        ),
        selected_extension_index=1 if extension else None,
        selected_extension_doc_hash=doc_hash.hex() if extension else None,
    )


class TestReplacementRecoveryInspection(unittest.TestCase):
    def test_inspection_deduplicates_auth_required_blockers(self) -> None:
        args = ReplacementRecoveryOperationRequest(payloads_file="main.txt", quiet=True)
        auth_required = {
            "code": "AUTH_REQUIRED",
            "message": (
                "replacement recovery requires an authenticated backup input with an AUTH payload"
            ),
            "details": {},
        }
        with (
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._load_replacement_input_state",
                return_value=_state(),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service.inspect_recovery_inputs",
                return_value=_recovery(auth_payload=None, satisfied=False, passphrase=None),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service."
                "_inspect_replacement_signing_key_state",
                return_value=(0, None, False, "signing-key shards", [auth_required]),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service."
                "_inspect_replacement_replacement_blockers",
                return_value=[],
            ),
        ):
            inspection = inspect_replacement_recovery_inputs(args)

        issues = [item for item in inspection.blocking_issues if item["code"] == "AUTH_REQUIRED"]
        self.assertEqual(len(issues), 1)

    def test_inspection_uses_root_binding_after_validating_selected_chain_head(self) -> None:
        args = ReplacementRecoveryOperationRequest(
            scan=["/tmp/root"], passphrase="passphrase", quiet=True
        )
        root_plan = _plan(import_documents=(object(), object()))
        chain = _chain()
        captured: dict[str, RecoveryInspection] = {}

        def capture_blockers(**kwargs):
            captured["recovery"] = kwargs["recovery"]
            return []

        with (
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._load_replacement_input_state",
                return_value=_state(),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service."
                "_try_build_replacement_recovery_plan",
                return_value=root_plan,
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service.inspect_recovery_inputs",
                return_value=_recovery(auth_payload=_root_auth()),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._recover_replacement_chain",
                return_value=chain,
            ) as recover_chain,
            mock.patch(
                "ethernity.workflows.replacement_recovery.service."
                "_inspect_replacement_signing_key_state",
                return_value=(0, None, True, "embedded signing seed", []),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service."
                "_inspect_replacement_replacement_blockers",
                side_effect=capture_blockers,
            ),
        ):
            inspection = inspect_replacement_recovery_inputs(args)

        self.assertEqual(inspection.recovery.doc_hash, root_plan.doc_hash)
        self.assertEqual(inspection.recovery.auth_payload, root_plan.auth_payload)
        self.assertEqual(inspection.selected_extension_index, 1)
        self.assertEqual(inspection.selected_extension_doc_hash, "44" * 32)
        self.assertEqual(captured["recovery"].doc_hash, root_plan.doc_hash)
        recover_chain.assert_called_once_with(root_plan, debug=False, allow_stale_head=False)

    def test_chain_failure_does_not_add_misleading_unlock_failure(self) -> None:
        args = ReplacementRecoveryOperationRequest(
            scan=["/tmp/root"], passphrase="passphrase", quiet=True
        )
        with (
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._load_replacement_input_state",
                return_value=_state(),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service."
                "_try_build_replacement_recovery_plan",
                return_value=_plan(import_documents=(object(), object())),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service.inspect_recovery_inputs",
                return_value=_recovery(auth_payload=_root_auth()),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._recover_replacement_chain",
                side_effect=ValueError("imported extension chain could not be trusted"),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service."
                "_inspect_replacement_signing_key_state",
                return_value=(0, None, False, "signing-key shards", []),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service."
                "_inspect_replacement_replacement_blockers",
                return_value=[],
            ),
        ):
            inspection = inspect_replacement_recovery_inputs(args)

        codes = [item["code"] for item in inspection.blocking_issues]
        self.assertIn(api_codes.RECOVERY_HEAD_UNTRUSTED, codes)
        self.assertNotIn("UNLOCK_FAILED", codes)
        self.assertIsNone(inspection.manifest)

    def test_inspection_preserves_plan_shard_unlock(self) -> None:
        args = ReplacementRecoveryOperationRequest(scan=["/tmp/root"], quiet=True)
        shard_frame = Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x66" * 8,
            index=1,
            total=1,
            data=b"shard",
        )
        plan = _plan()
        plan = plan.__class__(
            **{
                **plan.__dict__,
                "passphrase": "derived-passphrase",
                "shard_frames": (shard_frame,),
                "shard_fallback_files": ("shard.txt",),
                "shard_payloads_file": ("payloads.txt",),
            }
        )
        with (
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._load_replacement_input_state",
                return_value=_state(shard_frames=(shard_frame,)),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service."
                "_try_build_replacement_recovery_plan",
                return_value=plan,
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service.inspect_recovery_inputs",
                return_value=_recovery(auth_payload=_root_auth(), satisfied=False),
            ) as inspect_recovery,
            mock.patch(
                "ethernity.workflows.replacement_recovery.service.decode_shard_payload",
                return_value=SimpleNamespace(
                    key_type=KEY_TYPE_PASSPHRASE,
                    threshold=2,
                    share_count=3,
                    share_index=1,
                ),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._recover_replacement_chain",
                return_value=_chain(extension=False),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service."
                "_inspect_replacement_signing_key_state",
                return_value=(0, None, True, "embedded signing seed", []),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service."
                "_inspect_replacement_replacement_blockers",
                return_value=[],
            ),
        ):
            inspection = inspect_replacement_recovery_inputs(args)

        self.assertEqual(inspect_recovery.call_args.kwargs["passphrase"], "derived-passphrase")
        self.assertEqual(inspection.recovery.unlock.mode, "shards")
        self.assertEqual(inspection.recovery.unlock.required_shard_threshold, 2)
        self.assertEqual(inspection.recovery.unlock.resolved_passphrase, "derived-passphrase")

    def test_execute_passes_selected_head_without_root_directory(self) -> None:
        args = ReplacementRecoveryOperationRequest(
            scan=["/tmp/root"],
            extension_index=0,
            expected_head_doc_hash="ab" * 32,
            quiet=True,
        )
        captured: dict[str, object] = {}

        def capture_plan(**kwargs):
            captured.update(kwargs)
            raise RuntimeError("stop")

        with (
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._load_replacement_input_state",
                return_value=_state(),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service.build_recovery_plan",
                side_effect=capture_plan,
            ),
            self.assertRaisesRegex(RuntimeError, "stop"),
        ):
            execute_replacement_recovery_operation(args)

        self.assertNotIn("root_dir", captured)
        self.assertEqual(captured["extension_index"], 0)
        self.assertEqual(captured["expected_head_doc_hash"], "ab" * 32)

    def test_execute_missing_auth_raises_stable_api_code(self) -> None:
        args = ReplacementRecoveryOperationRequest(payloads_file="main.txt", quiet=True)
        with (
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._load_replacement_input_state",
                return_value=_state(),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._build_replacement_recovery_plan",
                return_value=SimpleNamespace(auth_payload=None),
            ),
            self.assertRaises(ApiCommandError) as caught,
        ):
            execute_replacement_recovery_operation(args)

        self.assertEqual(caught.exception.code, api_codes.AUTH_REQUIRED)

    def test_replacement_chain_delegates_to_shared_recovery_service(self) -> None:
        plan = _plan(import_documents=(object(), object()))
        chain = _chain()
        with mock.patch(
            "ethernity.workflows.replacement_recovery.service.recover_chain_entries",
            return_value=chain,
        ) as recover:
            actual = _recover_replacement_chain(plan, debug=True, allow_stale_head=True)

        self.assertIs(actual, chain)
        recover.assert_called_once_with(plan, debug=True)

    def test_replacement_requires_stale_head_acknowledgement(self) -> None:
        plan = _plan(import_documents=(object(), object()))
        with (
            mock.patch(
                "ethernity.workflows.replacement_recovery.service.recover_chain_entries",
                return_value=_chain(),
            ),
            self.assertRaises(ApiCommandError) as caught,
        ):
            _recover_replacement_chain(plan, debug=False)

        self.assertEqual(caught.exception.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(caught.exception.details["validated_head_index"], 1)


if __name__ == "__main__":
    unittest.main()
