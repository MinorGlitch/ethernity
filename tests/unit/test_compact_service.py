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

from ethernity.cli.features.compact.service import run_compact
from ethernity.cli.shared.types import CompactArgs, RecoverArgs
from ethernity.crypto.signing import derive_public_key
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile


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

    def test_run_compact_rejects_root_dir_without_main_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            with self.assertRaisesRegex(
                ValueError,
                (
                    "backup root folder \\(backup root directory\\) "
                    "does not contain a root MAIN carrier"
                ),
            ):
                run_compact(
                    CompactArgs(
                        root_dir=str(root_dir),
                        output_dir="/tmp/out",
                        passphrase="secret",
                        quiet=True,
                    )
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
            auth_payload=SimpleNamespace(sign_pub=b"\x55" * 32),
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
        self.assertEqual(
            run_backup_mock.call_args.kwargs["render_lineage"].kind,
            "compaction_checkpoint",
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
        self.assertFalse(infer_root_publish_policy.call_args.kwargs["allow_unsigned"])

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
            passphrase_shard_threshold=2,
            passphrase_shard_count=3,
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
        self.assertTrue(infer_root_publish_policy.call_args.kwargs["allow_unsigned"])
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
