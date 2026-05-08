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

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from fpdf import FPDF

from ethernity.cli.features.extend.main_carrier_validation import (
    validate_single_main_carrier as _validate_single_main_carrier,
    validate_staged_recovery_kit_index_document as _validate_staged_recovery_kit_index_document,
)
from ethernity.cli.features.extend.models import (
    ExtensionPassphraseShards,
    ExtensionSigningKeyShards,
    ReuseRootPassphraseShards,
)
from ethernity.cli.features.extend.planning import ExtendInspection, ResolvedExtendState
from ethernity.cli.features.extend.runtime import resolve_extend_policy
from ethernity.cli.features.extend.scope import SelectedExtendScope
from ethernity.cli.features.extend.service import (
    EXTENSION_INPUT_REQUIRED,
    EXTENSION_INVALID_POLICY,
    EXTENSION_MAIN_CARRIER_INVALID,
    EXTENSION_NO_CHANGES,
    EXTENSION_SHARD_CARRIER_INVALID,
    assemble_prepared_extension_document,
    encrypt_prepared_extension_document,
    execute_staged_extension_publish,
    prepare_extend_run,
    prepare_staged_extension_publish,
    resolve_extend_runtime,
    run_extend,
)
from ethernity.cli.features.extend.shard_validation import (
    validate_rendered_shard_carrier as _validate_rendered_shard_carrier,
)
from ethernity.cli.shared.constants import AUTH_FALLBACK_LABEL
from ethernity.cli.shared.crypto import _doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import ExtendArgs, InputFile
from ethernity.config import BackupDefaults
from ethernity.crypto.sharding import ShardPayload, encode_shard_payload
from ethernity.crypto.signing import AuthPayload, derive_public_key
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.extensions.staging import ExtensionPublishPolicy
from ethernity.formats.extension_envelope import ExtensionChunkingProfile
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC


def _inspection(
    *,
    diff_summary: dict[str, object] | None,
    blocking_issues: tuple[dict[str, object], ...] = (),
) -> ExtendInspection:
    return ExtendInspection(
        doc_id="deadbeef",
        root_dir="/tmp/root",
        input_label="Backup root directory",
        input_detail="/tmp/root",
        input_kind="standalone_root",
        source_summary=None,
        frame_counts={"main": 0, "auth": 0, "shard": 0},
        root_doc_id="deadbeef",
        root_doc_hash="cafebabe",
        chain_id="feedface",
        auth_status="verified",
        unlock={
            "mode": "passphrase",
            "passphrase_provided": True,
            "validated_shard_count": 0,
            "required_shard_threshold": None,
            "shard_share_count": None,
            "satisfied": True,
        },
        discovered_extension_dirs=(),
        validated_head_index=0,
        validated_head_doc_hash="cafebabe",
        available_extensions=(),
        validated_head_auth_status=None,
        validated_head_root_authority_verified=None,
        ancestry_valid=True,
        signing_authority={"available": True, "satisfied": True, "source": "embedded_seed"},
        selected_scope={"files": ["/tmp/root/example.txt"], "directories": [], "base_dir": "/tmp"},
        diff_summary=diff_summary,
        blocking_issues=blocking_issues,
    )


def _resolved_state(
    *,
    diff_summary: dict[str, object] | None,
    blocking_issues: tuple[dict[str, object], ...] = (),
    root_passphrase_shard_threshold: int | None = None,
    root_passphrase_shard_count: int = 0,
) -> ResolvedExtendState:
    scope = SelectedExtendScope(
        raw_files=("/tmp/root/example.txt",),
        raw_directories=(),
        base_dir_arg="/tmp/root",
        input_files=(
            InputFile(
                source_path=None,
                relative_path="updated.txt",
                data=b"updated",
                mtime=1,
            ),
            InputFile(
                source_path=None,
                relative_path="new.txt",
                data=b"new",
                mtime=2,
            ),
        ),
        base_dir=None,
        input_origin="file",
        input_roots=(),
        exact_paths=("updated.txt", "new.txt"),
        directory_prefixes=(),
    )
    return ResolvedExtendState(
        inspection=_inspection(diff_summary=diff_summary, blocking_issues=blocking_issues),
        loaded_scope=scope,
        current_state=(),
        resolved_passphrase="secret",
        root_doc_hash=b"\x22" * 32,
        parent_doc_hash=b"\x11" * 32,
        next_index=2,
        signing_seed=b"\x33" * 32,
        chunking=ExtensionChunkingProfile(
            algorithm_id=CHUNK_ALGORITHM_FASTCDC,
            target_size=64 * 1024,
            min_size=16 * 1024,
            max_size=256 * 1024,
        ),
        root_passphrase_shard_threshold=root_passphrase_shard_threshold,
        root_passphrase_shard_count=root_passphrase_shard_count,
    )


def _shard_payload(
    *,
    share_index: int,
    threshold: int,
    share_count: int,
    key_type: str,
    doc_hash: bytes = b"\x22" * 32,
    sign_pub: bytes = b"\x44" * 32,
) -> ShardPayload:
    return ShardPayload(
        share_index=share_index,
        threshold=threshold,
        share_count=share_count,
        key_type=key_type,
        share=bytes([share_index]) * 16,
        secret_len=8,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        signature=b"\x55" * 64,
        shard_set_id=b"\x66" * 16,
    )


def _config_with_no_shard_defaults(path: Path) -> Path:
    path.write_text('[defaults.backup]\nqr_payload_codec = "raw"\n', encoding="utf-8")
    return path


