# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

from ethernity.crypto.signing import AuthPayload, derive_public_key, sign_auth
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.extensions.errors import ExtensionRecoveryError
from ethernity.extensions.recovery import ValidatedRecoveryHead
from ethernity.workflows.recovery.planning import (
    RecoveryPlan,
    RecoveryUnlockStatus,
)
from ethernity.workflows.recovery.source_state import (
    LoadedRecoveryInputs,
    LoadedRecoverySource,
    RecoverySourceFields,
)
from ethernity.workflows.replacement_recovery.service import (
    _recover_replacement_chain,
    _replacement_from_plan,
    execute_replacement_recovery_operation,
)
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.events import CommandError as ApiCommandError
from ethernity.workflows.shared.requests import RecoveryRequest, ReplacementRecoveryRequest

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
        recover_args=RecoveryRequest(),
        loaded=LoadedRecoveryInputs(
            source=LoadedRecoverySource((), (), (), "Scan", "/tmp/root"),
            shard_frames=shard_frames,
        ),
        signing_key_frames=(),
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
        unlock=RecoveryUnlockStatus(
            mode="passphrase",
            passphrase_provided=True,
            validated_shard_count=0,
            required_shard_threshold=None,
            satisfied=True,
            resolved_passphrase="passphrase",
        ),
        blocking_issues=(),
        auth_payload=_root_auth(),
        auth_status="verified",
        allow_unsigned=False,
        output_path=None,
        expected_head_doc_hash=expected_head_doc_hash,
        loaded_source=LoadedRecoverySource((), (), import_documents, None, None),
        source=RecoverySourceFields(
            input_label="Scan",
            input_detail="/tmp/root",
            main_frames=(),
            auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
        ),
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


class TestReplacementRecoveryPreparation(unittest.TestCase):
    def test_sheets_use_root_binding_after_validating_selected_chain_head(self) -> None:
        plan = _plan(import_documents=(object(), object()))
        args = ReplacementRecoveryRequest(allow_stale_head=True)
        with (
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._recover_replacement_chain",
                return_value=_chain(),
            ) as recover,
            mock.patch(
                "ethernity.workflows.replacement_recovery.service.create_replacement_documents"
            ) as generate,
        ):
            result = _replacement_from_plan(
                plan=plan,
                config=mock.sentinel.config,
                args=args,
                passphrase_shard_frames=[],
                signing_key_frames=[],
                debug=False,
            )
        self.assertIs(result, generate.return_value)
        material = generate.call_args.args[0]
        self.assertEqual(material.trust.doc_id, plan.doc_id)
        self.assertEqual(material.trust.doc_hash, plan.doc_hash)
        self.assertEqual(material.trust.sign_pub, ROOT_SIGN_PUB)
        self.assertEqual(material.signing_seed, ROOT_SIGNING_SEED)
        self.assertEqual(material.selected_extension_index, 1)
        self.assertEqual(material.selected_extension_doc_hash, "44" * 32)
        recover.assert_called_once_with(plan, debug=False, allow_stale_head=True, session=None)

    def test_chain_failure_stops_generation_and_preserves_the_error(self) -> None:
        plan = _plan(import_documents=(object(), object()))
        with (
            mock.patch(
                "ethernity.extensions.recovery.recover_chain_entries",
                side_effect=ExtensionRecoveryError(
                    issue_codes.RECOVERY_HEAD_UNTRUSTED,
                    "imported extension chain could not be trusted",
                ),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service.create_replacement_documents"
            ) as generate,
            self.assertRaises(ApiCommandError) as caught,
        ):
            _replacement_from_plan(
                plan=plan,
                config=mock.sentinel.config,
                args=ReplacementRecoveryRequest(),
                passphrase_shard_frames=[],
                signing_key_frames=[],
                debug=False,
            )
        self.assertEqual(caught.exception.code, issue_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertIn("chain could not be trusted", caught.exception.message)
        generate.assert_not_called()

    def test_execution_preserves_the_passphrase_recovered_from_shards(self) -> None:
        shard_frame = Frame(VERSION, FrameType.KEY_DOCUMENT, b"\x66" * 8, 1, 1, b"shard")
        plan = replace(
            _plan(),
            unlock=RecoveryUnlockStatus(
                mode="shards",
                passphrase_provided=False,
                validated_shard_count=2,
                required_shard_threshold=2,
                satisfied=True,
                resolved_passphrase="derived-passphrase",
                shard_share_count=3,
            ),
        )
        with (
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._load_replacement_input_state",
                return_value=_state(shard_frames=(shard_frame,)),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service.build_recovery_plan",
                return_value=plan,
            ) as build,
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._recover_replacement_chain",
                return_value=_chain(extension=False),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service.create_replacement_documents"
            ) as generate,
        ):
            execute_replacement_recovery_operation(ReplacementRecoveryRequest(quiet=True))
        self.assertEqual(build.call_args.args[0].shard_frames, (shard_frame,))
        self.assertEqual(generate.call_args.args[0].passphrase, "derived-passphrase")
        self.assertEqual(generate.call_args.kwargs["passphrase_shard_frames"], [shard_frame])

    def test_execute_passes_selected_head_without_root_directory(self) -> None:
        args = ReplacementRecoveryRequest(
            scan_paths=["/tmp/root"],
            extension_index=0,
            expected_head_doc_hash="ab" * 32,
            quiet=True,
        )
        captured: dict[str, object] = {}

        def capture_plan(loaded, request, **kwargs):
            captured.update(
                extension_index=request.extension_index,
                expected_head_doc_hash=request.expected_head_doc_hash,
            )
            raise RuntimeError("stop")

        with (
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._load_replacement_input_state",
                return_value=SimpleNamespace(
                    **{
                        **vars(_state()),
                        "recover_args": replace(args.recovery_request(), extension_index=0),
                    }
                ),
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

    def test_execute_missing_auth_raises_issue_code(self) -> None:
        args = ReplacementRecoveryRequest(payloads_file="main.txt", quiet=True)
        with (
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._load_replacement_input_state",
                return_value=_state(),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service._build_replacement_recovery_plan",
                return_value=SimpleNamespace(auth_payload=None),
            ),
            mock.patch(
                "ethernity.workflows.replacement_recovery.service.create_replacement_documents"
            ) as generate,
            self.assertRaises(ApiCommandError) as caught,
        ):
            execute_replacement_recovery_operation(args)

        self.assertEqual(caught.exception.code, issue_codes.AUTH_REQUIRED)
        generate.assert_not_called()

    def test_replacement_chain_delegates_to_shared_recovery_service(self) -> None:
        plan = _plan(import_documents=(object(), object()))
        chain = _chain()
        with mock.patch(
            "ethernity.extensions.recovery.recover_chain_entries",
            return_value=chain,
        ) as recover:
            actual = _recover_replacement_chain(plan, debug=True, allow_stale_head=True)

        self.assertIs(actual, chain)
        recover.assert_called_once_with(plan, debug=True)

    def test_replacement_requires_stale_head_acknowledgement(self) -> None:
        plan = _plan(import_documents=(object(), object()))
        with (
            mock.patch(
                "ethernity.extensions.recovery.recover_chain_entries",
                return_value=_chain(),
            ),
            self.assertRaises(ApiCommandError) as caught,
        ):
            _recover_replacement_chain(plan, debug=False)

        self.assertEqual(caught.exception.code, issue_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(caught.exception.details["validated_head_index"], 1)


if __name__ == "__main__":
    unittest.main()
