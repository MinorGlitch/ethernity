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

from ethernity.crypto.document_identity import doc_id_from_doc_hash
from ethernity.crypto.sharding import encode_shard_payload, split_passphrase, split_signing_seed
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.formats.manifest import BackupManifest, ManifestFile
from ethernity.workflows.rebuild.service import (
    _infer_passphrase_shard_policy_from_frames,
    _infer_recovery_sheet_settings,
    execute_rebuild_operation,
)
from ethernity.workflows.shared import api_codes
from ethernity.workflows.shared.events import CommandError as ApiCommandError
from ethernity.workflows.shared.operation_types import (
    BackupResult,
    RebuildOperationRequest,
    RecoverArgs,
)


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


def _backup_result() -> BackupResult:
    return BackupResult(
        doc_id=b"\xaa" * 8,
        doc_hash=b"\xaa" * 32,
        qr_path="/tmp/out/qr.pdf",
        recovery_path="/tmp/out/recovery.pdf",
        shard_paths=(),
        signing_key_shard_paths=(),
        passphrase_used="secret",
    )


class TestRebuildService(unittest.TestCase):
    def test_run_rebuild_rejects_missing_root_dir_with_rebuild_specific_message(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "backup source folder not found: /tmp/missing-root",
        ):
            execute_rebuild_operation(
                RebuildOperationRequest(
                    root_dir="/tmp/missing-root",
                    output_dir="/tmp/out",
                    passphrase="secret",
                    allow_stale_head=True,
                )
            )

    def test_run_rebuild_rejects_root_dir_with_scan_source(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "use either --root-dir or --scan for rebuild, not both",
        ):
            execute_rebuild_operation(
                RebuildOperationRequest(
                    root_dir="/tmp/root",
                    scan=["root.pdf"],
                    output_dir="/tmp/out",
                    passphrase="secret",
                    allow_stale_head=True,
                )
            )

    def test_run_rebuild_reports_scan_failure_for_empty_root_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            with self.assertRaisesRegex(
                ValueError,
                "scan failed: no scan files found in directory",
            ):
                execute_rebuild_operation(
                    RebuildOperationRequest(
                        root_dir=str(root_dir),
                        output_dir="/tmp/out",
                        passphrase="secret",
                        allow_stale_head=True,
                    )
                )

    def test_run_rebuild_rejects_unacknowledged_scan_source(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "--allow-stale-head",
        ):
            execute_rebuild_operation(
                RebuildOperationRequest(
                    scan=["root.pdf"],
                    output_dir="/tmp/out",
                    passphrase="secret",
                )
            )

    def test_run_rebuild_requires_freshness_acknowledgement_for_folders(self) -> None:
        with self.assertRaisesRegex(ValueError, "supplied documents are the latest chain state"):
            execute_rebuild_operation(
                RebuildOperationRequest(
                    root_dir="source-documents", output_dir="rebuilt", passphrase="secret"
                )
            )

    def test_run_rebuild_accepts_scan_source_without_root_dir(self) -> None:
        chain = SimpleNamespace(
            manifest=BackupManifest(
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
            selected_extension_doc_hash="55" * 32,
        )
        recover_plan = SimpleNamespace(
            passphrase="secret passphrase",
            doc_id=b"\x22" * 8,
            doc_hash=b"\x44" * 32,
            auth_payload=None,
            shard_frames=(),
        )
        inherited = SimpleNamespace(
            passphrase_shard_threshold=None,
            passphrase_shard_count=0,
            signing_key_shard_threshold=None,
            signing_key_shard_count=0,
        )

        with (
            mock.patch(
                "ethernity.workflows.rebuild.service._validated_rebuild_root_dir"
            ) as validated_rebuild_root_dir,
            mock.patch(
                "ethernity.workflows.rebuild.service.plan_recover_from_args",
                return_value=recover_plan,
            ) as plan_recover_from_args,
            mock.patch(
                "ethernity.workflows.rebuild.service.recover_chain_entries",
                return_value=chain,
            ),
            mock.patch(
                "ethernity.workflows.rebuild.service._infer_recovery_sheet_settings",
                return_value=inherited,
            ) as infer_recovery_sheet_settings,
            mock.patch(
                "ethernity.workflows.rebuild.service.load_app_config",
                return_value=SimpleNamespace(),
            ),
            mock.patch(
                "ethernity.workflows.rebuild.service.apply_render_style",
                side_effect=lambda config, _design: config,
            ),
            mock.patch(
                "ethernity.workflows.rebuild.service.apply_qr_chunk_size_override",
                side_effect=lambda config, _size: config,
            ),
            mock.patch(
                "ethernity.workflows.rebuild.service.plan_backup_from_args",
                return_value=SimpleNamespace(
                    sealed=True,
                    sharding=None,
                    signing_seed_mode="embedded",
                    signing_seed_sharding=None,
                ),
            ),
            mock.patch(
                "ethernity.workflows.rebuild.service.run_backup",
                return_value=_backup_result(),
            ) as run_backup_mock,
        ):
            result = execute_rebuild_operation(
                RebuildOperationRequest(
                    scan=["root.pdf", "extension-01.pdf"],
                    output_dir="/tmp/out",
                    passphrase="secret",
                    allow_stale_head=True,
                )
            )

        self.assertEqual(result.doc_id, b"\xaa" * 8)
        validated_rebuild_root_dir.assert_not_called()
        recover_args = plan_recover_from_args.call_args.args[0]
        self.assertEqual(recover_args.scan, ["root.pdf", "extension-01.pdf"])
        self.assertIsNone(infer_recovery_sheet_settings.call_args.kwargs["root_dir"])
        self.assertEqual(
            infer_recovery_sheet_settings.call_args.kwargs["source_scan"],
            ("root.pdf", "extension-01.pdf"),
        )
        self.assertIsNone(run_backup_mock.call_args.kwargs.get("promote_lock_path"))
        self.assertIsNone(run_backup_mock.call_args.kwargs.get("prepare_promotion"))

    def test_run_rebuild_rejects_output_dir_equal_to_root_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            with self.assertRaisesRegex(
                ValueError,
                "rebuild output directory must not be the source folder or inside it",
            ):
                execute_rebuild_operation(
                    RebuildOperationRequest(
                        root_dir=str(root_dir),
                        output_dir=str(root_dir),
                        passphrase="secret",
                        allow_stale_head=True,
                    )
                )

    def test_run_rebuild_rejects_output_dir_inside_root_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            with self.assertRaisesRegex(
                ValueError,
                "rebuild output directory must not be the source folder or inside it",
            ):
                execute_rebuild_operation(
                    RebuildOperationRequest(
                        root_dir=str(root_dir),
                        output_dir=str(root_dir / "rebuilt"),
                        passphrase="secret",
                        allow_stale_head=True,
                    )
                )

    def test_run_rebuild_rejects_layout_debug_dir_inside_root_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            with self.assertRaisesRegex(
                ValueError,
                "rebuild layout debug directory must not be the source folder or inside it",
            ):
                execute_rebuild_operation(
                    RebuildOperationRequest(
                        root_dir=str(root_dir),
                        output_dir=str(root_dir.parent / "rebuilt"),
                        layout_debug_dir=str(root_dir / "layout-debug"),
                        passphrase="secret",
                        allow_stale_head=True,
                    )
                )

    def test_infer_recovery_sheet_settings_uses_external_passphrase_shard_frames(self) -> None:
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
        policy = _infer_recovery_sheet_settings(
            root_dir=None,
            root_doc_id_hex=doc_id.hex(),
            root_doc_hash=doc_hash,
            sign_pub=sign_pub,
            passphrase_shard_frames=shard_frames,
        )

        self.assertEqual(policy.passphrase_shard_threshold, 2)
        self.assertEqual(policy.passphrase_shard_count, 3)
        self.assertIsNone(policy.signing_key_shard_threshold)
        self.assertEqual(policy.signing_key_shard_count, 0)

    def test_infer_recovery_sheet_settings_scans_renamed_shard_content(self) -> None:
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
                "ethernity.workflows.rebuild.service.frames_from_scan",
                return_value=list(shard_frames),
            ) as frames_from_scan:
                policy = _infer_recovery_sheet_settings(
                    root_dir=str(root_dir),
                    root_doc_id_hex=doc_id.hex(),
                    root_doc_hash=doc_hash,
                    sign_pub=sign_pub,
                )

        frames_from_scan.assert_called_once_with([str(root_dir)])
        self.assertEqual(policy.passphrase_shard_threshold, 2)
        self.assertEqual(policy.passphrase_shard_count, 3)

    def test_infer_recovery_sheet_settings_classifies_signing_key_shards_by_payload(self) -> None:
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
                "ethernity.workflows.rebuild.service.frames_from_scan",
                return_value=list(shard_frames),
            ):
                policy = _infer_recovery_sheet_settings(
                    root_dir=str(root_dir),
                    root_doc_id_hex=doc_id.hex(),
                    root_doc_hash=doc_hash,
                    sign_pub=sign_pub,
                )

        self.assertIsNone(policy.passphrase_shard_threshold)
        self.assertEqual(policy.passphrase_shard_count, 0)
        self.assertEqual(policy.signing_key_shard_threshold, 2)
        self.assertEqual(policy.signing_key_shard_count, 4)

    def test_infer_recovery_sheet_settings_selects_shards_by_binding_regardless_of_location(
        self,
    ) -> None:
        doc_hash = b"\x44" * 32
        doc_id = doc_id_from_doc_hash(doc_hash)
        sign_priv = b"\x33" * 32
        root_shards = _passphrase_shard_frames(
            "secret",
            threshold=2,
            share_count=3,
            doc_id=doc_id,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
        )[:2]
        unrelated_shards = _passphrase_shard_frames(
            "other",
            threshold=2,
            share_count=5,
            doc_id=b"\x99" * 8,
            doc_hash=b"\x99" * 32,
            sign_priv=sign_priv,
        )[:2]
        with mock.patch(
            "ethernity.workflows.rebuild.service.frames_from_scan",
            return_value=[*unrelated_shards, *root_shards],
        ) as scanner:
            policy = _infer_recovery_sheet_settings(
                root_dir="arbitrary-documents",
                root_doc_id_hex=doc_id.hex(),
                root_doc_hash=doc_hash,
                sign_pub=derive_public_key(sign_priv),
            )
        scanner.assert_called_once_with(["arbitrary-documents"])
        self.assertEqual(policy.passphrase_shard_threshold, 2)
        self.assertEqual(policy.passphrase_shard_count, 3)

    def test_infer_recovery_sheet_settings_rejects_shards_without_a_trusted_signing_key(
        self,
    ) -> None:
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
            _infer_recovery_sheet_settings(
                root_dir=None,
                root_doc_id_hex=doc_id.hex(),
                root_doc_hash=doc_hash,
                sign_pub=None,
                passphrase_shard_frames=shard_frames,
            )

        self.assertEqual(ctx.exception.code, api_codes.REBUILD_INVALID_POLICY)
        self.assertEqual(ctx.exception.details, {"stage": "root_shard_policy"})

    def test_infer_source_shard_policy_rejects_shards_without_a_trusted_signing_key(self) -> None:
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

        self.assertEqual(ctx.exception.code, api_codes.REBUILD_INVALID_POLICY)
        self.assertEqual(ctx.exception.details, {"stage": "source_shard_policy"})

    def test_run_rebuild_preserves_external_unlock_shard_policy(self) -> None:
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
            manifest=BackupManifest(
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
            output_dir = Path(tmpdir) / "rebuilt"
            with (
                mock.patch(
                    "ethernity.workflows.rebuild.service.plan_recover_from_args",
                    return_value=recover_plan,
                ),
                mock.patch("ethernity.workflows.rebuild.service.frames_from_scan", return_value=[]),
                mock.patch(
                    "ethernity.workflows.rebuild.service.recover_chain_entries",
                    return_value=chain,
                ),
                mock.patch(
                    "ethernity.workflows.rebuild.service.load_app_config",
                    return_value=SimpleNamespace(),
                ),
                mock.patch(
                    "ethernity.workflows.rebuild.service.apply_render_style",
                    side_effect=lambda config, _design: config,
                ),
                mock.patch(
                    "ethernity.workflows.rebuild.service.apply_qr_chunk_size_override",
                    side_effect=lambda config, _size: config,
                ),
                mock.patch(
                    "ethernity.workflows.rebuild.service.plan_backup_from_args",
                    return_value=SimpleNamespace(
                        sealed=True,
                        sharding=None,
                        signing_seed_mode="embedded",
                        signing_seed_sharding=None,
                    ),
                ) as plan_backup_from_args,
                mock.patch(
                    "ethernity.workflows.rebuild.service.run_backup",
                    return_value=_backup_result(),
                ),
            ):
                result = execute_rebuild_operation(
                    RebuildOperationRequest(
                        root_dir=str(root_dir),
                        output_dir=str(output_dir),
                        shard_scan=["/separate/shard-a.pdf", "/separate/shard-b.pdf"],
                        allow_stale_head=True,
                    )
                )

        self.assertEqual(result.doc_id, b"\xaa" * 8)
        backup_args = plan_backup_from_args.call_args.args[0]
        self.assertEqual(backup_args.shard_threshold, 2)
        self.assertEqual(backup_args.shard_count, 3)
        self.assertTrue(backup_args.sealed)

    def test_run_rebuild_preserves_extension_local_unlock_shard_policy(self) -> None:
        root_doc_id = b"\x22" * 8
        root_doc_hash = b"\x44" * 32
        extension_doc_hash = b"\x55" * 16 + b"\x66" * 16
        extension_doc_id = doc_id_from_doc_hash(extension_doc_hash)
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
            manifest=BackupManifest(
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
            output_dir = Path(tmpdir) / "rebuilt"
            with (
                mock.patch(
                    "ethernity.workflows.rebuild.service.plan_recover_from_args",
                    return_value=recover_plan,
                ),
                mock.patch("ethernity.workflows.rebuild.service.frames_from_scan", return_value=[]),
                mock.patch(
                    "ethernity.workflows.rebuild.service.recover_chain_entries",
                    return_value=chain,
                ),
                mock.patch(
                    "ethernity.workflows.rebuild.service.load_app_config",
                    return_value=SimpleNamespace(),
                ),
                mock.patch(
                    "ethernity.workflows.rebuild.service.apply_render_style",
                    side_effect=lambda config, _design: config,
                ),
                mock.patch(
                    "ethernity.workflows.rebuild.service.apply_qr_chunk_size_override",
                    side_effect=lambda config, _size: config,
                ),
                mock.patch(
                    "ethernity.workflows.rebuild.service.plan_backup_from_args",
                    return_value=SimpleNamespace(
                        sealed=True,
                        sharding=None,
                        signing_seed_mode="embedded",
                        signing_seed_sharding=None,
                    ),
                ) as plan_backup_from_args,
                mock.patch(
                    "ethernity.workflows.rebuild.service.run_backup",
                    return_value=_backup_result(),
                ),
            ):
                result = execute_rebuild_operation(
                    RebuildOperationRequest(
                        root_dir=str(root_dir),
                        output_dir=str(output_dir),
                        shard_scan=["/separate/extension-shard-a.pdf"],
                        allow_stale_head=True,
                    )
                )

        self.assertEqual(result.doc_id, b"\xaa" * 8)
        backup_args = plan_backup_from_args.call_args.args[0]
        self.assertEqual(backup_args.shard_threshold, 2)
        self.assertEqual(backup_args.shard_count, 3)
        self.assertTrue(backup_args.sealed)

    def test_run_rebuild_rejects_selected_extension_unlock_shard_with_wrong_frame_doc_id(
        self,
    ) -> None:
        root_doc_id = b"\x22" * 8
        root_doc_hash = b"\x44" * 32
        extension_doc_hash = b"\x55" * 16 + b"\x66" * 16
        sign_priv = b"\x33" * 32
        sign_pub = derive_public_key(sign_priv)
        shard_frames = _passphrase_shard_frames(
            "secret passphrase",
            threshold=2,
            share_count=3,
            doc_id=b"\x99" * 8,
            doc_hash=extension_doc_hash,
            sign_priv=sign_priv,
        )[:2]
        chain = SimpleNamespace(
            manifest=BackupManifest(
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
            output_dir = Path(tmpdir) / "rebuilt"
            with (
                mock.patch(
                    "ethernity.workflows.rebuild.service.plan_recover_from_args",
                    return_value=recover_plan,
                ),
                mock.patch("ethernity.workflows.rebuild.service.frames_from_scan", return_value=[]),
                mock.patch(
                    "ethernity.workflows.rebuild.service.recover_chain_entries",
                    return_value=chain,
                ),
            ):
                with self.assertRaises(ApiCommandError) as ctx:
                    execute_rebuild_operation(
                        RebuildOperationRequest(
                            root_dir=str(root_dir),
                            output_dir=str(output_dir),
                            shard_scan=["/separate/extension-shard-a.pdf"],
                            allow_stale_head=True,
                        )
                    )

        self.assertEqual(ctx.exception.code, api_codes.REBUILD_INVALID_POLICY)
        self.assertEqual(ctx.exception.details, {"stage": "source_shard_policy"})

    def test_run_rebuild_filters_mixed_unlock_shards_to_selected_head_policy(self) -> None:
        root_doc_id = b"\x22" * 8
        root_doc_hash = b"\x44" * 32
        extension_doc_hash = b"\x55" * 16 + b"\x66" * 16
        extension_doc_id = doc_id_from_doc_hash(extension_doc_hash)
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
            manifest=BackupManifest(
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
            output_dir = Path(tmpdir) / "rebuilt"
            with (
                mock.patch(
                    "ethernity.workflows.rebuild.service.plan_recover_from_args",
                    return_value=recover_plan,
                ),
                mock.patch("ethernity.workflows.rebuild.service.frames_from_scan", return_value=[]),
                mock.patch(
                    "ethernity.workflows.rebuild.service.recover_chain_entries",
                    return_value=chain,
                ),
                mock.patch(
                    "ethernity.workflows.rebuild.service.load_app_config",
                    return_value=SimpleNamespace(),
                ),
                mock.patch(
                    "ethernity.workflows.rebuild.service.apply_render_style",
                    side_effect=lambda config, _design: config,
                ),
                mock.patch(
                    "ethernity.workflows.rebuild.service.apply_qr_chunk_size_override",
                    side_effect=lambda config, _size: config,
                ),
                mock.patch(
                    "ethernity.workflows.rebuild.service.plan_backup_from_args",
                    return_value=SimpleNamespace(
                        sealed=True,
                        sharding=None,
                        signing_seed_mode="embedded",
                        signing_seed_sharding=None,
                    ),
                ) as plan_backup_from_args,
                mock.patch(
                    "ethernity.workflows.rebuild.service.run_backup",
                    return_value=_backup_result(),
                ),
            ):
                result = execute_rebuild_operation(
                    RebuildOperationRequest(
                        root_dir=str(root_dir),
                        output_dir=str(output_dir),
                        shard_scan=["/mixed/root-a.pdf", "/mixed/ext-a.pdf"],
                        allow_stale_head=True,
                    )
                )

        self.assertEqual(result.doc_id, b"\xaa" * 8)
        backup_args = plan_backup_from_args.call_args.args[0]
        self.assertEqual(backup_args.shard_threshold, 2)
        self.assertEqual(backup_args.shard_count, 3)
        self.assertTrue(backup_args.sealed)

    @mock.patch("ethernity.workflows.rebuild.service.run_backup")
    @mock.patch(
        "ethernity.workflows.rebuild.service.recover_chain_entries",
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
                "validated_head_root_signing_key_verified": None,
                "explicit_selection": False,
            },
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.plan_recover_from_args",
        return_value=SimpleNamespace(
            passphrase="secret",
            doc_id=b"\x22" * 16,
            doc_hash=b"\x44" * 32,
            auth_payload=None,
            shard_frames=(),
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service._validated_rebuild_root_dir",
        return_value=Path("/tmp/root"),
    )
    def test_run_rebuild_refuses_to_create_a_backup_from_an_untrusted_head(
        self,
        _validated_rebuild_root_dir: mock.MagicMock,
        _plan_recover_from_args: mock.MagicMock,
        _recover_chain_entries: mock.MagicMock,
        run_backup_mock: mock.MagicMock,
    ) -> None:
        with self.assertRaises(ApiCommandError) as ctx:
            execute_rebuild_operation(
                RebuildOperationRequest(
                    root_dir="/tmp/root",
                    output_dir="/tmp/out",
                    passphrase="secret",
                    allow_stale_head=True,
                )
            )

        exc = ctx.exception
        self.assertEqual(exc.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(
            str(exc),
            (
                "latest supplied rebuild head could not be trusted; no rebuilt backup was created: "
                "missing required MAIN documents"
            ),
        )
        self.assertEqual(exc.details["stage"], "replay")
        self.assertEqual(exc.details["failure_stage"], "discovery")
        self.assertEqual(exc.details["failure_head_index"], 2)
        self.assertEqual(exc.details["latest_head_index"], 2)
        self.assertEqual(exc.details["validated_head_index"], 0)
        self.assertFalse(exc.details["explicit_selection"])
        self.assertFalse(exc.details["backup_created"])
        self.assertIsNone(exc.details["failure_head_doc_hash"])
        self.assertIsNone(exc.details["latest_head_doc_hash"])
        run_backup_mock.assert_not_called()

    @mock.patch("ethernity.workflows.rebuild.service.run_backup")
    @mock.patch(
        "ethernity.workflows.rebuild.service.recover_chain_entries",
        side_effect=ApiCommandError(
            code=api_codes.ROOT_SIGNING_KEY_MISMATCH,
            message="embedded signing seed does not match the verified root AUTH signing key",
            details={"stage": "replay"},
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.plan_recover_from_args",
        return_value=SimpleNamespace(
            passphrase="secret",
            doc_id=b"\x22" * 16,
            doc_hash=b"\x44" * 32,
            auth_payload=None,
            shard_frames=(),
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service._validated_rebuild_root_dir",
        return_value=Path("/tmp/root"),
    )
    def test_run_rebuild_preserves_non_trust_api_command_errors(
        self,
        _validated_rebuild_root_dir: mock.MagicMock,
        _plan_recover_from_args: mock.MagicMock,
        _recover_chain_entries: mock.MagicMock,
        run_backup_mock: mock.MagicMock,
    ) -> None:
        with self.assertRaises(ApiCommandError) as ctx:
            execute_rebuild_operation(
                RebuildOperationRequest(
                    root_dir="/tmp/root",
                    output_dir="/tmp/out",
                    passphrase="secret",
                    allow_stale_head=True,
                )
            )

        exc = ctx.exception
        self.assertEqual(exc.code, api_codes.ROOT_SIGNING_KEY_MISMATCH)
        self.assertEqual(
            str(exc),
            "embedded signing seed does not match the verified root AUTH signing key",
        )
        self.assertEqual(exc.details, {"stage": "replay"})
        run_backup_mock.assert_not_called()

    @mock.patch("ethernity.workflows.rebuild.service.run_backup", return_value=_backup_result())
    @mock.patch(
        "ethernity.workflows.rebuild.service.plan_backup_from_args",
        return_value=SimpleNamespace(
            sealed=False,
            sharding=None,
            signing_seed_mode="embedded",
            signing_seed_sharding=None,
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.apply_qr_chunk_size_override",
        side_effect=lambda config, _size: config,
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.apply_render_style",
        side_effect=lambda config, _design: config,
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.load_app_config",
        return_value=SimpleNamespace(),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service._infer_recovery_sheet_settings",
        return_value=SimpleNamespace(
            passphrase_shard_threshold=2,
            passphrase_shard_count=3,
            signing_key_shard_threshold=2,
            signing_key_shard_count=3,
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.recover_chain_entries",
        return_value=SimpleNamespace(
            manifest=BackupManifest(
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
        "ethernity.workflows.rebuild.service.plan_recover_from_args",
        return_value=SimpleNamespace(
            passphrase="secret",
            doc_id=b"\x22" * 16,
            doc_hash=b"\x44" * 32,
            auth_payload=SimpleNamespace(sign_pub=b"\x55" * 32),
            shard_frames=(),
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service._validated_rebuild_root_dir",
        return_value=Path("/tmp/root"),
    )
    def test_run_rebuild_reuses_root_signing_seed_and_inherited_policy(
        self,
        _validated_rebuild_root_dir: mock.MagicMock,
        plan_recover_from_args: mock.MagicMock,
        recover_chain_entries: mock.MagicMock,
        _infer_recovery_sheet_settings: mock.MagicMock,
        load_app_config: mock.MagicMock,
        apply_render_style: mock.MagicMock,
        apply_qr_chunk_size_override: mock.MagicMock,
        plan_backup_from_args: mock.MagicMock,
        run_backup_mock: mock.MagicMock,
    ) -> None:
        result = execute_rebuild_operation(
            RebuildOperationRequest(
                root_dir="/tmp/root",
                output_dir="/tmp/out",
                passphrase="secret",
                shard_fallback_file=["shard-a.txt"],
                shard_payloads_file=["shard-a.payloads"],
                shard_scan=["shard-a.pdf"],
                auth_fallback_file="auth.txt",
                auth_payloads_file="auth.payloads",
                expected_head_doc_hash="ab" * 32,
            )
        )

        self.assertEqual(result.doc_id, b"\xaa" * 8)
        self.assertEqual(result.expected_head_doc_hash, "ab" * 32)
        self.assertEqual(result.doc_hash, b"\xaa" * 32)
        recover_args = plan_recover_from_args.call_args.args[0]
        self.assertIsInstance(recover_args, RecoverArgs)
        self.assertEqual(recover_args.scan, [str(Path("/tmp/root"))])
        self.assertEqual(recover_args.shard_fallback_file, ["shard-a.txt"])
        self.assertEqual(recover_args.shard_payloads_file, ["shard-a.payloads"])
        self.assertEqual(recover_args.shard_scan, ["shard-a.pdf"])
        self.assertEqual(recover_args.auth_fallback_file, "auth.txt")
        self.assertEqual(recover_args.auth_payloads_file, "auth.payloads")
        self.assertEqual(recover_args.expected_head_doc_hash, "ab" * 32)
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
            run_backup_mock.call_args.kwargs["render_origin"].kind,
            "rebuilt_backup",
        )
        self.assertNotIn("promote_lock_path", run_backup_mock.call_args.kwargs)
        self.assertNotIn("prepare_promotion", run_backup_mock.call_args.kwargs)
        self.assertNotIn("validate_promotion", run_backup_mock.call_args.kwargs)

    @mock.patch("ethernity.workflows.rebuild.service.run_backup", return_value=_backup_result())
    @mock.patch(
        "ethernity.workflows.rebuild.service.plan_backup_from_args",
        return_value=SimpleNamespace(
            sealed=False,
            sharding=None,
            signing_seed_mode="embedded",
            signing_seed_sharding=None,
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.apply_qr_chunk_size_override",
        side_effect=lambda config, _size: config,
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.apply_render_style",
        side_effect=lambda config, _design: config,
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.load_app_config",
        return_value=SimpleNamespace(),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service._infer_recovery_sheet_settings",
        return_value=SimpleNamespace(
            passphrase_shard_threshold=2,
            passphrase_shard_count=3,
            signing_key_shard_threshold=2,
            signing_key_shard_count=3,
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.recover_chain_entries",
        return_value=SimpleNamespace(
            manifest=BackupManifest(
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
        "ethernity.workflows.rebuild.service.plan_recover_from_args",
        return_value=SimpleNamespace(
            passphrase="secret",
            doc_id=b"\x22" * 16,
            doc_hash=b"\x44" * 32,
            auth_payload=None,
            shard_frames=(),
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service._validated_rebuild_root_dir",
        return_value=Path("/tmp/root"),
    )
    def test_run_rebuild_derives_public_key_from_manifest_seed_when_auth_missing(
        self,
        _validated_rebuild_root_dir: mock.MagicMock,
        _plan_recover_from_args: mock.MagicMock,
        _recover_chain_entries: mock.MagicMock,
        infer_recovery_sheet_settings: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_render_style: mock.MagicMock,
        _apply_qr_chunk_size_override: mock.MagicMock,
        _plan_backup_from_args: mock.MagicMock,
        _run_backup_mock: mock.MagicMock,
    ) -> None:
        result = execute_rebuild_operation(
            RebuildOperationRequest(
                root_dir="/tmp/root",
                output_dir="/tmp/out",
                passphrase="secret",
                allow_stale_head=True,
            )
        )

        self.assertEqual(result.doc_id, b"\xaa" * 8)
        self.assertEqual(
            infer_recovery_sheet_settings.call_args.kwargs["sign_pub"],
            derive_public_key(b"\x33" * 32),
        )
        self.assertNotIn("allow_unsigned", infer_recovery_sheet_settings.call_args.kwargs)

    @mock.patch("ethernity.workflows.rebuild.service.run_backup", return_value=_backup_result())
    @mock.patch(
        "ethernity.workflows.rebuild.service.plan_backup_from_args",
        return_value=SimpleNamespace(
            sealed=True,
            sharding=None,
            signing_seed_mode="embedded",
            signing_seed_sharding=None,
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.apply_qr_chunk_size_override",
        side_effect=lambda config, _size: config,
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.apply_render_style",
        side_effect=lambda config, _design: config,
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.load_app_config",
        return_value=SimpleNamespace(),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service._infer_recovery_sheet_settings",
        return_value=SimpleNamespace(
            passphrase_shard_threshold=None,
            passphrase_shard_count=0,
            signing_key_shard_threshold=None,
            signing_key_shard_count=0,
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service.recover_chain_entries",
        return_value=SimpleNamespace(
            manifest=BackupManifest(
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
        "ethernity.workflows.rebuild.service.plan_recover_from_args",
        return_value=SimpleNamespace(
            passphrase="secret",
            doc_id=b"\x22" * 16,
            doc_hash=b"\x44" * 32,
            auth_payload=None,
            shard_frames=(),
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service._validated_rebuild_root_dir",
        return_value=Path("/tmp/root"),
    )
    def test_run_rebuild_allows_sealed_rescue_flow_without_root_auth(
        self,
        _validated_rebuild_root_dir: mock.MagicMock,
        _plan_recover_from_args: mock.MagicMock,
        _recover_chain_entries: mock.MagicMock,
        infer_recovery_sheet_settings: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_render_style: mock.MagicMock,
        _apply_qr_chunk_size_override: mock.MagicMock,
        _plan_backup_from_args: mock.MagicMock,
        run_backup_mock: mock.MagicMock,
    ) -> None:
        result = execute_rebuild_operation(
            RebuildOperationRequest(
                root_dir="/tmp/root",
                output_dir="/tmp/out",
                passphrase="secret",
                allow_stale_head=True,
            )
        )

        self.assertEqual(result.doc_id, b"\xaa" * 8)
        self.assertIsNone(infer_recovery_sheet_settings.call_args.kwargs["sign_pub"])
        self.assertNotIn("allow_unsigned", infer_recovery_sheet_settings.call_args.kwargs)
        backup_args = _plan_backup_from_args.call_args.args[0]
        self.assertIsNone(backup_args.shard_threshold)
        self.assertIsNone(backup_args.shard_count)
        self.assertIsNone(run_backup_mock.call_args.kwargs["signing_seed_override"])

    @mock.patch(
        "ethernity.workflows.rebuild.service.recover_chain_entries",
        return_value=SimpleNamespace(
            manifest=BackupManifest(
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
        "ethernity.workflows.rebuild.service.plan_recover_from_args",
        return_value=SimpleNamespace(
            passphrase="secret",
            doc_id=b"\x22" * 16,
            doc_hash=b"\x44" * 32,
            auth_payload=SimpleNamespace(sign_pub=b"\x55" * 32),
            shard_frames=(),
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service._infer_recovery_sheet_settings",
        return_value=SimpleNamespace(
            passphrase_shard_threshold=None,
            passphrase_shard_count=0,
            signing_key_shard_threshold=2,
            signing_key_shard_count=3,
        ),
    )
    @mock.patch(
        "ethernity.workflows.rebuild.service._validated_rebuild_root_dir",
        return_value=Path("/tmp/root"),
    )
    def test_run_rebuild_rejects_invalid_inherited_signing_key_shard_policy(
        self,
        _validated_rebuild_root_dir: mock.MagicMock,
        _infer_recovery_sheet_settings: mock.MagicMock,
        _plan_recover_from_args: mock.MagicMock,
        _recover_chain_entries: mock.MagicMock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "signing-key shards require passphrase shards"):
            execute_rebuild_operation(
                RebuildOperationRequest(
                    root_dir="/tmp/root",
                    output_dir="/tmp/out",
                    passphrase="secret",
                    allow_stale_head=True,
                )
            )