class TestExtendService(unittest.TestCase):
    def test_prepare_extend_run_requires_explicit_scope(self) -> None:
        with self.assertRaises(ApiCommandError) as ctx:
            prepare_extend_run(ExtendArgs(root_dir="/tmp/root"))
        self.assertEqual(ctx.exception.code, EXTENSION_INPUT_REQUIRED)

    def test_prepare_extend_run_surfaces_first_blocking_issue(self) -> None:
        with mock.patch(
            "ethernity.cli.features.extend.prepare.resolve_extend_state",
            return_value=_resolved_state(
                diff_summary=None,
                blocking_issues=(
                    {
                        "code": "SEALED_ROOT_NOT_EXTENDABLE",
                        "message": "sealed roots are terminal in v1 and cannot be extended",
                        "details": {},
                    },
                ),
            ),
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                prepare_extend_run(
                    ExtendArgs(root_dir="/tmp/root", input=["/tmp/root/example.txt"])
                )
        self.assertEqual(ctx.exception.code, "SEALED_ROOT_NOT_EXTENDABLE")

    def test_prepare_extend_run_preserves_recovery_head_untrusted_details(self) -> None:
        trust_details = {
            "stage": "replay",
            "failure_stage": "discovery",
            "failure_message": "missing required payload MAIN carriers",
            "failure_head_index": 2,
            "failure_head_doc_hash": None,
            "failure_head_dir_name": "02",
            "latest_head_index": 2,
            "latest_head_doc_hash": None,
            "latest_head_dir_name": "02",
            "requested_head_index": None,
            "requested_head_doc_hash": None,
            "validated_head_index": 1,
            "validated_head_doc_hash": "aa" * 32,
            "validated_head_auth_status": "verified",
            "validated_head_root_authority_verified": True,
            "explicit_selection": False,
        }

        with mock.patch(
            "ethernity.cli.features.extend.prepare.resolve_extend_state",
            return_value=_resolved_state(
                diff_summary=None,
                blocking_issues=(
                    {
                        "code": "RECOVERY_HEAD_UNTRUSTED",
                        "message": (
                            "latest recovery head could not be trusted: "
                            "missing required payload MAIN carriers"
                        ),
                        "details": trust_details,
                    },
                ),
            ),
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                prepare_extend_run(
                    ExtendArgs(root_dir="/tmp/root", input=["/tmp/root/example.txt"])
                )

        self.assertEqual(ctx.exception.code, "RECOVERY_HEAD_UNTRUSTED")
        self.assertEqual(
            str(ctx.exception),
            "latest recovery head could not be trusted: missing required payload MAIN carriers",
        )
        self.assertEqual(ctx.exception.details, trust_details)

    def test_prepare_extend_run_rejects_noop_diffs(self) -> None:
        with mock.patch(
            "ethernity.cli.features.extend.prepare.resolve_extend_state",
            return_value=_resolved_state(
                diff_summary={
                    "new_paths": [],
                    "changed_paths": [],
                    "unchanged_paths": ["example.txt"],
                    "missing_paths": [],
                },
            ),
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                prepare_extend_run(
                    ExtendArgs(root_dir="/tmp/root", input=["/tmp/root/example.txt"])
                )
        self.assertEqual(ctx.exception.code, EXTENSION_NO_CHANGES)

    def test_prepare_extend_run_returns_changed_and_new_paths(self) -> None:
        with mock.patch(
            "ethernity.cli.features.extend.prepare.resolve_extend_state",
            return_value=_resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": ["same.txt"],
                    "missing_paths": [],
                },
            ),
        ):
            prepared = prepare_extend_run(
                ExtendArgs(root_dir="/tmp/root", input=["/tmp/root/example.txt"])
            )

        self.assertEqual(prepared.next_index, 2)
        self.assertEqual(prepared.new_paths, ("new.txt",))
        self.assertEqual(prepared.changed_paths, ("updated.txt",))
        self.assertEqual(prepared.unchanged_paths, ("same.txt",))

    def test_resolve_extend_policy_applies_backup_defaults_for_self_contained(self) -> None:
        policy = resolve_extend_policy(
            args=ExtendArgs(),
            defaults=BackupDefaults(
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
            root_passphrase_shard_threshold=None,
            root_passphrase_shard_count=0,
            require_recovery_kit_index=True,
        )

        self.assertEqual(
            policy.passphrase,
            ExtensionPassphraseShards(threshold=2, share_count=3),
        )
        self.assertEqual(
            policy.signing_key,
            ExtensionSigningKeyShards(threshold=2, share_count=3),
        )
        self.assertTrue(policy.require_recovery_kit_index)
        self.assertEqual(policy.to_publish_policy().passphrase_shard_count, 3)
        self.assertEqual(policy.to_publish_policy().signing_key_shard_count, 3)

    def test_resolve_extend_policy_uses_validated_unlock_policy_for_reuse_root(self) -> None:
        policy = resolve_extend_policy(
            args=ExtendArgs(unlock_policy="reuse-root"),
            defaults=BackupDefaults(
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
            root_passphrase_shard_threshold=2,
            root_passphrase_shard_count=2,
            require_recovery_kit_index=True,
        )

        self.assertEqual(
            policy.passphrase,
            ReuseRootPassphraseShards(threshold=2, share_count=2),
        )
        self.assertEqual(policy.to_publish_policy().passphrase_shard_count, 0)
        self.assertEqual(policy.to_publish_policy().signing_key_shard_count, 0)
        self.assertTrue(policy.require_recovery_kit_index)

    def test_run_extend_fails_closed_before_artifact_creation_on_untrusted_latest_head(
        self,
    ) -> None:
        trust_details = {
            "stage": "replay",
            "failure_stage": "discovery",
            "failure_message": "missing required payload MAIN carriers",
            "failure_head_index": 2,
            "failure_head_doc_hash": None,
            "failure_head_dir_name": "02",
            "latest_head_index": 2,
            "latest_head_doc_hash": None,
            "latest_head_dir_name": "02",
            "requested_head_index": None,
            "requested_head_doc_hash": None,
            "validated_head_index": 1,
            "validated_head_doc_hash": "aa" * 32,
            "validated_head_auth_status": "verified",
            "validated_head_root_authority_verified": True,
            "explicit_selection": False,
        }

        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            existing_head = root_dir / "extensions" / "01"
            existing_head.mkdir(parents=True)
            (existing_head / "keep.txt").write_text("keep", encoding="utf-8")

            with mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=_resolved_state(
                    diff_summary=None,
                    blocking_issues=(
                        {
                            "code": "RECOVERY_HEAD_UNTRUSTED",
                            "message": (
                                "latest recovery head could not be trusted: "
                                "missing required payload MAIN carriers"
                            ),
                            "details": trust_details,
                        },
                    ),
                ),
            ):
                with self.assertRaises(ApiCommandError) as ctx:
                    run_extend(
                        ExtendArgs(
                            root_dir=str(root_dir),
                            input=["/tmp/root/example.txt"],
                        ),
                        chunker=lambda data, _profile: (data,),
                        nonce="abc123",
                    )

        self.assertEqual(ctx.exception.code, "RECOVERY_HEAD_UNTRUSTED")
        self.assertEqual(ctx.exception.details, trust_details)
        self.assertFalse((root_dir / "extensions" / "02").exists())
        self.assertEqual(list((root_dir / "extensions").glob(".staging-*")), [])

    def test_assemble_prepared_extension_document_uses_changed_and_new_paths(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )
        with mock.patch(
            "ethernity.cli.features.extend.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtendArgs(root_dir="/tmp/root", input=["/tmp/root/example.txt"])
            )
            built = assemble_prepared_extension_document(
                prepared,
                chunker=lambda data, _profile: (data,),
            )

        self.assertEqual(built.document.header.index, 2)
        self.assertEqual(built.document.header.parent_doc_hash, b"\x11" * 32)
        self.assertEqual(built.document.header.root_doc_hash, b"\x22" * 32)
        self.assertFalse(hasattr(built.document.header, "parent_index"))
        self.assertFalse(hasattr(built.document.header, "signing_seed"))
        self.assertEqual([item.path for item in built.document.files], ["new.txt", "updated.txt"])

    def test_encrypt_prepared_extension_document_returns_ciphertext_and_ids(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )
        with mock.patch(
            "ethernity.cli.features.extend.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtendArgs(root_dir="/tmp/root", input=["/tmp/root/example.txt"])
            )
            with mock.patch(
                "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
            ):
                encrypted = encrypt_prepared_extension_document(
                    prepared,
                    chunker=lambda data, _profile: (data,),
                )
        expected_doc_id, expected_doc_hash = _doc_id_and_hash_from_ciphertext(encrypted.ciphertext)
        self.assertEqual(encrypted.ciphertext[:4], b"enc:")
        self.assertEqual(encrypted.doc_id, expected_doc_id)
        self.assertEqual(encrypted.doc_hash, expected_doc_hash)
        self.assertEqual(encrypted.built.document.header.index, 2)

    def test_prepare_staged_extension_publish_plans_canonical_targets(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
                root_passphrase_shard_threshold=1,
                root_passphrase_shard_count=1,
            )
            with mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtendArgs(root_dir=str(root_dir), input=["/tmp/root/example.txt"])
                )
                with mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: (data,),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(
                            require_recovery_kit_index=True,
                            passphrase_shard_count=2,
                            signing_key_shard_count=1,
                        ),
                    )

        self.assertEqual(publish.encrypted.built.document.header.index, 2)
        self.assertEqual(publish.artifacts.staging_dir.name, ".staging-2-abc123")
        self.assertEqual(publish.artifacts.final_dir.name, "02")
        expected_qr_path = (
            root_dir
            / "extensions"
            / ".staging-2-abc123"
            / f"qr_document-02-{publish.encrypted.doc_id.hex()}.pdf"
        )
        self.assertEqual(
            publish.artifacts.qr_document_path,
            expected_qr_path,
        )
        self.assertEqual(
            publish.artifacts.recovery_document_path.name,
            f"recovery_document-02-{publish.encrypted.doc_id.hex()}.pdf",
        )
        self.assertEqual(
            publish.artifacts.recovery_kit_index_path.name
            if publish.artifacts.recovery_kit_index_path
            else None,
            f"recovery_kit_index-02-{publish.encrypted.doc_id.hex()}.pdf",
        )
        self.assertEqual(
            [path.name for path in publish.artifacts.shard_paths],
            [
                f"shard-02-{publish.encrypted.doc_id.hex()}-1-of-2.pdf",
                f"shard-02-{publish.encrypted.doc_id.hex()}-2-of-2.pdf",
            ],
        )
        self.assertEqual(
            [path.name for path in publish.artifacts.signing_key_shard_paths],
            [f"signing-key-shard-02-{publish.encrypted.doc_id.hex()}-1-of-1.pdf"],
        )

    def test_execute_staged_extension_publish_promotes_valid_artifacts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtendArgs(root_dir=str(root_dir), input=["/tmp/root/example.txt"])
                )
                with mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: (data,),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(
                            require_recovery_kit_index=True,
                            passphrase_shard_count=2,
                        ),
                    )

            def _renderer(plan) -> None:
                plan.artifacts.qr_document_path.write_bytes(b"qr")
                plan.artifacts.recovery_document_path.write_bytes(b"recovery")
                if plan.artifacts.recovery_kit_index_path is not None:
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Helvetica", size=12)
                    pdf.multi_cell(
                        w=0,
                        text="\n".join(
                            [
                                "Recovery Kit Index",
                                "QR-DOC-01",
                                "RECOVERY-DOC-01",
                                "SHARD-01",
                                "SHARD-02",
                            ]
                        ),
                    )
                    pdf.output(str(plan.artifacts.recovery_kit_index_path))
                for path in plan.artifacts.shard_paths:
                    path.write_bytes(b"shard")

            result = execute_staged_extension_publish(
                publish,
                renderer=_renderer,
                post_validate=lambda _plan, _result: None,
            )

            self.assertEqual(result.index, 2)
            self.assertEqual(result.final_dir.name, "02")
            self.assertTrue(result.qr_document_path.exists())
            self.assertTrue(result.recovery_document_path.exists())
            self.assertTrue(result.recovery_kit_index_path.exists())
            self.assertEqual(
                [path.name for path in result.shard_paths],
                [
                    f"shard-02-{publish.encrypted.doc_id.hex()}-1-of-2.pdf",
                    f"shard-02-{publish.encrypted.doc_id.hex()}-2-of-2.pdf",
                ],
            )
            self.assertFalse((root_dir / "extensions" / ".staging-2-abc123").exists())

    def test_validate_staged_recovery_kit_index_document_rejects_invalid_pdf(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtendArgs(root_dir=str(root_dir), input=["/tmp/root/example.txt"])
                )
                with mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: (data,),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(require_recovery_kit_index=True),
                    )

            assert publish.artifacts.recovery_kit_index_path is not None
            publish.artifacts.recovery_kit_index_path.write_bytes(b"not-a-pdf")

            with self.assertRaises(ApiCommandError) as ctx:
                _validate_staged_recovery_kit_index_document(publish)

            self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
            self.assertIn("recovery_kit_index artifact is invalid", str(ctx.exception))

    def test_validate_staged_recovery_kit_index_document_accepts_valid_pdf(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtendArgs(root_dir=str(root_dir), input=["/tmp/root/example.txt"])
                )
                with mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: (data,),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(require_recovery_kit_index=True),
                    )

            assert publish.artifacts.recovery_kit_index_path is not None
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            pdf.multi_cell(
                w=0,
                text="\n".join(
                    [
                        "Recovery Kit Index",
                        publish.encrypted.doc_id.hex(),
                        "Extension 02",
                        "QR-DOC-01",
                        "RECOVERY-DOC-01",
                    ]
                ),
            )
            pdf.output(str(publish.artifacts.recovery_kit_index_path))

            _validate_staged_recovery_kit_index_document(publish)

    def test_validate_staged_recovery_kit_index_document_rejects_wrong_doc_identity(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtendArgs(root_dir=str(root_dir), input=["/tmp/root/example.txt"])
                )
                with mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: (data,),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(require_recovery_kit_index=True),
                    )

            assert publish.artifacts.recovery_kit_index_path is not None
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            pdf.multi_cell(
                w=0,
                text="\n".join(
                    [
                        "Recovery Kit Index",
                        "wrong-doc-id",
                        "Extension 02",
                        "QR-DOC-01",
                        "RECOVERY-DOC-01",
                    ]
                ),
            )
            pdf.output(str(publish.artifacts.recovery_kit_index_path))

            with self.assertRaises(ApiCommandError) as ctx:
                _validate_staged_recovery_kit_index_document(publish)

            self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
            self.assertIn("missing expected inventory rows", str(ctx.exception))

    def test_validate_staged_recovery_kit_index_document_rejects_missing_inventory_rows(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtendArgs(root_dir=str(root_dir), input=["/tmp/root/example.txt"])
                )
                with mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: (data,),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(require_recovery_kit_index=True),
                    )

            assert publish.artifacts.recovery_kit_index_path is not None
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            pdf.cell(text="Recovery Kit Index")
            pdf.output(str(publish.artifacts.recovery_kit_index_path))

            with self.assertRaises(ApiCommandError) as ctx:
                _validate_staged_recovery_kit_index_document(publish)

            self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
            self.assertIn("missing expected inventory rows", str(ctx.exception))

    def test_execute_staged_extension_publish_discards_failed_staging_dir(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtendArgs(root_dir=str(root_dir), input=["/tmp/root/example.txt"])
                )
                with mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: (data,),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(),
                    )

            def _renderer(plan) -> None:
                plan.artifacts.qr_document_path.write_bytes(b"qr-only")

            with self.assertRaisesRegex(ValueError, "missing required MAIN artifacts"):
                execute_staged_extension_publish(
                    publish,
                    renderer=_renderer,
                    post_validate=lambda _plan, _result: None,
                )

            self.assertFalse(publish.artifacts.staging_dir.exists())

    def test_execute_staged_extension_publish_rejects_post_validation_file_swap(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtendArgs(root_dir=str(root_dir), input=["/tmp/root/example.txt"])
                )
                with mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: (data,),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(),
                    )

            def _renderer(plan) -> None:
                plan.artifacts.qr_document_path.write_bytes(b"qr")
                plan.artifacts.recovery_document_path.write_bytes(b"recovery")

            def _post_validate(plan, _render_result) -> None:
                plan.artifacts.qr_document_path.write_bytes(b"swapped regular file")

            with self.assertRaisesRegex(ValueError, "artifacts changed before promotion"):
                execute_staged_extension_publish(
                    publish,
                    renderer=_renderer,
                    post_validate=_post_validate,
                )

            self.assertFalse(publish.artifacts.staging_dir.exists())

    def test_run_extend_promotes_rendered_extension_with_validated_unlock_shards(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            existing_head = root_dir / "extensions" / "01"
            existing_head.mkdir(parents=True)
            (existing_head / "qr_document-01-existing.pdf").write_bytes(b"existing")
            (root_dir / "recovery_kit_index.pdf").write_bytes(b"root-index")
            config_path = _config_with_no_shard_defaults(Path(tmpdir) / "config.toml")

            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
                root_passphrase_shard_threshold=2,
                root_passphrase_shard_count=2,
            )
            rendered_inputs: dict[str, object] = {}
            shard_frames_by_path: dict[str, list[Frame]] = {}
            main_frames_by_path: dict[str, list[Frame]] = {}
            auth_frame: Frame | None = None

            def _fake_render(inputs) -> None:
                nonlocal auth_frame
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                rendered_inputs[output_path.name] = inputs
                if output_path.name.startswith("recovery_kit_index-"):
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Helvetica", size=12)
                    pdf.multi_cell(
                        w=0,
                        text="\n".join(
                            [
                                "Recovery Kit Index",
                                inputs.frames[0].doc_id.hex(),
                                "Extension 02",
                                "QR-DOC-01",
                                "RECOVERY-DOC-01",
                                "SHARD-01",
                                "SHARD-02",
                                "SIGNING-SHARD-01",
                            ]
                        ),
                    )
                    pdf.output(str(output_path))
                else:
                    output_path.write_bytes(output_path.name.encode("utf-8"))
                if output_path.name.startswith(("qr_document-", "recovery_document-")):
                    main_frames_by_path[str(output_path)] = list(inputs.frames)
                if output_path.name.startswith("qr_document-"):
                    auth_frame = next(
                        (frame for frame in inputs.frames if frame.frame_type == FrameType.AUTH),
                        None,
                    )
                if output_path.name.startswith(("shard-", "signing-key-shard-")):
                    shard_frames_by_path[str(output_path)] = list(inputs.frames)

            def _scan_main_carrier(paths, **_kwargs):
                frames = list(main_frames_by_path[str(paths[0])])
                if (
                    auth_frame is not None
                    and Path(paths[0]).name.startswith("recovery_document-")
                    and not any(frame.frame_type == FrameType.AUTH for frame in frames)
                ):
                    frames.append(auth_frame)
                return frames

            with (
                mock.patch(
                    "ethernity.cli.features.extend.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.shard_validation._shard_frames_from_scan",
                    side_effect=lambda paths, **_kwargs: shard_frames_by_path[str(paths[0])],
                ),
                mock.patch(
                    "ethernity.cli.features.extend.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.main_carrier_validation._recovery_frames_from_scan",
                    side_effect=_scan_main_carrier,
                ),
            ):
                result = run_extend(
                    ExtendArgs(
                        config=str(config_path),
                        root_dir=str(root_dir),
                        input=["/tmp/root/example.txt"],
                        signing_key_mode="sharded",
                        signing_key_shard_threshold=1,
                        signing_key_shard_count=1,
                    ),
                    chunker=lambda data, _profile: (data,),
                    nonce="abc123",
                )

            self.assertEqual(result.final_dir.name, "02")
            self.assertTrue(result.qr_document_path.exists())
            self.assertTrue(result.recovery_document_path.exists())
            self.assertEqual(len(result.shard_paths), 2)
            self.assertEqual(len(result.signing_key_shard_paths), 1)
            self.assertIsNotNone(result.recovery_kit_index_path)
            self.assertTrue(existing_head.exists())
            self.assertFalse((root_dir / "extensions" / ".staging-2-abc123").exists())
            qr_inputs = rendered_inputs[result.qr_document_path.name]
            recovery_inputs = rendered_inputs[result.recovery_document_path.name]
            kit_index_inputs = rendered_inputs[result.recovery_kit_index_path.name]
            self.assertEqual(qr_inputs.lineage.kind, "extension")
            self.assertEqual(qr_inputs.lineage.extension_index, 2)
            self.assertEqual(recovery_inputs.lineage.kind, "extension")
            self.assertEqual(kit_index_inputs.lineage.kind, "extension")
            self.assertEqual(
                sum(1 for frame in qr_inputs.frames if frame.frame_type == FrameType.AUTH),
                1,
            )
            self.assertEqual(
                sum(1 for frame in kit_index_inputs.frames if frame.frame_type == FrameType.AUTH),
                1,
            )
            self.assertEqual(len(kit_index_inputs.frames), len(qr_inputs.frames))
            self.assertEqual(
                [section.label for section in recovery_inputs.fallback_sections or ()],
                [AUTH_FALLBACK_LABEL, "Main Frame"],
            )

    def test_run_extend_keeps_previous_head_when_main_validation_fails(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            existing_head = root_dir / "extensions" / "01"
            existing_head.mkdir(parents=True)
            marker = existing_head / "keep.txt"
            marker.write_text("keep", encoding="utf-8")

            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            captured: dict[str, list[Frame]] = {}

            def _fake_render(inputs) -> None:
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(output_path.name.encode("utf-8"))
                if output_path.name.startswith(("qr_document-", "recovery_document-")):
                    captured["frames"] = list(inputs.frames)

            with (
                mock.patch(
                    "ethernity.cli.features.extend.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.main_carrier_validation._recovery_frames_from_scan",
                    side_effect=lambda *_args, **_kwargs: [
                        Frame(
                            version=VERSION,
                            frame_type=FrameType.MAIN_DOCUMENT,
                            doc_id=captured["frames"][0].doc_id,
                            index=0,
                            total=1,
                            data=b"wrong",
                        ),
                    ],
                ),
            ):
                with self.assertRaises(ApiCommandError) as ctx:
                    run_extend(
                        ExtendArgs(
                            root_dir=str(root_dir),
                            input=["/tmp/root/example.txt"],
                        ),
                        chunker=lambda data, _profile: (data,),
                        nonce="abc123",
                    )

            self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
            self.assertTrue(existing_head.exists())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertFalse((root_dir / "extensions" / "02").exists())
            self.assertFalse((root_dir / "extensions" / ".staging-2-abc123").exists())

    def test_run_extend_keeps_previous_head_when_shard_validation_fails(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            existing_head = root_dir / "extensions" / "01"
            existing_head.mkdir(parents=True)
            marker = existing_head / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            (root_dir / "shard-root-1.pdf").write_bytes(b"root-shard-1")

            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            captured: dict[str, list[Frame]] = {}

            def _fake_render(inputs) -> None:
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(output_path.name.encode("utf-8"))
                if output_path.name.startswith(("qr_document-", "recovery_document-")):
                    captured["frames"] = list(inputs.frames)

            invalid_payload = _shard_payload(
                share_index=1,
                threshold=1,
                share_count=1,
                key_type="passphrase",
                doc_hash=b"\x99" * 32,
            )
            invalid_frame = Frame(
                version=VERSION,
                frame_type=FrameType.KEY_DOCUMENT,
                doc_id=b"\x00" * 16,
                index=0,
                total=1,
                data=encode_shard_payload(invalid_payload),
            )

            with (
                mock.patch(
                    "ethernity.cli.features.extend.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.shard_validation._shard_frames_from_scan",
                    return_value=[invalid_frame],
                ),
                mock.patch(
                    "ethernity.cli.features.extend.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.main_carrier_validation._recovery_frames_from_scan",
                    side_effect=lambda *_args, **_kwargs: list(captured["frames"]),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.main_carrier_validation._resolve_auth_payload",
                    return_value=(
                        AuthPayload(
                            version=1,
                            doc_hash=b"\x22" * 32,
                            sign_pub=derive_public_key(resolved.signing_seed),
                            signature=b"\x77" * 64,
                        ),
                        "verified",
                    ),
                ),
            ):
                with self.assertRaises(ApiCommandError) as ctx:
                    run_extend(
                        ExtendArgs(
                            root_dir=str(root_dir),
                            input=["/tmp/root/example.txt"],
                        ),
                        chunker=lambda data, _profile: (data,),
                        nonce="abc123",
                    )

            self.assertEqual(ctx.exception.code, EXTENSION_SHARD_CARRIER_INVALID)
            self.assertTrue(existing_head.exists())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertFalse((root_dir / "extensions" / "02").exists())
            self.assertFalse((root_dir / "extensions" / ".staging-2-abc123").exists())

    def test_validate_rendered_shard_carrier_rejects_invalid_signature(self) -> None:
        path = Path("/tmp/shard-01-deadbeef-1-of-1.pdf")
        expected_doc_id = b"\x22" * 16
        expected_doc_hash = b"\x33" * 32
        expected_payload = _shard_payload(
            share_index=1,
            threshold=1,
            share_count=1,
            key_type="passphrase",
            doc_hash=expected_doc_hash,
        )
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=expected_doc_id,
            index=0,
            total=1,
            data=encode_shard_payload(expected_payload),
        )

        with (
            mock.patch(
                "ethernity.cli.features.extend.shard_validation._shard_frames_from_scan",
                return_value=[frame],
            ),
            mock.patch(
                "ethernity.cli.features.extend.shard_validation.verify_shard",
                return_value=False,
            ),
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                _validate_rendered_shard_carrier(
                    path=path,
                    expected_payload=expected_payload,
                    expected_doc_id=expected_doc_id,
                    expected_doc_hash=expected_doc_hash,
                    quiet=True,
                    secret_label="passphrase shard",
                )

        self.assertEqual(ctx.exception.code, EXTENSION_SHARD_CARRIER_INVALID)
        self.assertIn("signature verification failed", str(ctx.exception))

    def test_run_extend_reuse_root_unlock_policy_emits_no_extension_shards(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            existing_head = root_dir / "extensions" / "01"
            existing_head.mkdir(parents=True)

            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
                root_passphrase_shard_threshold=2,
                root_passphrase_shard_count=2,
            )
            captured: dict[str, list[Frame]] = {}
            rendered_inputs: dict[str, object] = {}

            def _fake_render(inputs) -> None:
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if output_path.name.startswith("recovery_kit_index-"):
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Helvetica", size=12)
                    pdf.multi_cell(
                        w=0,
                        text="\n".join(
                            [
                                "Recovery Kit Index",
                                inputs.frames[0].doc_id.hex(),
                                "Extension 02",
                                "QR-DOC-01",
                                "RECOVERY-DOC-01",
                            ]
                        ),
                    )
                    pdf.output(str(output_path))
                else:
                    output_path.write_bytes(output_path.name.encode("utf-8"))
                rendered_inputs[output_path.name] = inputs
                if output_path.name.startswith(("qr_document-", "recovery_document-")):
                    captured["frames"] = list(inputs.frames)

            with (
                mock.patch(
                    "ethernity.cli.features.extend.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.main_carrier_validation._recovery_frames_from_scan",
                    side_effect=lambda *_args, **_kwargs: list(captured["frames"]),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.main_carrier_validation._resolve_auth_payload",
                    return_value=(
                        AuthPayload(
                            version=1,
                            doc_hash=b"\x22" * 32,
                            sign_pub=derive_public_key(resolved.signing_seed),
                            signature=b"\x77" * 64,
                        ),
                        "verified",
                    ),
                ),
            ):
                result = run_extend(
                    ExtendArgs(
                        root_dir=str(root_dir),
                        input=["/tmp/root/example.txt"],
                        unlock_policy="reuse-root",
                    ),
                    chunker=lambda data, _profile: (data,),
                    nonce="abc123",
                )

            self.assertEqual(result.final_dir.name, "02")
            self.assertEqual(len(result.shard_paths), 0)
            self.assertEqual(len(result.signing_key_shard_paths), 0)
            self.assertIsNotNone(result.recovery_kit_index_path)
            recovery_inputs = rendered_inputs[result.recovery_document_path.name]
            self.assertIsNone(recovery_inputs.recovery_meta.passphrase)
            self.assertEqual(recovery_inputs.recovery_meta.quorum_value, "2 of 2")
            self.assertIn(
                "Passphrase is stored in the root backup shard documents.",
                recovery_inputs.key_lines,
            )
            self.assertIn(
                "Recover with 2 of 2 root shard documents.",
                recovery_inputs.key_lines,
            )
            self.assertIn(
                "Signing private key not stored in this extension document.",
                recovery_inputs.key_lines,
            )
            self.assertNotIn("Passphrase:", recovery_inputs.key_lines)
            self.assertNotIn(
                "Signing private key stored in main document.",
                recovery_inputs.key_lines,
            )

    def test_run_extend_reuse_root_unlock_policy_requires_root_passphrase_shards(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )

        with (
            mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=resolved,
            ),
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                run_extend(
                    ExtendArgs(
                        root_dir="/tmp/root",
                        input=["/tmp/root/example.txt"],
                        unlock_policy="reuse-root",
                    ),
                    chunker=lambda data, _profile: (data,),
                    nonce="abc123",
                )

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("requires unlocking with passphrase shard inputs", str(ctx.exception))

    def test_resolve_extend_runtime_self_contained_inherits_validated_unlock_shard_policy(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()
            config_path = _config_with_no_shard_defaults(Path(tmpdir) / "config.toml")
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
                root_passphrase_shard_threshold=2,
                root_passphrase_shard_count=3,
            )
            with mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtendArgs(
                        config=str(config_path),
                        root_dir=str(root_dir),
                        input=["/tmp/root/example.txt"],
                    )
                )

            runtime = resolve_extend_runtime(prepared)

        self.assertEqual(runtime.passphrase, ExtensionPassphraseShards(threshold=2, share_count=3))

    def test_resolve_extend_runtime_reuse_root_requires_validated_unlock_shard_policy(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()
            config_path = _config_with_no_shard_defaults(Path(tmpdir) / "config.toml")
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtendArgs(
                        config=str(config_path),
                        root_dir=str(root_dir),
                        input=["/tmp/root/example.txt"],
                        unlock_policy="reuse-root",
                    )
                )

            with self.assertRaises(ApiCommandError) as ctx:
                resolve_extend_runtime(prepared)

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("requires unlocking with passphrase shard inputs", str(ctx.exception))

    def test_resolve_extend_runtime_rejects_explicit_zero_qr_chunk_size(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )
        with mock.patch(
            "ethernity.cli.features.extend.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtendArgs(
                    root_dir="/tmp/root",
                    input=["/tmp/root/example.txt"],
                    qr_chunk_size=0,
                )
            )

        with self.assertRaises(ApiCommandError) as ctx:
            resolve_extend_runtime(prepared)

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("qr_chunk_size must be a positive integer", str(ctx.exception))

    def test_resolve_extend_runtime_emits_kit_index_when_design_supports_it(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )
        with mock.patch(
            "ethernity.cli.features.extend.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtendArgs(root_dir="/tmp/root", input=["/tmp/root/example.txt"])
            )

        kit_index_template_path = Path("/tmp/kit_index_document.html.j2")
        with (
            mock.patch(
                "ethernity.cli.features.extend.runtime.backup_execution."
                "_resolve_kit_index_template_path",
                return_value=kit_index_template_path,
            ),
        ):
            runtime = resolve_extend_runtime(prepared)

        self.assertTrue(runtime.to_publish_policy().require_recovery_kit_index)
        self.assertEqual(runtime.kit_index_template_path, kit_index_template_path)

    def test_resolve_extend_runtime_omits_kit_index_when_design_lacks_template(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )
        with mock.patch(
            "ethernity.cli.features.extend.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtendArgs(root_dir="/tmp/root", input=["/tmp/root/example.txt"])
            )

        with (
            mock.patch(
                "ethernity.cli.features.extend.runtime.backup_execution."
                "_resolve_kit_index_template_path",
                return_value=None,
            ),
        ):
            runtime = resolve_extend_runtime(prepared)

        self.assertFalse(runtime.to_publish_policy().require_recovery_kit_index)
        self.assertIsNone(runtime.kit_index_template_path)

    def test_resolve_extend_runtime_reuse_root_rejects_explicit_zero_qr_chunk_size(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
            root_passphrase_shard_threshold=2,
            root_passphrase_shard_count=3,
        )
        with mock.patch(
            "ethernity.cli.features.extend.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtendArgs(
                    root_dir="/tmp/root",
                    input=["/tmp/root/example.txt"],
                    unlock_policy="reuse-root",
                    qr_chunk_size=0,
                )
            )

        with self.assertRaises(ApiCommandError) as ctx:
            resolve_extend_runtime(prepared)

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("qr_chunk_size must be a positive integer", str(ctx.exception))

    def test_run_extend_reuse_root_unlock_policy_rejects_explicit_shard_overrides(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )

        with (
            mock.patch(
                "ethernity.cli.features.extend.prepare.resolve_extend_state",
                return_value=resolved,
            ),
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                run_extend(
                    ExtendArgs(
                        root_dir="/tmp/root",
                        input=["/tmp/root/example.txt"],
                        unlock_policy="reuse-root",
                        shard_count=0,
                    ),
                    chunker=lambda data, _profile: (data,),
                    nonce="abc123",
                )

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("unlock_policy=reuse-root", str(ctx.exception))

    def test_run_extend_rejects_missing_extension_auth(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            captured: dict[str, list[Frame]] = {}

            def _fake_render(inputs) -> None:
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(output_path.name.encode("utf-8"))
                if output_path.name.startswith(("qr_document-", "recovery_document-")):
                    captured["frames"] = [
                        frame
                        for frame in inputs.frames
                        if frame.frame_type == FrameType.MAIN_DOCUMENT
                    ]

            with (
                mock.patch(
                    "ethernity.cli.features.extend.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.main_carrier_validation._recovery_frames_from_scan",
                    side_effect=lambda *_args, **_kwargs: list(captured["frames"]),
                ),
            ):
                with self.assertRaises(ApiCommandError) as ctx:
                    run_extend(
                        ExtendArgs(
                            root_dir=str(root_dir),
                            input=["/tmp/root/example.txt"],
                        ),
                        chunker=lambda data, _profile: (data,),
                        nonce="abc123",
                    )

        self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
        self.assertIn("missing auth payload", str(ctx.exception))

    def test_validate_single_main_carrier_rejects_missing_auth_for_recovery_document_scan(
        self,
    ) -> None:
        ciphertext = b"enc:extension"
        doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)
        main_frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=ciphertext,
        )

        with mock.patch(
            "ethernity.cli.features.extend.main_carrier_validation._recovery_frames_from_scan",
            return_value=[main_frame],
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                _validate_single_main_carrier(
                    path=Path("/tmp/recovery_document-01-deadbeefcafebabe.pdf"),
                    expected_doc_id=doc_id,
                    expected_doc_hash=doc_hash,
                    expected_sign_pub=b"\x44" * 32,
                    require_auth=True,
                    quiet=True,
                )

        self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
        self.assertIn("missing auth payload", str(ctx.exception))

    def test_validate_single_main_carrier_rejects_mismatched_auth_for_recovery_document_scan(
        self,
    ) -> None:
        ciphertext = b"enc:extension"
        doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)
        main_frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=ciphertext,
        )
        auth_frame = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"auth",
        )

        with (
            mock.patch(
                "ethernity.cli.features.extend.main_carrier_validation._recovery_frames_from_scan",
                return_value=[main_frame, auth_frame],
            ),
            mock.patch(
                "ethernity.cli.features.extend.main_carrier_validation._resolve_auth_payload",
                return_value=(
                    AuthPayload(
                        version=1,
                        doc_hash=doc_hash,
                        sign_pub=b"\x99" * 32,
                        signature=b"\x55" * 64,
                    ),
                    "verified",
                ),
            ),
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                _validate_single_main_carrier(
                    path=Path("/tmp/recovery_document-01-deadbeefcafebabe.pdf"),
                    expected_doc_id=doc_id,
                    expected_doc_hash=doc_hash,
                    expected_sign_pub=b"\x44" * 32,
                    require_auth=True,
                    quiet=True,
                )

        self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
        self.assertIn("root-derived signing authority", str(ctx.exception))

    def test_validate_single_main_carrier_rejects_recovery_scan_with_no_qr(
        self,
    ) -> None:
        ciphertext = b"enc:extension"
        doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)

        with mock.patch(
            "ethernity.cli.features.extend.main_carrier_validation._recovery_frames_from_scan",
            side_effect=ValueError("scan failed: no QR codes found in scan inputs"),
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                _validate_single_main_carrier(
                    path=Path("/tmp/recovery_document-01-deadbeefcafebabe.pdf"),
                    expected_doc_id=doc_id,
                    expected_doc_hash=doc_hash,
                    expected_sign_pub=b"\x44" * 32,
                    require_auth=True,
                    quiet=True,
                )

        self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
        self.assertIn("no QR codes found", str(ctx.exception))
