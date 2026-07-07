from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from ethernity.cli.features.mint import workflow as mint_flow
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import MintArgs


class TestMintWorkflow(unittest.TestCase):
    def _mock_mint_output_dir(
        self,
        ensure_mint_output_dir: mock.MagicMock,
        tmpdir: str,
    ) -> Path:
        output_dir = Path(tmpdir) / "minted"
        ensure_mint_output_dir.return_value = str(output_dir)
        return output_dir

    def test_validate_mint_args_requires_output_selection(self) -> None:
        args = MintArgs(
            payloads_file="qr.txt",
            passphrase="passphrase",
            mint_passphrase_shards=False,
            mint_signing_key_shards=False,
        )

        with self.assertRaisesRegex(ValueError, "at least one shard document type"):
            mint_flow._validate_mint_args(args)

    def test_validate_mint_args_replacement_requires_matching_inputs(self) -> None:
        args = MintArgs(
            payloads_file="qr.txt",
            passphrase="passphrase",
            passphrase_replacement_count=1,
            mint_signing_key_shards=False,
        )

        with self.assertRaisesRegex(ValueError, "existing passphrase shard inputs"):
            mint_flow._validate_mint_args(args)

    def test_validate_mint_args_accepts_scan_only_passphrase_replacement_inputs(self) -> None:
        args = MintArgs(
            payloads_file="qr.txt",
            passphrase="passphrase",
            shard_scan=["old-passphrase-shard.pdf"],
            passphrase_replacement_count=1,
            mint_signing_key_shards=False,
        )

        mint_flow._validate_mint_args(args)

    @mock.patch(
        "ethernity.cli.features.mint.workflow.validated_shard_payloads_from_frames",
        side_effect=mint_flow.InsufficientShardError(
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
        resolution = mint_flow._replacement_payloads_from_frames(
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
        resolution = mint_flow._ReplacementShardResolution(
            provided_count=1,
            threshold=2,
            shard_version=1,
        )

        with self.assertRaisesRegex(ValueError, "legacy v1"):
            mint_flow._require_replacement_payloads(
                resolution,
                secret_label="passphrase",
            )

    def test_raise_if_under_quorum_replacement_inputs_adds_legacy_hint(self) -> None:
        resolution = mint_flow._ReplacementShardResolution(
            provided_count=1,
            threshold=2,
            shard_version=1,
        )

        with self.assertRaisesRegex(ValueError, "legacy v1"):
            mint_flow._raise_if_under_quorum_replacement_inputs(
                resolution,
                secret_label="passphrase",
            )

    @mock.patch(
        "ethernity.cli.features.mint.workflow._replacement_payloads_from_frames",
        side_effect=[
            mint_flow._ReplacementShardResolution(provided_count=1, threshold=2),
            mint_flow._ReplacementShardResolution(),
        ],
    )
    @mock.patch("ethernity.cli.features.mint.workflow._ensure_mint_output_dir")
    @mock.patch("ethernity.cli.features.mint.workflow.RenderService")
    @mock.patch("ethernity.cli.features.mint.workflow.derive_public_key", return_value=b"p" * 32)
    def test_mint_from_plan_rejects_under_quorum_replacement_request(
        self,
        _derive_public_key: mock.MagicMock,
        _render_service: mock.MagicMock,
        ensure_mint_output_dir: mock.MagicMock,
        _replacement_payloads_from_frames: mock.MagicMock,
    ) -> None:
        args = MintArgs(
            passphrase_replacement_count=1,
            mint_signing_key_shards=False,
            quiet=True,
        )
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        )
        config = SimpleNamespace(
            cli_defaults=SimpleNamespace(backup=SimpleNamespace(qr_payload_codec="raw"))
        )

        with self.assertRaisesRegex(
            ValueError,
            r"need at least 2 validated shard\(s\), got 1",
        ):
            mint_flow._mint_from_plan(
                plan=plan,
                config=config,
                args=args,
                passphrase_shard_frames=[mock.Mock()],
                signing_key_frames=[],
                manifest_signing_seed=b"s" * 32,
                debug=False,
            )
        ensure_mint_output_dir.assert_not_called()

    @mock.patch(
        "ethernity.cli.features.mint.workflow._replacement_payloads_from_frames",
        side_effect=[
            mint_flow._ReplacementShardResolution(
                payloads=(cast(Any, SimpleNamespace(version=1)),),
                shard_version=1,
            ),
            mint_flow._ReplacementShardResolution(),
        ],
    )
    @mock.patch("ethernity.cli.features.mint.workflow._ensure_mint_output_dir")
    @mock.patch("ethernity.cli.features.mint.workflow.RenderService")
    @mock.patch("ethernity.cli.features.mint.workflow.mint_replacement_shards", return_value=[])
    @mock.patch("ethernity.cli.features.mint.workflow.derive_public_key", return_value=b"p" * 32)
    def test_mint_from_plan_adds_legacy_replacement_note(
        self,
        _derive_public_key: mock.MagicMock,
        _mint_replacement_shards: mock.MagicMock,
        _render_service: mock.MagicMock,
        ensure_mint_output_dir: mock.MagicMock,
        _replacement_payloads_from_frames: mock.MagicMock,
    ) -> None:
        args = MintArgs(
            passphrase_replacement_count=1,
            mint_signing_key_shards=False,
            quiet=True,
        )
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        )
        config = SimpleNamespace(
            design_name="sentinel",
            cli_defaults=SimpleNamespace(backup=SimpleNamespace(qr_payload_codec="raw")),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            self._mock_mint_output_dir(ensure_mint_output_dir, tmpdir)
            result = mint_flow._mint_from_plan(
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
        notes = mint_flow._legacy_replacement_notes(
            passphrase_resolution=mint_flow._ReplacementShardResolution(shard_version=1),
            signing_resolution=mint_flow._ReplacementShardResolution(shard_version=1),
            args=MintArgs(),
        )

        self.assertEqual(notes, ())

    @mock.patch("ethernity.cli.features.mint.workflow._replacement_payloads_from_frames")
    @mock.patch("ethernity.cli.features.mint.workflow._ensure_mint_output_dir")
    @mock.patch("ethernity.cli.features.mint.workflow.RenderService")
    @mock.patch("ethernity.cli.features.mint.workflow.split_passphrase", return_value=[])
    @mock.patch("ethernity.cli.features.mint.workflow.derive_public_key", return_value=b"p" * 32)
    def test_mint_from_plan_skips_unused_shard_validation_for_fresh_mint(
        self,
        _derive_public_key: mock.MagicMock,
        _split_passphrase: mock.MagicMock,
        _render_service: mock.MagicMock,
        ensure_mint_output_dir: mock.MagicMock,
        replacement_payloads_from_frames: mock.MagicMock,
    ) -> None:
        args = MintArgs(
            shard_threshold=2,
            shard_count=2,
            mint_signing_key_shards=False,
            quiet=True,
        )
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        )
        config = SimpleNamespace(
            cli_defaults=SimpleNamespace(backup=SimpleNamespace(qr_payload_codec="raw"))
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            self._mock_mint_output_dir(ensure_mint_output_dir, tmpdir)
            result = mint_flow._mint_from_plan(
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
        "ethernity.cli.features.mint.workflow.signing_seed_from_shard_frames",
        return_value=b"s" * 32,
    )
    def test_resolve_signing_authority_uses_signing_key_shards_when_sealed(
        self,
        signing_seed_from_frames: mock.MagicMock,
    ) -> None:
        seed, source = mint_flow._resolve_signing_authority(
            manifest_signing_seed=None,
            signing_key_frames=[mock.Mock()],
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            expected_sign_pub=b"p" * 32,
        )

        self.assertEqual(seed, b"s" * 32)
        self.assertEqual(source, "signing authority shards")
        signing_seed_from_frames.assert_called_once()

    def test_resolve_signing_authority_requires_shards_with_stable_api_code(self) -> None:
        with self.assertRaises(ApiCommandError) as caught:
            mint_flow._resolve_signing_authority(
                manifest_signing_seed=None,
                signing_key_frames=[],
                doc_id=b"d" * 16,
                doc_hash=b"h" * 32,
                expected_sign_pub=b"p" * 32,
            )

        self.assertEqual(caught.exception.code, api_codes.SIGNING_KEY_SHARDS_REQUIRED)


if __name__ == "__main__":
    unittest.main()
