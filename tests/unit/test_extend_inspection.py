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
from unittest import mock

from ethernity.cli.features.extend.planning import _shard_frames_from_extend_args, inspect_from_args
from ethernity.cli.features.recover.chain import (
    DiscoveredRecoveryExtension,
    RecoveryChainInspection,
    RecoveryExtensionInventory,
    RecoveryHeadTrustRefusal,
    RecoveryReplayFailure,
)
from ethernity.cli.features.recover.planning import RecoveryInspection, RecoveryUnlockStatus
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import ExtendArgs
from ethernity.crypto.signing import AuthPayload
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions import LogicalFileState
from ethernity.formats.envelope_codec import build_manifest_and_payload
from ethernity.formats.envelope_types import PayloadPart


def _root_inspection(*, passphrase: str | None = None) -> RecoveryInspection:
    return RecoveryInspection(
        ciphertext=b"ciphertext",
        doc_id=b"\x11" * 16,
        doc_hash=b"\x22" * 32,
        auth_payload=None,
        auth_status="verified",
        allow_unsigned=False,
        input_label="Backup root directory",
        input_detail="/tmp/root",
        main_frames=(),
        auth_frames=(),
        shard_frames=(),
        shard_fallback_files=(),
        shard_payloads_file=(),
        shard_scan=(),
        unlock=RecoveryUnlockStatus(
            mode="passphrase",
            passphrase_provided=passphrase is not None,
            validated_shard_count=0,
            required_shard_threshold=None,
            satisfied=False,
            resolved_passphrase=passphrase,
            blocking_issues=(),
        ),
        blocking_issues=(),
    )


def _recovery_chain_inspection(
    *,
    extensions: tuple[DiscoveredRecoveryExtension, ...] = (),
    refusal: RecoveryHeadTrustRefusal | None = None,
    validated_head_index: int = 0,
    validated_head_doc_hash: str = "22" * 32,
    validated_head_auth_status: str | None = None,
    validated_head_root_authority_verified: bool | None = None,
    latest_state: tuple[LogicalFileState, ...] | None = None,
    locked_chunking=mock.sentinel.locked_chunking,
    links: tuple[object, ...] = (),
) -> RecoveryChainInspection:
    return RecoveryChainInspection(
        inventory=RecoveryExtensionInventory(
            extensions=extensions,
            explicit_selection=False,
            requested_head_index=None,
            requested_head_doc_hash=None,
            requested_target_matched=False,
            latest_head_index=extensions[-1].index if extensions else None,
            latest_head_doc_hash=extensions[-1].doc_hash.hex() if extensions else None,
            latest_head_dir_name=extensions[-1].dir_name if extensions else None,
            failure=None,
        ),
        links=links,
        latest_state=latest_state,
        locked_chunking=locked_chunking,
        refusal=refusal,
        validated_head_index=validated_head_index,
        validated_head_doc_hash=validated_head_doc_hash,
        validated_head_auth_status=validated_head_auth_status,
        validated_head_root_authority_verified=validated_head_root_authority_verified,
    )


