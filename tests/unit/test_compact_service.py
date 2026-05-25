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

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ethernity.cli.features.compact.service import (
    _infer_passphrase_shard_policy_from_frames,
    _infer_root_publish_policy,
    run_compact,
)
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import CompactArgs, RecoverArgs
from ethernity.crypto.sharding import encode_shard_payload, split_passphrase, split_signing_seed
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile


def _passphrase_shard_frames(
    passphrase: str,
    *,
    threshold: int,
    share_count: int,
    doc_id: bytes,
    doc_hash: bytes,
    sign_priv: bytes,
) -> tuple[Frame, ...]:
    sign_pub = derive_public_key(sign_priv)
    shards = split_passphrase(
        passphrase,
        threshold=threshold,
        shares=share_count,
        doc_hash=doc_hash,
        sign_priv=sign_priv,
        sign_pub=sign_pub,
    )
    return tuple(
        Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=encode_shard_payload(shard),
        )
        for shard in shards
    )


def _signing_seed_shard_frames(
    seed: bytes,
    *,
    threshold: int,
    share_count: int,
    doc_id: bytes,
    doc_hash: bytes,
    sign_priv: bytes,
) -> tuple[Frame, ...]:
    sign_pub = derive_public_key(sign_priv)
    shards = split_signing_seed(
        seed,
        threshold=threshold,
        shares=share_count,
        doc_hash=doc_hash,
        sign_priv=sign_priv,
        sign_pub=sign_pub,
    )
    return tuple(
        Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=encode_shard_payload(shard),
        )
        for shard in shards
    )


