from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from ethernity.workflows.replacement_recovery import service as replacement_service
from ethernity.workflows.shared import api_codes
from ethernity.workflows.shared.events import CommandError as ApiCommandError
from ethernity.workflows.shared.operation_types import ReplacementRecoveryOperationRequest


def _chain_for_plan(plan: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        manifest=SimpleNamespace(signing_seed=b"s" * 32),
        head=SimpleNamespace(
            doc_id=plan.doc_id,
            doc_hash=plan.doc_hash,
            auth_payload=plan.auth_payload,
        ),
        selected_extension_index=None,
        selected_extension_doc_hash=None,
    )


class TestReplacementRecoveryService(unittest.TestCase):
    def _mock_replacement_output_dir(
        self,
        ensure_replacement_output_dir: mock.MagicMock,
        tmpdir: str,
    ) -> Path:
        output_dir = Path(tmpdir) / "replacement"
        ensure_replacement_output_dir.return_value = str(output_dir)
        return output_dir

    def test_validate_replacement_args_requires_output_selection(self) -> None:
        args = ReplacementRecoveryOperationRequest(
            payloads_file="qr.txt",
            passphrase="passphrase",
            create_passphrase_shards=False,
            create_signing_key_shards=False,
        )

        with self.assertRaisesRegex(ValueError, "at least one shard document type"):
            replacement_service._validate_replacement_args(args)

    def test_output_preflight_rejects_dangling_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "replacement"
            try:
                output_dir.symlink_to(Path(tmpdir) / "missing", target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "output directory already exists"):
                replacement_service.require_replacement_recovery_output_available(output_dir)

    def test_validate_replacement_args_replacement_requires_matching_inputs(self) -> None:
        args = ReplacementRecoveryOperationRequest(
            payloads_file="qr.txt",
            passphrase="passphrase",
            passphrase_replacement_count=1,
            create_signing_key_shards=False,
        )

        with self.assertRaisesRegex(ValueError, "existing passphrase shard inputs"):
            replacement_service._validate_replacement_args(args)

    def test_validate_replacement_args_accepts_scan_only_passphrase_replacement_inputs(
        self,
    ) -> None:
        args = ReplacementRecoveryOperationRequest(
            payloads_file="qr.txt",
            passphrase="passphrase",
            shard_scan=["old-passphrase-shard.pdf"],
            passphrase_replacement_count=1,
            create_signing_key_shards=False,
        )

        replacement_service._validate_replacement_args(args)

    @mock.patch(
        "ethernity.workflows.replacement_recovery.service.validated_shard_payloads_from_frames",
        side_effect=replacement_service.InsufficientShardError(
            threshold=2,
            provided_count=1,
            secret_label="passphrase",
            shard_version=1,
        ),
    )
    def test_replacement_payload_resolution_preserves_legacy_version_under_quorum(
        self,
        _validated_shard_payloads_from_frames: mock.MagicMock,
    ) -> None:
        resolution = replacement_service._replacement_payloads_from_frames(
            [mock.Mock()],
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            sign_pub=b"p" * 32,
            key_type="passphrase",
            secret_label="passphrase",
        )

        self.assertTrue(resolution.under_quorum)
        self.assertTrue(resolution.uses_legacy_shards)

    def test_require_replacement_payloads_adds_legacy_hint_for_under_quorum_inputs(
        self,
    ) -> None:
        resolution = replacement_service._ReplacementShardResolution(
            provided_count=1,
            threshold=2,
            shard_version=1,
        )

        with self.assertRaisesRegex(ValueError, "legacy v1"):
            replacement_service._require_replacement_payloads(
                resolution,
                secret_label="passphrase",
            )

    def test_raise_if_under_quorum_replacement_inputs_adds_legacy_hint(self) -> None:
        resolution = replacement_service._ReplacementShardResolution(
            provided_count=1,
            threshold=2,
            shard_version=1,
        )

        with self.assertRaisesRegex(ValueError, "legacy v1"):
            replacement_service._raise_if_under_quorum_replacement_inputs(
                resolution,
                secret_label="passphrase",
            )

    @mock.patch(
        "ethernity.workflows.replacement_recovery.service._replacement_payloads_from_frames",
        side_effect=[
            replacement_service._ReplacementShardResolution(provided_count=1, threshold=2),
            replacement_service._ReplacementShardResolution(),
        ],
    )
    @mock.patch("ethernity.workflows.replacement_recovery.service._ensure_replacement_output_dir")
    @mock.patch("ethernity.workflows.replacement_recovery.service.RenderService")
    @mock.patch(
        "ethernity.workflows.replacement_recovery.service.derive_public_key", return_value=b"p" * 32
    )
    def test_replacement_from_plan_rejects_under_quorum_replacement_request(
        self,
        _derive_public_key: mock.MagicMock,
        _render_service: mock.MagicMock,
        ensure_replacement_output_dir: mock.MagicMock,
        _replacement_payloads_from_frames: mock.MagicMock,
    ) -> None:
        args = ReplacementRecoveryOperationRequest(
            passphrase_replacement_count=1,
            create_signing_key_shards=False,
            quiet=True,
        )
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="replacement-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        )
        config = SimpleNamespace(
            cli_defaults=SimpleNamespace(backup=SimpleNamespace(qr_payload_codec="raw"))
        )

        with (
            mock.patch.object(
                replacement_service,
                "_recover_replacement_chain",
                return_value=_chain_for_plan(plan),
            ),
            self.assertRaisesRegex(
                ValueError,
                r"need at least 2 validated shard\(s\), got 1",
            ),
        ):
            replacement_service._replacement_from_plan(
                plan=plan,
                config=config,
                args=args,
                passphrase_shard_frames=[mock.Mock()],
                signing_key_frames=[],
                manifest_signing_seed=b"s" * 32,
                debug=False,
            )
        ensure_replacement_output_dir.assert_not_called()

    @mock.patch(
        "ethernity.workflows.replacement_recovery.service._replacement_payloads_from_frames",
        side_effect=[
            replacement_service._ReplacementShardResolution(
                payloads=(cast(Any, SimpleNamespace(version=1)),),
                shard_version=1,
            ),
            replacement_service._ReplacementShardResolution(),
        ],
    )
    @mock.patch("ethernity.workflows.replacement_recovery.service._ensure_replacement_output_dir")
    @mock.patch("ethernity.workflows.replacement_recovery.service.RenderService")
    @mock.patch(
        "ethernity.workflows.replacement_recovery.service.create_replacement_shards",
        return_value=[],
    )
    @mock.patch(
        "ethernity.workflows.replacement_recovery.service.derive_public_key", return_value=b"p" * 32
    )
    def test_replacement_from_plan_adds_legacy_replacement_note(
        self,
        _derive_public_key: mock.MagicMock,
        _replacement_replacement_shards: mock.MagicMock,
        _render_service: mock.MagicMock,
        ensure_replacement_output_dir: mock.MagicMock,
        _replacement_payloads_from_frames: mock.MagicMock,
    ) -> None:
        args = ReplacementRecoveryOperationRequest(
            passphrase_replacement_count=1,
            create_signing_key_shards=False,
            quiet=True,
        )
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="replacement-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        )
        config = SimpleNamespace(
            design_name="sentinel",
            cli_defaults=SimpleNamespace(backup=SimpleNamespace(qr_payload_codec="raw")),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            self._mock_replacement_output_dir(ensure_replacement_output_dir, tmpdir)
            with mock.patch.object(
                replacement_service,
                "_recover_replacement_chain",
                return_value=_chain_for_plan(plan),
            ):
                result = replacement_service._replacement_from_plan(
                    plan=plan,
                    config=config,
                    args=args,
                    passphrase_shard_frames=[mock.Mock()],
                    signing_key_frames=[],
                    manifest_signing_seed=b"s" * 32,
                    debug=False,
                )

        self.assertEqual(len(result.notes), 1)
        self.assertIn("Legacy v1 passphrase shards detected", result.notes[0])

    def test_legacy_replacement_notes_only_apply_to_replacement_requests(self) -> None:
        notes = replacement_service._legacy_replacement_notes(
            passphrase_resolution=replacement_service._ReplacementShardResolution(shard_version=1),
            signing_resolution=replacement_service._ReplacementShardResolution(shard_version=1),
            args=ReplacementRecoveryOperationRequest(),
        )

        self.assertEqual(notes, ())

    @mock.patch(
        "ethernity.workflows.replacement_recovery.service._replacement_payloads_from_frames"
    )
    @mock.patch("ethernity.workflows.replacement_recovery.service._ensure_replacement_output_dir")
    @mock.patch("ethernity.workflows.replacement_recovery.service.RenderService")
    @mock.patch(
        "ethernity.workflows.replacement_recovery.service.split_passphrase", return_value=[]
    )
    @mock.patch(
        "ethernity.workflows.replacement_recovery.service.derive_public_key", return_value=b"p" * 32
    )
    def test_replacement_from_plan_skips_unused_shard_validation_for_fresh_replacement(
        self,
        _derive_public_key: mock.MagicMock,
        _split_passphrase: mock.MagicMock,
        _render_service: mock.MagicMock,
        ensure_replacement_output_dir: mock.MagicMock,
        replacement_payloads_from_frames: mock.MagicMock,
    ) -> None:
        args = ReplacementRecoveryOperationRequest(
            shard_threshold=2,
            shard_count=2,
            create_signing_key_shards=False,
            quiet=True,
        )
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="replacement-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        )
        config = SimpleNamespace(
            cli_defaults=SimpleNamespace(backup=SimpleNamespace(qr_payload_codec="raw"))
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            self._mock_replacement_output_dir(ensure_replacement_output_dir, tmpdir)
            with mock.patch.object(
                replacement_service,
                "_recover_replacement_chain",
                return_value=_chain_for_plan(plan),
            ):
                result = replacement_service._replacement_from_plan(
                    plan=plan,
                    config=config,
                    args=args,
                    passphrase_shard_frames=[mock.Mock(name="unused-passphrase-frame")],
                    signing_key_frames=[mock.Mock(name="unused-signing-frame")],
                    manifest_signing_seed=b"s" * 32,
                    debug=False,
                )

        self.assertEqual(result.notes, ())
        replacement_payloads_from_frames.assert_not_called()

    @mock.patch(
        "ethernity.workflows.replacement_recovery.service.signing_seed_from_shard_frames",
        return_value=b"s" * 32,
    )
    def test_recover_signing_seed_uses_signing_key_shards_when_sealed(
        self,
        signing_seed_from_frames: mock.MagicMock,
    ) -> None:
        seed, source = replacement_service._recover_signing_seed(
            manifest_signing_seed=None,
            signing_key_frames=[mock.Mock()],
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            expected_sign_pub=b"p" * 32,
        )

        self.assertEqual(seed, b"s" * 32)
        self.assertEqual(source, "signing-key shards")
        signing_seed_from_frames.assert_called_once()

    def test_recover_signing_seed_requires_shards_with_stable_api_code(self) -> None:
        with self.assertRaises(ApiCommandError) as caught:
            replacement_service._recover_signing_seed(
                manifest_signing_seed=None,
                signing_key_frames=[],
                doc_id=b"d" * 16,
                doc_hash=b"h" * 32,
                expected_sign_pub=b"p" * 32,
            )

        self.assertEqual(caught.exception.code, api_codes.SIGNING_KEY_SHARDS_REQUIRED)


if __name__ == "__main__":
    unittest.main()