class TestExtendInspection(unittest.TestCase):
    def test_inspect_from_args_requires_root_dir(self) -> None:
        with self.assertRaises(ApiCommandError):
            inspect_from_args(ExtendArgs())

    def test_inspect_from_args_rejects_symlinked_root_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir) / "target"
            root_dir = Path(tmpdir) / "backup-root"
            target_dir.mkdir()
            try:
                root_dir.symlink_to(target_dir, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaises(ApiCommandError) as ctx:
                inspect_from_args(ExtendArgs(root_dir=str(root_dir)))

        self.assertEqual(ctx.exception.code, "INVALID_INPUT")
        self.assertIn("must not be a symlink", str(ctx.exception))

    def test_inspect_from_args_rejects_symlinked_root_main_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            external = Path(tmpdir) / "external-qr.pdf"
            root_dir.mkdir()
            external.write_bytes(b"x")
            try:
                (root_dir / "qr_document.pdf").symlink_to(external)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaises(ApiCommandError) as ctx:
                inspect_from_args(ExtendArgs(root_dir=str(root_dir)))

        self.assertEqual(ctx.exception.code, "INVALID_INPUT")
        self.assertIn("root backup MAIN carrier must not be a symlink", str(ctx.exception))

    def test_inspect_from_args_reports_discovered_extensions(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_root_inspection(),
            ),
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_discovered_extensions",
                return_value=(
                    mock.Mock(
                        dir_name="01",
                        doc_id_hex="deadbeefcafebabe",
                        doc_hash_hex="cafebabe",
                        doc_hash=None,
                        ciphertext=None,
                    ),
                ),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            extension_dir = root_dir / "extensions" / "01"
            local_dir = Path(tmpdir) / "scope"
            nested_dir = local_dir / "nested"
            extension_dir.mkdir(parents=True)
            nested_dir.mkdir(parents=True)
            (extension_dir / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"x")
            (extension_dir / "recovery_document-01-deadbeefcafebabe.pdf").write_bytes(b"y")
            (local_dir / "alpha.txt").write_text("alpha", encoding="utf-8")
            (nested_dir / "beta.txt").write_text("beta", encoding="utf-8")

            inspection = inspect_from_args(
                ExtendArgs(
                    root_dir=str(root_dir),
                    input=[str(local_dir / "alpha.txt")],
                    input_dir=[str(nested_dir)],
                    base_dir=str(local_dir),
                )
            )

        self.assertEqual(inspection.input_kind, "extended_root")
        self.assertEqual(inspection.discovered_extension_dirs, (1,))
        self.assertEqual(
            inspection.available_extensions,
            ({"dir_name": "01", "doc_id": "deadbeefcafebabe", "doc_hash": "cafebabe"},),
        )
        self.assertEqual(
            inspection.selected_scope,
            {
                "files": [str(local_dir / "alpha.txt")],
                "directories": [str(nested_dir)],
                "base_dir": str(local_dir),
                "file_count": 2,
                "total_bytes": 9,
                "input_origin": "mixed",
                "input_roots": ["nested"],
            },
        )

    def test_inspect_from_args_surfaces_invalid_layout_as_blocking_issue(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_root_inspection(),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            (root_dir / "extensions" / "001").mkdir(parents=True)

            inspection = inspect_from_args(ExtendArgs(root_dir=str(root_dir)))

        self.assertEqual(inspection.input_kind, "standalone_root")
        self.assertEqual(inspection.discovered_extension_dirs, ())
        self.assertEqual(inspection.available_extensions, ())
        self.assertEqual(inspection.blocking_issues[0]["code"], "EXTENSION_LAYOUT_INVALID")

    def test_inspect_from_args_rejects_invalid_extension_doc_id_filename(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_root_inspection(),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            extension_dir = root_dir / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (extension_dir / "qr_document-01-abc.pdf").write_bytes(b"x")
            (extension_dir / "recovery_document-01-abc.pdf").write_bytes(b"y")

            inspection = inspect_from_args(ExtendArgs(root_dir=str(root_dir)))

        self.assertEqual(inspection.discovered_extension_dirs, ())
        self.assertEqual(inspection.available_extensions, ())
        self.assertEqual(inspection.blocking_issues[0]["code"], "EXTENSION_LAYOUT_INVALID")
        self.assertIn(
            "invalid extension MAIN carrier filename",
            inspection.blocking_issues[0]["message"],
        )

    def test_inspect_from_args_rejects_corrupt_canonical_extension_inventory(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_root_inspection(),
            ),
            mock.patch(
                "ethernity.cli.features.extend.planning.scan_extension_carriers",
                side_effect=ValueError("unreadable MAIN data"),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            extension_dir = root_dir / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (extension_dir / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"x")
            (extension_dir / "recovery_document-01-deadbeefcafebabe.pdf").write_bytes(b"y")

            inspection = inspect_from_args(ExtendArgs(root_dir=str(root_dir)))

        self.assertEqual(inspection.discovered_extension_dirs, (1,))
        self.assertEqual(inspection.available_extensions, ())
        self.assertEqual(inspection.blocking_issues[0]["code"], "EXTENSION_LAYOUT_INVALID")
        self.assertIn(
            "extension 01 MAIN carriers could not be reconstructed",
            inspection.blocking_issues[0]["message"],
        )

    def test_inspect_from_args_base_dir_only_uses_canonical_selected_scope_shape(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_root_inspection(),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir(parents=True)

            inspection = inspect_from_args(
                ExtendArgs(
                    root_dir=str(root_dir),
                    base_dir=str(Path(tmpdir) / "scope"),
                )
            )

        self.assertEqual(
            inspection.selected_scope,
            {
                "files": [],
                "directories": [],
                "base_dir": str(Path(tmpdir) / "scope"),
                "file_count": 0,
                "total_bytes": 0,
                "input_origin": None,
                "input_roots": [],
            },
        )

    def test_inspect_from_args_rejects_main_carrier_hidden_by_other_carrier(self) -> None:
        good_frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x11" * 16,
                index=0,
                total=2,
                data=b"alpha",
            ),
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x11" * 16,
                index=1,
                total=2,
                data=b"beta",
            ),
        ]

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_root_inspection(),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            extension_dir = root_dir / "extensions" / "01"
            qr_path = extension_dir / "qr_document-01-1111111111111111.pdf"
            recovery_path = extension_dir / "recovery_document-01-1111111111111111.pdf"
            extension_dir.mkdir(parents=True)
            qr_path.write_bytes(b"x")
            recovery_path.write_bytes(b"y")

            def _scan(paths: list[str], *, quiet: bool = False):
                _ = quiet
                frames: list[Frame] = []
                for path in paths:
                    if path == str(qr_path):
                        frames.extend(good_frames)
                    elif path == str(recovery_path):
                        frames.extend([good_frames[0]])
                return frames

            with mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                side_effect=_scan,
            ):
                inspection = inspect_from_args(ExtendArgs(root_dir=str(root_dir)))

        self.assertEqual(inspection.discovered_extension_dirs, (1,))
        self.assertEqual(inspection.available_extensions, ())
        self.assertEqual(inspection.blocking_issues[0]["code"], "EXTENSION_LAYOUT_INVALID")
        self.assertIn(
            "extension 01 MAIN carriers could not be reconstructed",
            inspection.blocking_issues[0]["message"],
        )

    def test_inspect_from_args_rejects_valid_prefix_when_suffix_is_invalid(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_root_inspection(),
            ),
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_discovered_extensions",
                return_value=(
                    mock.Mock(
                        dir_name="01",
                        doc_id_hex="deadbeefcafebabe",
                        doc_hash_hex="cafebabe",
                        doc_hash=None,
                        ciphertext=None,
                    ),
                ),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            valid_dir = root_dir / "extensions" / "01"
            invalid_dir = root_dir / "extensions" / "02"
            valid_dir.mkdir(parents=True)
            invalid_dir.mkdir(parents=True)
            (valid_dir / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"x")
            (valid_dir / "recovery_document-01-deadbeefcafebabe.pdf").write_bytes(b"y")
            (invalid_dir / "qr_document-02-cafebabedeadbeef.pdf").write_bytes(b"z")

            inspection = inspect_from_args(ExtendArgs(root_dir=str(root_dir)))

        self.assertEqual(inspection.input_kind, "standalone_root")
        self.assertEqual(inspection.discovered_extension_dirs, ())
        self.assertEqual(inspection.available_extensions, ())
        self.assertEqual(inspection.blocking_issues[0]["code"], "EXTENSION_LAYOUT_INVALID")
        self.assertIn(
            "missing required payload MAIN carriers",
            inspection.blocking_issues[0]["message"],
        )

    def test_shard_frames_from_extend_args_preserves_preloaded_frames(self) -> None:
        shard_frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x11" * 16,
            index=0,
            total=1,
            data=b"shard",
        )
        shard_frames, shard_fallback, shard_payloads, shard_scan = _shard_frames_from_extend_args(
            ExtendArgs(shard_frames=[shard_frame]),
            quiet=True,
        )

        self.assertEqual(shard_frames, [shard_frame])
        self.assertEqual(shard_fallback, [])
        self.assertEqual(shard_payloads, [])
        self.assertEqual(shard_scan, [])

    def test_inspect_from_args_populates_decrypt_dependent_fields_when_unlocked(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        unlocked_root = RecoveryInspection(
            **{
                **_root_inspection(passphrase="secret").__dict__,
                "unlock": RecoveryUnlockStatus(
                    mode="passphrase",
                    passphrase_provided=True,
                    validated_shard_count=0,
                    required_shard_threshold=None,
                    satisfied=True,
                    resolved_passphrase="secret",
                    blocking_issues=(),
                ),
            }
        )

        with (
            tempfile.TemporaryDirectory() as tmpdir,
        ):
            root_dir = Path(tmpdir) / "backup-root"
            local_dir = Path(tmpdir) / "scope"
            root_dir.mkdir()
            local_dir.mkdir()
            (local_dir / "alpha.txt").write_text("alpha", encoding="utf-8")
            alpha_mtime = int((local_dir / "alpha.txt").stat().st_mtime)
            with (
                mock.patch(
                    "ethernity.cli.features.extend.planning._inspect_root_recovery",
                    return_value=unlocked_root,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning.extract_root_logical_state",
                    return_value=(
                        LogicalFileState(
                            path="alpha.txt",
                            size=5,
                            sha256=manifest.files[0].sha256,
                            mtime=alpha_mtime,
                            data=b"alpha",
                        ),
                    ),
                ),
            ):
                inspection = inspect_from_args(
                    ExtendArgs(
                        root_dir=str(root_dir),
                        input=[str(local_dir / "alpha.txt")],
                        base_dir=str(local_dir),
                        passphrase="secret",
                    )
                )

        self.assertEqual(inspection.doc_id, "11111111111111111111111111111111")
        self.assertEqual(
            inspection.root_doc_hash,
            "2222222222222222222222222222222222222222222222222222222222222222",
        )
        self.assertIsNotNone(inspection.chain_id)
        self.assertEqual(inspection.source_summary["file_count"], 1)
        self.assertEqual(inspection.validated_head_index, 0)
        self.assertEqual(
            inspection.validated_head_doc_hash,
            "2222222222222222222222222222222222222222222222222222222222222222",
        )
        self.assertEqual(inspection.validated_head_auth_status, "verified")
        self.assertEqual(inspection.validated_head_root_authority_verified, True)
        self.assertEqual(
            inspection.signing_authority,
            {"available": True, "satisfied": True, "source": "embedded_seed"},
        )
        self.assertEqual(
            inspection.diff_summary,
            {
                "new_paths": [],
                "changed_paths": [],
                "unchanged_paths": ["alpha.txt"],
                "missing_paths": [],
                "new_count": 0,
                "changed_count": 0,
                "unchanged_count": 1,
                "missing_count": 0,
            },
        )

    def test_inspect_from_args_blocks_root_authority_mismatch(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        unlocked_root = RecoveryInspection(
            **{
                **_root_inspection(passphrase="secret").__dict__,
                "auth_payload": AuthPayload(
                    version=1,
                    doc_hash=b"\x22" * 32,
                    sign_pub=b"\x99" * 32,
                    signature=b"\x77" * 64,
                ),
                "unlock": RecoveryUnlockStatus(
                    mode="passphrase",
                    passphrase_provided=True,
                    validated_shard_count=0,
                    required_shard_threshold=None,
                    satisfied=True,
                    resolved_passphrase="secret",
                    blocking_issues=(),
                ),
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir()
            (root_dir / "alpha.txt").write_text("alpha", encoding="utf-8")
            with (
                mock.patch(
                    "ethernity.cli.features.extend.planning._inspect_root_recovery",
                    return_value=unlocked_root,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning.extract_root_logical_state",
                    return_value=(
                        LogicalFileState(
                            path="alpha.txt",
                            size=5,
                            sha256=manifest.files[0].sha256,
                            mtime=1,
                            data=b"alpha",
                        ),
                    ),
                ),
            ):
                inspection = inspect_from_args(
                    ExtendArgs(
                        root_dir=str(root_dir),
                        input=[str(root_dir / "alpha.txt")],
                        passphrase="secret",
                    )
                )

        self.assertEqual(inspection.signing_authority["available"], True)
        self.assertEqual(inspection.signing_authority["satisfied"], False)
        self.assertIsNone(inspection.signing_authority["source"])
        self.assertEqual(inspection.blocking_issues[0]["code"], "ROOT_AUTHORITY_MISMATCH")

    def test_inspect_from_args_uses_shared_recovery_head_refusal_for_degraded_latest_chain(
        self,
    ) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        unlocked_root = RecoveryInspection(
            **{
                **_root_inspection(passphrase="secret").__dict__,
                "unlock": RecoveryUnlockStatus(
                    mode="passphrase",
                    passphrase_provided=True,
                    validated_shard_count=0,
                    required_shard_threshold=None,
                    satisfied=True,
                    resolved_passphrase="secret",
                    blocking_issues=(),
                ),
            }
        )
        degraded_refusal = RecoveryHeadTrustRefusal(
            code=api_codes.RECOVERY_HEAD_UNTRUSTED,
            message=(
                "latest recovery head could not be trusted: extension directory 02 is missing "
                "required payload MAIN carriers: recovery_document"
            ),
            details={
                "stage": "replay",
                "failure_stage": "discovery",
                "failure_message": (
                    "extension directory 02 is missing required payload MAIN carriers: "
                    "recovery_document"
                ),
                "failure_head_index": 2,
                "failure_head_doc_hash": None,
                "failure_head_dir_name": "02",
                "latest_head_index": 2,
                "latest_head_doc_hash": None,
                "latest_head_dir_name": "02",
                "requested_head_index": None,
                "requested_head_doc_hash": None,
                "validated_head_index": 0,
                "validated_head_doc_hash": "22" * 32,
                "validated_head_auth_status": None,
                "validated_head_root_authority_verified": None,
                "explicit_selection": False,
            },
        )
        extension = DiscoveredRecoveryExtension(
            index=1,
            dir_name="01",
            doc_id_hex="de" * 8,
            doc_hash=b"\xaa" * 32,
            ciphertext=b"extension-01",
            auth_frames=(),
        )
        chain_inspection = _recovery_chain_inspection(
            extensions=(extension,),
            refusal=degraded_refusal,
            latest_state=None,
            locked_chunking=None,
        )
        chain_inspection = RecoveryChainInspection(
            inventory=RecoveryExtensionInventory(
                **{
                    **chain_inspection.inventory.__dict__,
                    "latest_head_index": 2,
                    "latest_head_doc_hash": None,
                    "latest_head_dir_name": "02",
                    "failure": RecoveryReplayFailure(
                        stage="discovery",
                        message=(
                            "extension directory 02 is missing required payload MAIN carriers: "
                            "recovery_document"
                        ),
                        head_index=2,
                        head_dir_name="02",
                    ),
                }
            ),
            links=chain_inspection.links,
            latest_state=chain_inspection.latest_state,
            locked_chunking=chain_inspection.locked_chunking,
            refusal=chain_inspection.refusal,
            validated_head_index=chain_inspection.validated_head_index,
            validated_head_doc_hash=chain_inspection.validated_head_doc_hash,
            validated_head_auth_status=chain_inspection.validated_head_auth_status,
            validated_head_root_authority_verified=(
                chain_inspection.validated_head_root_authority_verified
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir()
            (root_dir / "alpha.txt").write_text("alpha", encoding="utf-8")
            with (
                mock.patch(
                    "ethernity.cli.features.extend.planning.discover_validated_extension_directories",
                    return_value=mock.Mock(
                        directories=(mock.Mock(index=1, dir_name="01"),),
                        first_invalid_message=(
                            "extension directory 02 is missing required payload MAIN carriers: "
                            "recovery_document"
                        ),
                        first_invalid_dir_name="02",
                    ),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning._inspect_root_recovery",
                    return_value=unlocked_root,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning.extract_root_logical_state",
                    return_value=(
                        LogicalFileState(
                            path="alpha.txt",
                            size=5,
                            sha256=manifest.files[0].sha256,
                            mtime=1,
                            data=b"alpha",
                        ),
                    ),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning.inspect_recovery_extension_chain",
                    return_value=chain_inspection,
                ),
            ):
                inspection = inspect_from_args(
                    ExtendArgs(
                        root_dir=str(root_dir),
                        input=[str(root_dir / "alpha.txt")],
                        passphrase="secret",
                    )
                )

        self.assertEqual(inspection.input_kind, "extended_root")
        self.assertEqual(inspection.discovered_extension_dirs, (1,))
        self.assertEqual(inspection.validated_head_index, 0)
        self.assertEqual(inspection.validated_head_doc_hash, "22" * 32)
        self.assertIsNone(inspection.validated_head_auth_status)
        self.assertIsNone(inspection.validated_head_root_authority_verified)
        self.assertEqual(
            inspection.available_extensions,
            ({"dir_name": "01", "doc_id": "de" * 8, "doc_hash": "aa" * 32},),
        )
        self.assertEqual(inspection.blocking_issues[0]["code"], api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(inspection.blocking_issues[0]["details"], degraded_refusal.details)
        self.assertEqual(inspection.blocking_issues[0]["details"]["failure_stage"], "discovery")
        self.assertEqual(inspection.blocking_issues[0]["details"]["validated_head_index"], 0)
        self.assertNotIn("CHAIN_INVALID", [issue["code"] for issue in inspection.blocking_issues])
        self.assertNotIn(
            "EXTENSION_LAYOUT_INVALID",
            [issue["code"] for issue in inspection.blocking_issues],
        )

    def test_inspect_from_args_adds_auth_metadata_from_shared_chain_inspection(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        unlocked_root = RecoveryInspection(
            **{
                **_root_inspection(passphrase="secret").__dict__,
                "unlock": RecoveryUnlockStatus(
                    mode="passphrase",
                    passphrase_provided=True,
                    validated_shard_count=0,
                    required_shard_threshold=None,
                    satisfied=True,
                    resolved_passphrase="secret",
                    blocking_issues=(),
                ),
            }
        )
        extension = DiscoveredRecoveryExtension(
            index=1,
            dir_name="01",
            doc_id_hex="de" * 8,
            doc_hash=b"\xaa" * 32,
            ciphertext=b"extension-01",
            auth_frames=(),
        )
        decoded_link = mock.Mock(
            auth_status="verified",
            root_authority_verified=True,
            link=mock.Mock(doc_hash=b"\xaa" * 32),
        )
        decoded_link.link.document.header.index = 1
        chain_inspection = _recovery_chain_inspection(
            extensions=(extension,),
            links=(decoded_link,),
            latest_state=(
                LogicalFileState(
                    path="alpha.txt",
                    size=5,
                    sha256=manifest.files[0].sha256,
                    mtime=1,
                    data=b"alpha",
                ),
            ),
            validated_head_index=1,
            validated_head_doc_hash="aa" * 32,
            validated_head_auth_status="verified",
            validated_head_root_authority_verified=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir()
            (root_dir / "alpha.txt").write_text("alpha", encoding="utf-8")
            with (
                mock.patch(
                    "ethernity.cli.features.extend.planning._inspect_root_recovery",
                    return_value=unlocked_root,
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning.extract_root_logical_state",
                    return_value=(
                        LogicalFileState(
                            path="alpha.txt",
                            size=5,
                            sha256=manifest.files[0].sha256,
                            mtime=1,
                            data=b"alpha",
                        ),
                    ),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning.discover_validated_extension_directories",
                    return_value=mock.Mock(
                        directories=(mock.Mock(index=1, dir_name="01"),),
                        first_invalid_message=None,
                        first_invalid_dir_name=None,
                    ),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning._inspect_discovered_extensions",
                    return_value=(
                        mock.Mock(
                            dir_name="01",
                            doc_id_hex="de" * 8,
                            doc_hash_hex="aa" * 32,
                            doc_hash=b"\xaa" * 32,
                            ciphertext=b"extension-01",
                            auth_frames=(),
                        ),
                    ),
                ),
                mock.patch(
                    "ethernity.cli.features.extend.planning.inspect_recovery_extension_chain",
                    return_value=chain_inspection,
                ),
            ):
                inspection = inspect_from_args(
                    ExtendArgs(
                        root_dir=str(root_dir),
                        input=[str(root_dir / "alpha.txt")],
                        passphrase="secret",
                    )
                )

        self.assertEqual(inspection.discovered_extension_dirs, (1,))
        self.assertEqual(inspection.validated_head_index, 1)
        self.assertEqual(inspection.validated_head_doc_hash, "aa" * 32)
        self.assertEqual(inspection.validated_head_auth_status, "verified")
        self.assertEqual(inspection.validated_head_root_authority_verified, True)
        self.assertEqual(
            inspection.available_extensions,
            (
                {
                    "dir_name": "01",
                    "doc_id": "de" * 8,
                    "doc_hash": "aa" * 32,
                    "auth_status": "verified",
                    "root_authority_verified": True,
                },
            ),
        )