class TestCompactService(unittest.TestCase):
    def test_run_compact_rejects_missing_root_dir_with_compact_specific_message(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "backup root folder \\(backup root directory\\) not found: /tmp/missing-root",
        ):
            run_compact(
                CompactArgs(
                    root_dir="/tmp/missing-root",
                    output_dir="/tmp/out",
                    passphrase="secret",
                    quiet=True,
                )
            )

    def test_run_compact_reports_scan_failure_for_empty_root_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            with self.assertRaisesRegex(
                ValueError,
                "scan failed: no scan files found in directory",
            ):
                run_compact(
                    CompactArgs(
                        root_dir=str(root_dir),
                        output_dir="/tmp/out",
                        passphrase="secret",
                        quiet=True,
                    )
                )

    def test_run_compact_rejects_output_dir_equal_to_root_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            with self.assertRaisesRegex(
                ValueError,
                "compact output directory must not be the source backup root or inside it",
            ):
                run_compact(
                    CompactArgs(
                        root_dir=str(root_dir),
                        output_dir=str(root_dir),
                        passphrase="secret",
                        quiet=True,
                    )
                )

    def test_run_compact_rejects_output_dir_inside_root_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            with self.assertRaisesRegex(
                ValueError,
                "compact output directory must not be the source backup root or inside it",
            ):
                run_compact(
                    CompactArgs(
                        root_dir=str(root_dir),
                        output_dir=str(root_dir / "compacted"),
                        passphrase="secret",
                        quiet=True,
                    )
                )

    def test_infer_root_publish_policy_uses_external_passphrase_shard_frames(self) -> None:
        doc_id = b"\x22" * 8
        doc_hash = b"\x44" * 32
        sign_priv = b"\x33" * 32
        sign_pub = derive_public_key(sign_priv)
        shard_frames = _passphrase_shard_frames(
            "secret passphrase",
            threshold=2,
            share_count=3,
            doc_id=doc_id,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
        )[:2]
        with tempfile.TemporaryDirectory() as tmpdir:
            policy = _infer_root_publish_policy(
                root_dir=tmpdir,
                root_doc_id_hex=doc_id.hex(),
                root_doc_hash=doc_hash,
                sign_pub=sign_pub,
                passphrase_shard_frames=shard_frames,
                quiet=True,
            )

        self.assertEqual(policy.passphrase_shard_threshold, 2)
        self.assertEqual(policy.passphrase_shard_count, 3)
        self.assertIsNone(policy.signing_key_shard_threshold)
        self.assertEqual(policy.signing_key_shard_count, 0)

    def test_infer_root_publish_policy_scans_renamed_root_level_shard_content(self) -> None:
        doc_id = b"\x22" * 8
        doc_hash = b"\x44" * 32
        sign_priv = b"\x33" * 32
        sign_pub = derive_public_key(sign_priv)
        shard_frames = _passphrase_shard_frames(
            "secret passphrase",
            threshold=2,
            share_count=3,
            doc_id=doc_id,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
        )[:2]
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            renamed = root_dir / "renamed-root-policy.pdf"
            renamed.write_bytes(b"not really a pdf; scanner is mocked")
            with mock.patch(
                "ethernity.cli.shared.root_shard_policy.frames_from_scan",
                return_value=list(shard_frames),
            ) as frames_from_scan:
                policy = _infer_root_publish_policy(
                    root_dir=str(root_dir),
                    root_doc_id_hex=doc_id.hex(),
                    root_doc_hash=doc_hash,
                    sign_pub=sign_pub,
                    quiet=True,
                )

        frames_from_scan.assert_called_once_with([str(renamed)])
        self.assertEqual(policy.passphrase_shard_threshold, 2)
        self.assertEqual(policy.passphrase_shard_count, 3)

    def test_infer_root_publish_policy_classifies_signing_key_shards_by_payload(self) -> None:
        doc_id = b"\x22" * 8
        doc_hash = b"\x44" * 32
        sign_priv = b"\x33" * 32
        sign_pub = derive_public_key(sign_priv)
        shard_frames = _signing_seed_shard_frames(
            b"\x55" * 32,
            threshold=2,
            share_count=4,
            doc_id=doc_id,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
        )[:2]
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            renamed = root_dir / "not-a-signing-key-name.pdf"
            renamed.write_bytes(b"scanner is mocked")
            with mock.patch(
                "ethernity.cli.shared.root_shard_policy.frames_from_scan",
                return_value=list(shard_frames),
            ):
                policy = _infer_root_publish_policy(
                    root_dir=str(root_dir),
                    root_doc_id_hex=doc_id.hex(),
                    root_doc_hash=doc_hash,
                    sign_pub=sign_pub,
                    quiet=True,
                )

        self.assertIsNone(policy.passphrase_shard_threshold)
        self.assertEqual(policy.passphrase_shard_count, 0)
        self.assertEqual(policy.signing_key_shard_threshold, 2)
        self.assertEqual(policy.signing_key_shard_count, 4)

    def test_infer_root_publish_policy_ignores_extension_directory_shards(self) -> None:
        doc_id = b"\x22" * 8
        doc_hash = b"\x44" * 32
        sign_pub = derive_public_key(b"\x33" * 32)
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            extension_dir = root_dir / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (extension_dir / "renamed-extension-shard.pdf").write_bytes(b"scanner must not run")
            with mock.patch(
                "ethernity.cli.shared.root_shard_policy.frames_from_scan",
                side_effect=AssertionError("extension shards must not be scanned"),
            ):
                policy = _infer_root_publish_policy(
                    root_dir=str(root_dir),
                    root_doc_id_hex=doc_id.hex(),
                    root_doc_hash=doc_hash,
                    sign_pub=sign_pub,
                    quiet=True,
                )

        self.assertIsNone(policy.passphrase_shard_threshold)
        self.assertEqual(policy.passphrase_shard_count, 0)
        self.assertIsNone(policy.signing_key_shard_threshold)
        self.assertEqual(policy.signing_key_shard_count, 0)

    def test_infer_root_publish_policy_rejects_shards_without_trusted_authority(self) -> None:
        doc_id = b"\x22" * 8
        doc_hash = b"\x44" * 32
        shard_frames = _passphrase_shard_frames(
            "secret passphrase",
            threshold=2,
            share_count=3,
            doc_id=doc_id,
            doc_hash=doc_hash,
            sign_priv=b"\x33" * 32,
        )[:2]

        with self.assertRaises(ApiCommandError) as ctx:
            _infer_root_publish_policy(
                root_dir="/tmp/root",
                root_doc_id_hex=doc_id.hex(),
                root_doc_hash=doc_hash,
                sign_pub=None,
                passphrase_shard_frames=shard_frames,
                quiet=True,
            )

        self.assertEqual(ctx.exception.code, api_codes.COMPACT_INVALID_POLICY)
        self.assertEqual(ctx.exception.details, {"stage": "root_shard_policy"})

    def test_infer_source_shard_policy_rejects_shards_without_trusted_authority(self) -> None:
        shard_frames = _passphrase_shard_frames(
            "secret passphrase",
            threshold=2,
            share_count=3,
            doc_id=b"\x22" * 8,
            doc_hash=b"\x44" * 32,
            sign_priv=b"\x33" * 32,
        )[:2]

        with self.assertRaises(ApiCommandError) as ctx:
            _infer_passphrase_shard_policy_from_frames(shard_frames, sign_pub=None)

        self.assertEqual(ctx.exception.code, api_codes.COMPACT_INVALID_POLICY)
        self.assertEqual(ctx.exception.details, {"stage": "source_shard_policy"})

    def test_run_compact_preserves_external_unlock_shard_policy(self) -> None:
        doc_id = b"\x22" * 8
        doc_hash = b"\x44" * 32
        sign_priv = b"\x33" * 32
        sign_pub = derive_public_key(sign_priv)
        shard_frames = _passphrase_shard_frames(
            "secret passphrase",
            threshold=2,
            share_count=3,
            doc_id=doc_id,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
        )[:2]
        chain = SimpleNamespace(
            manifest=EnvelopeManifest(
                format_version=1,
                created_at=1,
                sealed=True,
                signing_seed=None,
                files=(ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1),),
                input_origin="file",
                input_roots=(),
            ),
            extracted=(
                (ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1), b"data"),
            ),
        )
        recover_plan = SimpleNamespace(
            passphrase="secret passphrase",
            doc_id=doc_id,
            doc_hash=doc_hash,
            auth_payload=SimpleNamespace(sign_pub=sign_pub),
            shard_frames=shard_frames,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()
            output_dir = Path(tmpdir) / "compacted"
            with (
                mock.patch(
                    "ethernity.cli.features.compact.service.plan_recover_from_args",
                    return_value=recover_plan,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.recover_chain_entries",
                    return_value=chain,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.load_app_config",
                    return_value=SimpleNamespace(),
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.apply_template_design",
                    side_effect=lambda config, _design: config,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.apply_qr_chunk_size_override",
                    side_effect=lambda config, _size: config,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.plan_backup_from_args",
                    return_value=SimpleNamespace(
                        sealed=True,
                        sharding=None,
                        signing_seed_mode="embedded",
                        signing_seed_sharding=None,
                    ),
                ) as plan_backup_from_args,
                mock.patch(
                    "ethernity.cli.features.compact.service.run_backup",
                    return_value="backup-result",
                ),
            ):
                result = run_compact(
                    CompactArgs(
                        root_dir=str(root_dir),
                        output_dir=str(output_dir),
                        shard_scan=["/separate/shard-a.pdf", "/separate/shard-b.pdf"],
                        quiet=True,
                    )
                )

        self.assertEqual(result, "backup-result")
        backup_args = plan_backup_from_args.call_args.args[0]
        self.assertEqual(backup_args.shard_threshold, 2)
        self.assertEqual(backup_args.shard_count, 3)
        self.assertTrue(backup_args.sealed)

    def test_run_compact_preserves_extension_local_unlock_shard_policy(self) -> None:
        root_doc_id = b"\x22" * 8
        root_doc_hash = b"\x44" * 32
        extension_doc_id = b"\x55" * 8
        extension_doc_hash = b"\x66" * 32
        sign_priv = b"\x33" * 32
        sign_pub = derive_public_key(sign_priv)
        shard_frames = _passphrase_shard_frames(
            "secret passphrase",
            threshold=2,
            share_count=3,
            doc_id=extension_doc_id,
            doc_hash=extension_doc_hash,
            sign_priv=sign_priv,
        )[:2]
        chain = SimpleNamespace(
            manifest=EnvelopeManifest(
                format_version=1,
                created_at=1,
                sealed=True,
                signing_seed=None,
                files=(ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1),),
                input_origin="file",
                input_roots=(),
            ),
            extracted=(
                (ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1), b"data"),
            ),
            selected_extension_index=1,
            selected_extension_doc_hash=extension_doc_hash.hex(),
        )
        recover_plan = SimpleNamespace(
            passphrase="secret passphrase",
            doc_id=root_doc_id,
            doc_hash=root_doc_hash,
            auth_payload=SimpleNamespace(sign_pub=sign_pub),
            shard_frames=shard_frames,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()
            output_dir = Path(tmpdir) / "compacted"
            with (
                mock.patch(
                    "ethernity.cli.features.compact.service.plan_recover_from_args",
                    return_value=recover_plan,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.recover_chain_entries",
                    return_value=chain,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.load_app_config",
                    return_value=SimpleNamespace(),
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.apply_template_design",
                    side_effect=lambda config, _design: config,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.apply_qr_chunk_size_override",
                    side_effect=lambda config, _size: config,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.plan_backup_from_args",
                    return_value=SimpleNamespace(
                        sealed=True,
                        sharding=None,
                        signing_seed_mode="embedded",
                        signing_seed_sharding=None,
                    ),
                ) as plan_backup_from_args,
                mock.patch(
                    "ethernity.cli.features.compact.service.run_backup",
                    return_value="backup-result",
                ),
            ):
                result = run_compact(
                    CompactArgs(
                        root_dir=str(root_dir),
                        output_dir=str(output_dir),
                        shard_scan=["/separate/extension-shard-a.pdf"],
                        quiet=True,
                    )
                )

        self.assertEqual(result, "backup-result")
        backup_args = plan_backup_from_args.call_args.args[0]
        self.assertEqual(backup_args.shard_threshold, 2)
        self.assertEqual(backup_args.shard_count, 3)
        self.assertTrue(backup_args.sealed)

    def test_run_compact_filters_mixed_unlock_shards_to_selected_head_policy(self) -> None:
        root_doc_id = b"\x22" * 8
        root_doc_hash = b"\x44" * 32
        extension_doc_id = b"\x55" * 8
        extension_doc_hash = b"\x66" * 32
        sign_priv = b"\x33" * 32
        sign_pub = derive_public_key(sign_priv)
        root_shard_frames = _passphrase_shard_frames(
            "secret passphrase",
            threshold=2,
            share_count=5,
            doc_id=root_doc_id,
            doc_hash=root_doc_hash,
            sign_priv=sign_priv,
        )[:2]
        extension_shard_frames = _passphrase_shard_frames(
            "secret passphrase",
            threshold=2,
            share_count=3,
            doc_id=extension_doc_id,
            doc_hash=extension_doc_hash,
            sign_priv=sign_priv,
        )[:2]
        chain = SimpleNamespace(
            manifest=EnvelopeManifest(
                format_version=1,
                created_at=1,
                sealed=True,
                signing_seed=None,
                files=(ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1),),
                input_origin="file",
                input_roots=(),
            ),
            extracted=(
                (ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1), b"data"),
            ),
            selected_extension_index=1,
            selected_extension_doc_hash=extension_doc_hash.hex(),
        )
        recover_plan = SimpleNamespace(
            passphrase="secret passphrase",
            doc_id=root_doc_id,
            doc_hash=root_doc_hash,
            auth_payload=SimpleNamespace(sign_pub=sign_pub),
            shard_frames=(*root_shard_frames, *extension_shard_frames),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()
            output_dir = Path(tmpdir) / "compacted"
            with (
                mock.patch(
                    "ethernity.cli.features.compact.service.plan_recover_from_args",
                    return_value=recover_plan,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.recover_chain_entries",
                    return_value=chain,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.load_app_config",
                    return_value=SimpleNamespace(),
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.apply_template_design",
                    side_effect=lambda config, _design: config,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.apply_qr_chunk_size_override",
                    side_effect=lambda config, _size: config,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.plan_backup_from_args",
                    return_value=SimpleNamespace(
                        sealed=True,
                        sharding=None,
                        signing_seed_mode="embedded",
                        signing_seed_sharding=None,
                    ),
                ) as plan_backup_from_args,
                mock.patch(
                    "ethernity.cli.features.compact.service.run_backup",
                    return_value="backup-result",
                ),
            ):
                result = run_compact(
                    CompactArgs(
                        root_dir=str(root_dir),
                        output_dir=str(output_dir),
                        shard_scan=["/mixed/root-a.pdf", "/mixed/ext-a.pdf"],
                        quiet=True,
                    )
                )

        self.assertEqual(result, "backup-result")
        backup_args = plan_backup_from_args.call_args.args[0]
        self.assertEqual(backup_args.shard_threshold, 2)
        self.assertEqual(backup_args.shard_count, 3)
        self.assertTrue(backup_args.sealed)

    @mock.patch("ethernity.cli.features.compact.service.run_backup")
    @mock.patch(
        "ethernity.cli.features.compact.service.recover_chain_entries",
        side_effect=ApiCommandError(
            code=api_codes.RECOVERY_HEAD_UNTRUSTED,
            message=(
                "latest supplied recovery head could not be trusted: "
                "missing required MAIN documents"
            ),
            details={
                "stage": "replay",
                "failure_stage": "discovery",
                "failure_message": "missing required MAIN documents",
                "failure_head_index": 2,
                "failure_head_doc_hash": None,
                "failure_head_dir_name": "02",
                "latest_head_index": 2,
                "latest_head_doc_hash": None,
                "latest_head_dir_name": "02",
                "requested_head_index": None,
                "requested_head_doc_hash": None,
                "validated_head_index": 0,
                "validated_head_doc_hash": "44" * 32,
                "validated_head_auth_status": None,
                "validated_head_root_authority_verified": None,
                "explicit_selection": False,
            },
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.plan_recover_from_args",
        return_value=SimpleNamespace(
            passphrase="secret",
            doc_id=b"\x22" * 16,
            doc_hash=b"\x44" * 32,
            auth_payload=None,
            shard_frames=(),
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service._validated_compact_root_dir",
        return_value=Path("/tmp/root"),
    )
    def test_run_compact_translates_head_untrusted_into_no_checkpoint_refusal(
        self,
        _validated_compact_root_dir: mock.MagicMock,
        _plan_recover_from_args: mock.MagicMock,
        _recover_chain_entries: mock.MagicMock,
        run_backup_mock: mock.MagicMock,
    ) -> None:
        with self.assertRaises(ApiCommandError) as ctx:
            run_compact(
                CompactArgs(
                    root_dir="/tmp/root",
                    output_dir="/tmp/out",
                    passphrase="secret",
                    quiet=True,
                )
            )

        exc = ctx.exception
        self.assertEqual(exc.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(
            str(exc),
            (
                "latest supplied compact head could not be trusted; no checkpoint was created: "
                "missing required MAIN documents"
            ),
        )
        self.assertEqual(exc.details["stage"], "replay")
        self.assertEqual(exc.details["failure_stage"], "discovery")
        self.assertEqual(exc.details["failure_head_index"], 2)
        self.assertEqual(exc.details["latest_head_index"], 2)
        self.assertEqual(exc.details["validated_head_index"], 0)
        self.assertFalse(exc.details["explicit_selection"])
        self.assertFalse(exc.details["checkpoint_created"])
        self.assertIsNone(exc.details["failure_head_doc_hash"])
        self.assertIsNone(exc.details["latest_head_doc_hash"])
        run_backup_mock.assert_not_called()

    @mock.patch("ethernity.cli.features.compact.service.run_backup")
    @mock.patch(
        "ethernity.cli.features.compact.service.recover_chain_entries",
        side_effect=ApiCommandError(
            code=api_codes.ROOT_AUTHORITY_MISMATCH,
            message="embedded signing seed does not match the verified root AUTH authority",
            details={"stage": "replay"},
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.plan_recover_from_args",
        return_value=SimpleNamespace(
            passphrase="secret",
            doc_id=b"\x22" * 16,
            doc_hash=b"\x44" * 32,
            auth_payload=None,
            shard_frames=(),
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service._validated_compact_root_dir",
        return_value=Path("/tmp/root"),
    )
    def test_run_compact_preserves_non_trust_api_command_errors(
        self,
        _validated_compact_root_dir: mock.MagicMock,
        _plan_recover_from_args: mock.MagicMock,
        _recover_chain_entries: mock.MagicMock,
        run_backup_mock: mock.MagicMock,
    ) -> None:
        with self.assertRaises(ApiCommandError) as ctx:
            run_compact(
                CompactArgs(
                    root_dir="/tmp/root",
                    output_dir="/tmp/out",
                    passphrase="secret",
                    quiet=True,
                )
            )

        exc = ctx.exception
        self.assertEqual(exc.code, api_codes.ROOT_AUTHORITY_MISMATCH)
        self.assertEqual(
            str(exc),
            "embedded signing seed does not match the verified root AUTH authority",
        )
        self.assertEqual(exc.details, {"stage": "replay"})
        run_backup_mock.assert_not_called()

    @mock.patch("ethernity.cli.features.compact.service.run_backup", return_value="backup-result")
    @mock.patch(
        "ethernity.cli.features.compact.service.plan_backup_from_args",
        return_value=SimpleNamespace(
            sealed=False,
            sharding=None,
            signing_seed_mode="embedded",
            signing_seed_sharding=None,
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.apply_qr_chunk_size_override",
        side_effect=lambda config, _size: config,
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.apply_template_design",
        side_effect=lambda config, _design: config,
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.load_app_config",
        return_value=SimpleNamespace(),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service._infer_root_publish_policy",
        return_value=SimpleNamespace(
            passphrase_shard_threshold=2,
            passphrase_shard_count=3,
            signing_key_shard_threshold=2,
            signing_key_shard_count=3,
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.recover_chain_entries",
        return_value=SimpleNamespace(
            manifest=EnvelopeManifest(
                format_version=1,
                created_at=1,
                sealed=False,
                signing_seed=b"\x33" * 32,
                files=(ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1),),
                input_origin="directory",
                input_roots=("reconstructed-state",),
            ),
            extracted=(
                (ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1), b"data"),
            ),
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.plan_recover_from_args",
        return_value=SimpleNamespace(
            passphrase="secret",
            doc_id=b"\x22" * 16,
            doc_hash=b"\x44" * 32,
            auth_payload=SimpleNamespace(sign_pub=b"\x55" * 32),
            shard_frames=(),
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service._validated_compact_root_dir",
        return_value=Path("/tmp/root"),
    )
    def test_run_compact_reuses_root_signing_seed_and_inherited_policy(
        self,
        _validated_compact_root_dir: mock.MagicMock,
        plan_recover_from_args: mock.MagicMock,
        recover_chain_entries: mock.MagicMock,
        _infer_root_publish_policy: mock.MagicMock,
        load_app_config: mock.MagicMock,
        apply_template_design: mock.MagicMock,
        apply_qr_chunk_size_override: mock.MagicMock,
        plan_backup_from_args: mock.MagicMock,
        run_backup_mock: mock.MagicMock,
    ) -> None:
        result = run_compact(
            CompactArgs(
                root_dir="/tmp/root",
                output_dir="/tmp/out",
                passphrase="secret",
                shard_fallback_file=["shard-a.txt"],
                shard_payloads_file=["shard-a.payloads"],
                shard_scan=["shard-a.pdf"],
                auth_fallback_file="auth.txt",
                auth_payloads_file="auth.payloads",
                quiet=True,
            )
        )

        self.assertEqual(result, "backup-result")
        recover_args = plan_recover_from_args.call_args.args[0]
        self.assertIsInstance(recover_args, RecoverArgs)
        self.assertEqual(recover_args.scan, ["/tmp/root"])
        self.assertEqual(recover_args.shard_fallback_file, ["shard-a.txt"])
        self.assertEqual(recover_args.shard_payloads_file, ["shard-a.payloads"])
        self.assertEqual(recover_args.shard_scan, ["shard-a.pdf"])
        self.assertEqual(recover_args.auth_fallback_file, "auth.txt")
        self.assertEqual(recover_args.auth_payloads_file, "auth.payloads")
        self.assertFalse(recover_args.allow_unsigned)
        backup_args = plan_backup_from_args.call_args.args[0]
        self.assertEqual(backup_args.output_dir, "/tmp/out")
        self.assertEqual(backup_args.shard_threshold, 2)
        self.assertEqual(backup_args.shard_count, 3)
        self.assertEqual(backup_args.signing_key_mode, "sharded")
        self.assertEqual(run_backup_mock.call_args.kwargs["signing_seed_override"], b"\x33" * 32)
        self.assertEqual(run_backup_mock.call_args.kwargs["input_origin"], "directory")
        self.assertEqual(
            run_backup_mock.call_args.kwargs["input_roots"],
            ["reconstructed-state"],
        )
        self.assertEqual(
            run_backup_mock.call_args.kwargs["render_lineage"].kind,
            "compaction_checkpoint",
        )
        self.assertEqual(
            run_backup_mock.call_args.kwargs["promote_lock_dir"],
            Path("/tmp/root") / "extensions" / ".chain.lock",
        )
        self.assertTrue(callable(run_backup_mock.call_args.kwargs["prepare_promotion"]))
        self.assertTrue(callable(run_backup_mock.call_args.kwargs["validate_promotion"]))

    def test_run_compact_revalidates_source_head_before_checkpoint_promotion(self) -> None:
        doc_id = b"\x22" * 16
        root_hash = b"\x44" * 32
        initial_chain = SimpleNamespace(
            manifest=EnvelopeManifest(
                format_version=1,
                created_at=1,
                sealed=True,
                signing_seed=None,
                files=(ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1),),
                input_origin="file",
                input_roots=(),
            ),
            extracted=(
                (ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1), b"data"),
            ),
            selected_extension_index=1,
            selected_extension_doc_hash="aa" * 32,
        )
        changed_chain = SimpleNamespace(
            manifest=initial_chain.manifest,
            extracted=initial_chain.extracted,
            selected_extension_index=2,
            selected_extension_doc_hash="bb" * 32,
        )
        initial_plan = SimpleNamespace(
            passphrase="secret",
            doc_id=doc_id,
            doc_hash=root_hash,
            auth_payload=SimpleNamespace(sign_pub=b"\x55" * 32),
            shard_frames=(),
        )
        changed_plan = SimpleNamespace(
            passphrase="secret",
            doc_id=doc_id,
            doc_hash=root_hash,
            auth_payload=SimpleNamespace(sign_pub=b"\x55" * 32),
            shard_frames=(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()
            output_dir = Path(tmpdir) / "out"

            def _run_backup_with_promotion_validation(**kwargs):
                self.assertEqual(
                    kwargs["promote_lock_dir"],
                    root_dir / "extensions" / ".chain.lock",
                )
                kwargs["prepare_promotion"]()
                self.assertTrue((root_dir / "extensions").is_dir())
                kwargs["validate_promotion"]()
                return "backup-result"

            with (
                mock.patch(
                    "ethernity.cli.features.compact.service.plan_recover_from_args",
                    side_effect=(initial_plan, changed_plan),
                ) as plan_recover_from_args,
                mock.patch(
                    "ethernity.cli.features.compact.service.recover_chain_entries",
                    side_effect=(initial_chain, changed_chain),
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.load_app_config",
                    return_value=SimpleNamespace(),
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.apply_template_design",
                    side_effect=lambda config, _design: config,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.apply_qr_chunk_size_override",
                    side_effect=lambda config, _size: config,
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.plan_backup_from_args",
                    return_value=SimpleNamespace(
                        sealed=True,
                        sharding=None,
                        signing_seed_mode="embedded",
                        signing_seed_sharding=None,
                    ),
                ),
                mock.patch(
                    "ethernity.cli.features.compact.service.run_backup",
                    side_effect=_run_backup_with_promotion_validation,
                ),
                self.assertRaises(ApiCommandError) as caught,
            ):
                run_compact(
                    CompactArgs(
                        root_dir=str(root_dir),
                        output_dir=str(output_dir),
                        passphrase="secret",
                        quiet=True,
                    )
                )

        self.assertEqual(plan_recover_from_args.call_count, 2)
        self.assertEqual(caught.exception.code, api_codes.CHAIN_INVALID)
        self.assertEqual(caught.exception.details["stage"], "publish_head")
        self.assertFalse(caught.exception.details["checkpoint_created"])
        mismatches = caught.exception.details["mismatches"]
        self.assertEqual(mismatches["selected_extension_index"], {"expected": 1, "actual": 2})
        self.assertEqual(
            mismatches["selected_extension_doc_hash"],
            {"expected": "aa" * 32, "actual": "bb" * 32},
        )

    @mock.patch("ethernity.cli.features.compact.service.run_backup", return_value="backup-result")
    @mock.patch(
        "ethernity.cli.features.compact.service.plan_backup_from_args",
        return_value=SimpleNamespace(
            sealed=False,
            sharding=None,
            signing_seed_mode="embedded",
            signing_seed_sharding=None,
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.apply_qr_chunk_size_override",
        side_effect=lambda config, _size: config,
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.apply_template_design",
        side_effect=lambda config, _design: config,
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.load_app_config",
        return_value=SimpleNamespace(),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service._infer_root_publish_policy",
        return_value=SimpleNamespace(
            passphrase_shard_threshold=2,
            passphrase_shard_count=3,
            signing_key_shard_threshold=2,
            signing_key_shard_count=3,
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.recover_chain_entries",
        return_value=SimpleNamespace(
            manifest=EnvelopeManifest(
                format_version=1,
                created_at=1,
                sealed=False,
                signing_seed=b"\x33" * 32,
                files=(ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1),),
                input_origin="file",
                input_roots=(),
            ),
            extracted=(
                (ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1), b"data"),
            ),
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.plan_recover_from_args",
        return_value=SimpleNamespace(
            passphrase="secret",
            doc_id=b"\x22" * 16,
            doc_hash=b"\x44" * 32,
            auth_payload=None,
            shard_frames=(),
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service._validated_compact_root_dir",
        return_value=Path("/tmp/root"),
    )
    def test_run_compact_derives_signing_authority_from_manifest_seed_when_auth_missing(
        self,
        _validated_compact_root_dir: mock.MagicMock,
        _plan_recover_from_args: mock.MagicMock,
        _recover_chain_entries: mock.MagicMock,
        infer_root_publish_policy: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_template_design: mock.MagicMock,
        _apply_qr_chunk_size_override: mock.MagicMock,
        _plan_backup_from_args: mock.MagicMock,
        _run_backup_mock: mock.MagicMock,
    ) -> None:
        result = run_compact(
            CompactArgs(
                root_dir="/tmp/root",
                output_dir="/tmp/out",
                passphrase="secret",
                quiet=True,
            )
        )

        self.assertEqual(result, "backup-result")
        self.assertEqual(
            infer_root_publish_policy.call_args.kwargs["sign_pub"],
            derive_public_key(b"\x33" * 32),
        )
        self.assertNotIn("allow_unsigned", infer_root_publish_policy.call_args.kwargs)

    @mock.patch("ethernity.cli.features.compact.service.run_backup", return_value="backup-result")
    @mock.patch(
        "ethernity.cli.features.compact.service.plan_backup_from_args",
        return_value=SimpleNamespace(
            sealed=True,
            sharding=None,
            signing_seed_mode="embedded",
            signing_seed_sharding=None,
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.apply_qr_chunk_size_override",
        side_effect=lambda config, _size: config,
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.apply_template_design",
        side_effect=lambda config, _design: config,
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.load_app_config",
        return_value=SimpleNamespace(),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service._infer_root_publish_policy",
        return_value=SimpleNamespace(
            passphrase_shard_threshold=None,
            passphrase_shard_count=0,
            signing_key_shard_threshold=None,
            signing_key_shard_count=0,
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.recover_chain_entries",
        return_value=SimpleNamespace(
            manifest=EnvelopeManifest(
                format_version=1,
                created_at=1,
                sealed=True,
                signing_seed=None,
                files=(ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1),),
                input_origin="file",
                input_roots=(),
            ),
            extracted=(
                (ManifestFile(path="a.txt", size=4, sha256=b"\x11" * 32, mtime=1), b"data"),
            ),
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.plan_recover_from_args",
        return_value=SimpleNamespace(
            passphrase="secret",
            doc_id=b"\x22" * 16,
            doc_hash=b"\x44" * 32,
            auth_payload=None,
            shard_frames=(),
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service._validated_compact_root_dir",
        return_value=Path("/tmp/root"),
    )
    def test_run_compact_allows_sealed_rescue_flow_without_root_auth(
        self,
        _validated_compact_root_dir: mock.MagicMock,
        _plan_recover_from_args: mock.MagicMock,
        _recover_chain_entries: mock.MagicMock,
        infer_root_publish_policy: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_template_design: mock.MagicMock,
        _apply_qr_chunk_size_override: mock.MagicMock,
        _plan_backup_from_args: mock.MagicMock,
        run_backup_mock: mock.MagicMock,
    ) -> None:
        result = run_compact(
            CompactArgs(
                root_dir="/tmp/root",
                output_dir="/tmp/out",
                passphrase="secret",
                quiet=True,
            )
        )

        self.assertEqual(result, "backup-result")
        self.assertIsNone(infer_root_publish_policy.call_args.kwargs["sign_pub"])
        self.assertNotIn("allow_unsigned", infer_root_publish_policy.call_args.kwargs)
        backup_args = _plan_backup_from_args.call_args.args[0]
        self.assertIsNone(backup_args.shard_threshold)
        self.assertIsNone(backup_args.shard_count)
        self.assertIsNone(run_backup_mock.call_args.kwargs["signing_seed_override"])

    @mock.patch(
        "ethernity.cli.features.compact.service.recover_chain_entries",
        return_value=SimpleNamespace(
            manifest=EnvelopeManifest(
                format_version=1,
                created_at=1,
                sealed=False,
                signing_seed=b"\x33" * 32,
                files=(ManifestFile(path="a.txt", size=1, sha256=b"\x11" * 32, mtime=1),),
                input_origin="file",
                input_roots=(),
            ),
            extracted=((ManifestFile(path="a.txt", size=1, sha256=b"\x11" * 32, mtime=1), b"a"),),
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service.plan_recover_from_args",
        return_value=SimpleNamespace(
            passphrase="secret",
            doc_id=b"\x22" * 16,
            doc_hash=b"\x44" * 32,
            auth_payload=SimpleNamespace(sign_pub=b"\x55" * 32),
            shard_frames=(),
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service._infer_root_publish_policy",
        return_value=SimpleNamespace(
            passphrase_shard_threshold=None,
            passphrase_shard_count=0,
            signing_key_shard_threshold=2,
            signing_key_shard_count=3,
        ),
    )
    @mock.patch(
        "ethernity.cli.features.compact.service._validated_compact_root_dir",
        return_value=Path("/tmp/root"),
    )
    def test_run_compact_rejects_invalid_inherited_signing_key_shard_policy(
        self,
        _validated_compact_root_dir: mock.MagicMock,
        _infer_root_publish_policy: mock.MagicMock,
        _plan_recover_from_args: mock.MagicMock,
        _recover_chain_entries: mock.MagicMock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "signing-key shards require passphrase shards"):
            run_compact(
                CompactArgs(
                    root_dir="/tmp/root",
                    output_dir="/tmp/out",
                    passphrase="secret",
                    quiet=True,
                )
            )
