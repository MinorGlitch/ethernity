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
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ethernity.cli.features.recover.key_recovery import InsufficientShardError
from ethernity.cli.features.recover.planning import RecoveryInspection, RecoveryUnlockStatus
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.io.frames import NoQrFramesError
from ethernity.crypto import sharding as sharding_module
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.signing import AuthPayload, derive_public_key, sign_auth
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions import LogicalFileState
from ethernity.extensions.recovery import (
    ImportedRecoveryDocument,
    RecoveryChainInspection,
    RecoveryExtensionInventory,
    RecoveryHeadTrustRefusal,
    RecoveryReplayFailure,
)
from ethernity.formats.envelope_codec import build_manifest_and_payload
from ethernity.formats.envelope_types import PayloadPart
from ethernity.formats.extension_envelope import ExtensionChunkingProfile
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC
from ethernity.workflows.extension.errors import ExtensionWorkflowError
from ethernity.workflows.extension.planning import (
    _audit_published_root_fallback_carriers,
    _expected_head_issue,
    _inspect_root_recovery,
    _RootRecoveryInspection,
    _shard_frames_from_extend_args,
    inspect_from_args,
    resolve_extend_state,
)
from ethernity.workflows.extension.request import ExtensionRequest
from ethernity.workflows.extension.root_shards import published_root_passphrase_shard_policy
from ethernity.workflows.recovery.frame_inputs import FrameInputResult

TEST_CHUNKING = ExtensionChunkingProfile(
    algorithm_id=CHUNK_ALGORITHM_FASTCDC,
    target_size=16 * 1024,
    min_size=4 * 1024,
    max_size=64 * 1024,
)


def _root_inspection(
    *,
    passphrase: str | None = None,
    auth_status: str = "verified",
    blocking_issues: tuple[dict[str, object], ...] = (),
    authenticated: bool = False,
) -> RecoveryInspection:
    root_doc_hash = b"\x22" * 32
    signing_seed = b"\x33" * 32
    sign_pub = derive_public_key(signing_seed)
    auth_payload = (
        AuthPayload(
            version=1,
            doc_hash=root_doc_hash,
            sign_pub=sign_pub,
            signature=sign_auth(root_doc_hash, sign_pub=sign_pub, sign_priv=signing_seed),
        )
        if auth_status == "verified" and authenticated
        else None
    )
    return RecoveryInspection(
        ciphertext=b"ciphertext",
        doc_id=b"\x11" * 16,
        doc_hash=root_doc_hash,
        auth_payload=auth_payload,
        auth_status=auth_status,
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
        blocking_issues=blocking_issues,
    )


def _root_recovery(
    *,
    passphrase: str | None = None,
    auth_status: str = "verified",
    blocking_issues: tuple[dict[str, object], ...] = (),
    shard_unlock_target: str = "none",
) -> _RootRecoveryInspection:
    return _RootRecoveryInspection(
        _root_inspection(
            passphrase=passphrase,
            auth_status=auth_status,
            blocking_issues=blocking_issues,
        ),
        shard_unlock_target,
    )


def _recovery_chain_inspection(
    *,
    extensions: tuple[ImportedRecoveryDocument, ...] = (),
    refusal: RecoveryHeadTrustRefusal | None = None,
    validated_head_index: int = 0,
    validated_head_doc_hash: str = "22" * 32,
    validated_head_auth_status: str | None = None,
    validated_head_root_authority_verified: bool | None = None,
    latest_state: tuple[LogicalFileState, ...] | None = None,
    locked_chunking=TEST_CHUNKING,
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


def _extension_inventory(
    *,
    extensions: tuple[ImportedRecoveryDocument, ...] = (),
    failure: RecoveryReplayFailure | None = None,
) -> RecoveryExtensionInventory:
    return RecoveryExtensionInventory(
        extensions=extensions,
        explicit_selection=False,
        requested_head_index=None,
        requested_head_doc_hash=None,
        requested_target_matched=False,
        latest_head_index=(
            failure.head_index
            if failure is not None
            else extensions[-1].index
            if extensions
            else None
        ),
        latest_head_doc_hash=extensions[-1].doc_hash.hex() if extensions else None,
        latest_head_dir_name=(
            failure.head_dir_name
            if failure is not None
            else extensions[-1].dir_name
            if extensions
            else None
        ),
        failure=failure,
    )


def _discovered_extension(
    *,
    index: int = 1,
    dir_name: str = "01",
    doc_id_hex: str = "deadbeefcafebabe",
    doc_hash: bytes = b"\xca\xfe\xba\xbe" * 8,
) -> ImportedRecoveryDocument:
    return ImportedRecoveryDocument.from_ciphertext(
        ciphertext=b"extension:" + bytes.fromhex(doc_id_hex) + doc_hash,
        auth_frames=(),
        source_label=dir_name,
        extension_index=index,
        extension_dir_name=dir_name,
    )


def _authenticated_root_audit_inspection() -> tuple[RecoveryInspection, bytes]:
    ciphertext = b"authenticated published root ciphertext"
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    signing_seed = b"\x33" * 32
    sign_pub = derive_public_key(signing_seed)
    auth_frame = Frame(
        version=1,
        frame_type=FrameType.AUTH,
        doc_id=doc_id,
        index=0,
        total=1,
        data=b"auth",
    )
    inspection = replace(
        _root_inspection(passphrase="secret"),
        ciphertext=ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
        auth_payload=AuthPayload(
            version=1,
            doc_hash=doc_hash,
            sign_pub=sign_pub,
            signature=b"\x55" * 64,
        ),
        auth_frames=(auth_frame,),
    )
    return inspection, signing_seed


def _signed_root_shard_frames(
    inspection: RecoveryInspection,
    signing_seed: bytes,
    *,
    key_type: str = sharding_module.KEY_TYPE_PASSPHRASE,
    share_count: int = 2,
) -> tuple[Frame, ...]:
    auth_payload = inspection.auth_payload
    assert auth_payload is not None
    if key_type == sharding_module.KEY_TYPE_PASSPHRASE:
        payloads = sharding_module.split_passphrase(
            "secret",
            threshold=min(2, share_count),
            shares=share_count,
            doc_hash=inspection.doc_hash,
            sign_priv=signing_seed,
            sign_pub=auth_payload.sign_pub,
        )
    else:
        payloads = sharding_module.split_signing_seed(
            b"\x77" * 32,
            threshold=min(2, share_count),
            shares=share_count,
            doc_hash=inspection.doc_hash,
            sign_priv=signing_seed,
            sign_pub=auth_payload.sign_pub,
        )
    return tuple(
        Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=inspection.doc_id,
            index=0,
            total=1,
            data=sharding_module.encode_shard_payload(payload),
        )
        for payload in payloads
    )


class TestExtendInspection(unittest.TestCase):
    def test_published_root_recovery_fallback_is_audited_against_qr_document(self) -> None:
        ciphertext = b"authenticated root ciphertext"
        doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        auth_frame = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"auth",
        )
        inspection = replace(
            _root_inspection(passphrase="secret"),
            ciphertext=ciphertext,
            doc_id=doc_id,
            doc_hash=doc_hash,
            auth_payload=AuthPayload(
                version=1,
                doc_hash=doc_hash,
                sign_pub=b"\x44" * 32,
                signature=b"\x55" * 64,
            ),
            auth_frames=(auth_frame,),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            recovery_path = root_dir / "recovery_document.pdf"
            recovery_path.write_bytes(b"pdf")
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "validate_published_recovery_document_carrier"
                ) as validate_recovery,
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "root_level_key_frame_carriers_from_scan",
                    return_value=(),
                ),
            ):
                _audit_published_root_fallback_carriers(root_dir, inspection, quiet=True)

        validate_recovery.assert_called_once()
        self.assertEqual(validate_recovery.call_args.kwargs["path"], recovery_path)
        self.assertEqual(validate_recovery.call_args.kwargs["document"].ciphertext, ciphertext)

    def test_published_root_audit_requires_recovery_document(self) -> None:
        inspection, _signing_seed = _authenticated_root_audit_inspection()
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "missing required recovery_document.pdf"):
                _audit_published_root_fallback_carriers(Path(tmpdir), inspection, quiet=True)

    def test_published_root_audit_rejects_invalid_recovery_document(self) -> None:
        inspection, _signing_seed = _authenticated_root_audit_inspection()
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            (root_dir / "recovery_document.pdf").write_bytes(b"%PDF-1.4\ninvalid")
            with self.assertRaises(ExtensionWorkflowError) as ctx:
                _audit_published_root_fallback_carriers(root_dir, inspection, quiet=True)

        self.assertEqual(ctx.exception.code, api_codes.EXTENSION_MAIN_CARRIER_INVALID)
        self.assertIn("published recovery document", str(ctx.exception))

    def test_complete_canonical_root_shard_set_is_bound_and_fallback_audited(self) -> None:
        inspection, signing_seed = _authenticated_root_audit_inspection()
        frames = _signed_root_shard_frames(inspection, signing_seed)
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            (root_dir / "recovery_document.pdf").write_bytes(b"%PDF-1.4\n")
            carriers: list[tuple[Path, tuple[Frame, ...]]] = []
            for index, frame in enumerate(frames, start=1):
                path = root_dir / f"shard-{inspection.doc_id.hex()}-{index}-of-2.pdf"
                path.write_bytes(b"%PDF-1.4\n")
                carriers.append((path, (frame,)))
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "validate_published_recovery_document_carrier"
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "root_level_key_frame_carriers_from_scan",
                    return_value=tuple(carriers),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "validate_published_shard_fallback_carrier"
                ) as validate_shard,
            ):
                _audit_published_root_fallback_carriers(root_dir, inspection, quiet=True)

        self.assertEqual(validate_shard.call_count, 2)
        self.assertEqual(
            {call.kwargs["path"].name for call in validate_shard.call_args_list},
            {path.name for path, _frames in carriers},
        )

    def test_incomplete_canonical_root_shard_set_is_rejected(self) -> None:
        inspection, signing_seed = _authenticated_root_audit_inspection()
        frame = _signed_root_shard_frames(inspection, signing_seed)[0]
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            (root_dir / "recovery_document.pdf").write_bytes(b"%PDF-1.4\n")
            shard_path = root_dir / f"shard-{inspection.doc_id.hex()}-1-of-2.pdf"
            shard_path.write_bytes(b"%PDF-1.4\n")
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "validate_published_recovery_document_carrier"
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "root_level_key_frame_carriers_from_scan",
                    return_value=((shard_path, (frame,)),),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "validate_published_shard_fallback_carrier"
                ),
            ):
                with self.assertRaisesRegex(ValueError, "must contain shares 1 through 2"):
                    _audit_published_root_fallback_carriers(root_dir, inspection, quiet=True)

    def test_canonical_root_shard_filename_metadata_is_bound_to_payload(self) -> None:
        inspection, signing_seed = _authenticated_root_audit_inspection()
        frame = _signed_root_shard_frames(inspection, signing_seed)[0]
        cases = (
            (
                f"signing-key-shard-{inspection.doc_id.hex()}-1-of-2.pdf",
                "filename role does not match payload",
            ),
            ("shard-9999999999999999-1-of-2.pdf", "filename doc_id does not match root"),
            (
                f"shard-{inspection.doc_id.hex()}-2-of-2.pdf",
                "filename share metadata is invalid",
            ),
        )
        for filename, error in cases:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmpdir:
                root_dir = Path(tmpdir)
                (root_dir / "recovery_document.pdf").write_bytes(b"%PDF-1.4\n")
                shard_path = root_dir / filename
                shard_path.write_bytes(b"%PDF-1.4\n")
                with (
                    mock.patch(
                        "ethernity.workflows.extension.planning."
                        "validate_published_recovery_document_carrier"
                    ),
                    mock.patch(
                        "ethernity.workflows.extension.planning."
                        "root_level_key_frame_carriers_from_scan",
                        return_value=((shard_path, (frame,)),),
                    ),
                ):
                    with self.assertRaisesRegex(ValueError, error):
                        _audit_published_root_fallback_carriers(root_dir, inspection, quiet=True)

    def test_canonical_root_shard_without_key_qr_is_rejected(self) -> None:
        inspection, _signing_seed = _authenticated_root_audit_inspection()
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            (root_dir / "recovery_document.pdf").write_bytes(b"%PDF-1.4\n")
            shard_path = root_dir / f"shard-{inspection.doc_id.hex()}-1-of-1.pdf"
            shard_path.write_bytes(b"%PDF-1.4\n")
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "validate_published_recovery_document_carrier"
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "root_level_key_frame_carriers_from_scan",
                    return_value=(),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "contains no KEY frame"):
                    _audit_published_root_fallback_carriers(root_dir, inspection, quiet=True)

    def test_canonical_root_shard_requires_root_hash_authority_and_signature(self) -> None:
        inspection, signing_seed = _authenticated_root_audit_inspection()
        auth_payload = inspection.auth_payload
        assert auth_payload is not None
        valid_frame = _signed_root_shard_frames(
            inspection,
            signing_seed,
            share_count=1,
        )[0]
        valid_payload = sharding_module.decode_shard_payload(valid_frame.data)
        wrong_hash_payload = sharding_module.split_passphrase(
            "secret",
            threshold=1,
            shares=1,
            doc_hash=b"\x99" * 32,
            sign_priv=signing_seed,
            sign_pub=auth_payload.sign_pub,
        )[0]
        other_seed = b"\x88" * 32
        wrong_authority_payload = sharding_module.split_passphrase(
            "secret",
            threshold=1,
            shares=1,
            doc_hash=inspection.doc_hash,
            sign_priv=other_seed,
            sign_pub=derive_public_key(other_seed),
        )[0]
        cases = (
            (wrong_hash_payload, "not bound to the root"),
            (wrong_authority_payload, "signing authority does not match root"),
            (replace(valid_payload, signature=b"\x00" * 64), "signature verification failed"),
        )
        for payload, error in cases:
            frame = replace(valid_frame, data=sharding_module.encode_shard_payload(payload))
            with self.subTest(error=error), tempfile.TemporaryDirectory() as tmpdir:
                root_dir = Path(tmpdir)
                (root_dir / "recovery_document.pdf").write_bytes(b"%PDF-1.4\n")
                shard_path = root_dir / f"shard-{inspection.doc_id.hex()}-1-of-1.pdf"
                shard_path.write_bytes(b"%PDF-1.4\n")
                with (
                    mock.patch(
                        "ethernity.workflows.extension.planning."
                        "validate_published_recovery_document_carrier"
                    ),
                    mock.patch(
                        "ethernity.workflows.extension.planning."
                        "root_level_key_frame_carriers_from_scan",
                        return_value=((shard_path, (frame,)),),
                    ),
                ):
                    with self.assertRaisesRegex(ValueError, error):
                        _audit_published_root_fallback_carriers(root_dir, inspection, quiet=True)

    def test_canonical_root_shard_rejects_mixed_root_and_foreign_key_frames(self) -> None:
        inspection = replace(
            _root_inspection(passphrase="secret"),
            doc_id=b"\x11" * 8,
            auth_payload=AuthPayload(
                version=1,
                doc_hash=b"\x22" * 32,
                sign_pub=b"\x44" * 32,
                signature=b"\x55" * 64,
            ),
        )
        root_frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=inspection.doc_id,
            index=0,
            total=1,
            data=b"root",
        )
        foreign_frame = replace(root_frame, doc_id=b"\x99" * 8, data=b"foreign")
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            (root_dir / "recovery_document.pdf").write_bytes(b"pdf")
            shard_path = root_dir / "shard-1111111111111111-1-of-1.pdf"
            shard_path.write_bytes(b"pdf")
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "validate_published_recovery_document_carrier"
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "root_level_key_frame_carriers_from_scan",
                    return_value=((shard_path, (root_frame, foreign_frame)),),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "exactly one distinct KEY frame"):
                    _audit_published_root_fallback_carriers(root_dir, inspection, quiet=True)

    def test_canonical_root_shard_rejects_foreign_only_key_frame(self) -> None:
        inspection, signing_seed = _authenticated_root_audit_inspection()
        root_frame = _signed_root_shard_frames(
            inspection,
            signing_seed,
            share_count=1,
        )[0]
        foreign_frame = replace(root_frame, doc_id=b"\x99" * len(inspection.doc_id))
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            (root_dir / "recovery_document.pdf").write_bytes(b"%PDF-1.4\n")
            shard_path = root_dir / f"shard-{inspection.doc_id.hex()}-1-of-1.pdf"
            shard_path.write_bytes(b"%PDF-1.4\n")
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "validate_published_recovery_document_carrier"
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "root_level_key_frame_carriers_from_scan",
                    return_value=((shard_path, (foreign_frame,)),),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "not bound to the root"):
                    _audit_published_root_fallback_carriers(root_dir, inspection, quiet=True)

    def test_noncanonical_root_shard_pdf_is_audited_but_image_and_foreign_pdf_are_not(
        self,
    ) -> None:
        inspection, signing_seed = _authenticated_root_audit_inspection()
        matching_frame = _signed_root_shard_frames(
            inspection,
            signing_seed,
            share_count=1,
        )[0]
        foreign_frame = replace(matching_frame, doc_id=b"\x99" * len(inspection.doc_id))
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            (root_dir / "recovery_document.pdf").write_bytes(b"%PDF-1.4\n")
            renamed_pdf = root_dir / "renamed-custody-copy.pdf"
            renamed_pdf.write_bytes(b"%PDF-1.4\n")
            image_path = root_dir / "root-shard.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
            foreign_pdf = root_dir / "foreign.pdf"
            foreign_pdf.write_bytes(b"%PDF-1.4\n")
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "validate_published_recovery_document_carrier"
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "root_level_key_frame_carriers_from_scan",
                    return_value=(
                        (renamed_pdf, (matching_frame,)),
                        (image_path, (matching_frame,)),
                        (foreign_pdf, (foreign_frame,)),
                    ),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "validate_published_shard_fallback_carrier"
                ) as validate_shard,
            ):
                _audit_published_root_fallback_carriers(root_dir, inspection, quiet=True)

        validate_shard.assert_called_once_with(path=renamed_pdf, frames=(matching_frame,))

    def test_inspect_from_args_requires_root_dir(self) -> None:
        with self.assertRaises(ExtensionWorkflowError):
            inspect_from_args(ExtensionRequest())

    def test_inspect_from_args_rejects_symlinked_root_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir) / "target"
            root_dir = Path(tmpdir) / "backup-root"
            target_dir.mkdir()
            try:
                root_dir.symlink_to(target_dir, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaises(ExtensionWorkflowError) as ctx:
                inspect_from_args(ExtensionRequest(publish_root=str(root_dir)))

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

            with self.assertRaises(ExtensionWorkflowError) as ctx:
                inspect_from_args(ExtensionRequest(publish_root=str(root_dir)))

        self.assertEqual(ctx.exception.code, "INVALID_INPUT")
        self.assertIn("root backup MAIN carrier must not be a symlink", str(ctx.exception))

    def test_inspect_from_args_reports_discovered_extensions(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.workflows.extension.planning._inspect_root_recovery",
                return_value=_root_recovery(),
            ),
            mock.patch(
                "ethernity.workflows.extension.planning._inspect_published_extension_inventory",
                return_value=_extension_inventory(
                    extensions=(_discovered_extension(doc_hash=b"\xca\xfe\xba\xbe" * 8),),
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
                ExtensionRequest(
                    publish_root=str(root_dir),
                    input_paths=[str(local_dir / "alpha.txt")],
                    input_directories=[str(nested_dir)],
                    base_directory=str(local_dir),
                )
            )

        self.assertEqual(inspection.input_kind, "extended_root")
        self.assertEqual(inspection.discovered_extension_dirs, (1,))
        self.assertEqual(inspection.available_extensions, ())
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

    def test_inspect_from_args_rejects_backup_artifacts_in_selected_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            extension_dir = root_dir / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (root_dir / "qr_document.pdf").write_bytes(b"root qr")
            (root_dir / "recovery_document.pdf").write_bytes(b"root recovery")
            (root_dir / "shard-01.pdf").write_bytes(b"root shard")
            (extension_dir / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"extension")
            (root_dir / "source.txt").write_text("source", encoding="utf-8")

            with self.assertRaises(ExtensionWorkflowError) as ctx:
                inspect_from_args(
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        input_directories=[str(root_dir)],
                        base_directory=str(root_dir),
                    )
                )

        self.assertEqual(ctx.exception.code, "INVALID_INPUT")
        self.assertIn(
            "extend input scope must not include backup root artifacts",
            str(ctx.exception),
        )
        self.assertIn("qr_document.pdf", str(ctx.exception))
        self.assertIn("extensions", str(ctx.exception))

    def test_inspect_from_args_surfaces_invalid_layout_as_blocking_issue(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.workflows.extension.planning._inspect_root_recovery",
                return_value=_root_recovery(),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            (root_dir / "extensions" / "001").mkdir(parents=True)

            inspection = inspect_from_args(ExtensionRequest(publish_root=str(root_dir)))

        self.assertEqual(inspection.input_kind, "standalone_root")
        self.assertEqual(inspection.discovered_extension_dirs, ())
        self.assertEqual(inspection.available_extensions, ())
        self.assertEqual(inspection.blocking_issues[0].code, "EXTENSION_LAYOUT_INVALID")

    def test_inspect_from_args_rejects_invalid_extension_doc_id_filename(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.workflows.extension.planning._inspect_root_recovery",
                return_value=_root_recovery(),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            extension_dir = root_dir / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (extension_dir / "qr_document-01-abc.pdf").write_bytes(b"x")
            (extension_dir / "recovery_document-01-abc.pdf").write_bytes(b"y")

            inspection = inspect_from_args(ExtensionRequest(publish_root=str(root_dir)))

        self.assertEqual(inspection.discovered_extension_dirs, ())
        self.assertEqual(inspection.available_extensions, ())
        self.assertEqual(inspection.blocking_issues[0].code, "EXTENSION_LAYOUT_INVALID")
        self.assertIn(
            "invalid extension MAIN carrier filename",
            inspection.blocking_issues[0].message,
        )

    def test_inspect_from_args_rejects_corrupt_canonical_extension_inventory(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.workflows.extension.planning._inspect_root_recovery",
                return_value=_root_recovery(),
            ),
            mock.patch(
                "ethernity.workflows.extension.planning._inspect_published_extension_inventory",
                return_value=_extension_inventory(
                    failure=RecoveryReplayFailure(
                        stage="discovery",
                        message="extension 01 MAIN carriers could not be reconstructed",
                        head_index=1,
                        head_dir_name="01",
                    )
                ),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            extension_dir = root_dir / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (extension_dir / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"x")
            (extension_dir / "recovery_document-01-deadbeefcafebabe.pdf").write_bytes(b"y")

            inspection = inspect_from_args(ExtensionRequest(publish_root=str(root_dir)))

        self.assertEqual(inspection.discovered_extension_dirs, (1,))
        self.assertEqual(inspection.available_extensions, ())
        self.assertEqual(inspection.blocking_issues[0].code, "EXTENSION_LAYOUT_INVALID")
        self.assertIn(
            "extension 01 MAIN carriers could not be reconstructed",
            inspection.blocking_issues[0].message,
        )

    def test_inspect_from_args_base_dir_only_uses_canonical_selected_scope_shape(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.workflows.extension.planning._inspect_root_recovery",
                return_value=_root_recovery(),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir(parents=True)

            inspection = inspect_from_args(
                ExtensionRequest(
                    publish_root=str(root_dir),
                    base_directory=str(Path(tmpdir) / "scope"),
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

    def test_inspect_from_args_uses_qr_document_as_machine_extension_carrier(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.workflows.extension.planning._inspect_root_recovery",
                return_value=_root_recovery(),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            extension_dir = root_dir / "extensions" / "01"
            qr_path = extension_dir / "qr_document-01-1111111111111111.pdf"
            recovery_path = extension_dir / "recovery_document-01-1111111111111111.pdf"
            extension_dir.mkdir(parents=True)
            qr_path.write_bytes(b"x")
            recovery_path.write_bytes(b"y")
            (extension_dir / "recovery_kit-01-1111111111111111.pdf").write_bytes(b"kit")

            def _scan(paths: list[str], *, quiet: bool = False):
                _ = quiet
                self.assertEqual(len(paths), 1)
                if paths == [str(qr_path)]:
                    return (
                        b"extension-ciphertext",
                        [
                            Frame(
                                version=1,
                                frame_type=FrameType.AUTH,
                                doc_id=b"\x11" * 8,
                                index=0,
                                total=1,
                                data=b"auth",
                            )
                        ],
                    )
                if paths == [str(recovery_path)]:
                    raise AssertionError("recovery_document must not be machine-scanned")
                raise AssertionError(f"unexpected carrier paths: {paths!r}")

            with (
                mock.patch(
                    "ethernity.workflows.extension.planning.scan_extension_carriers",
                    side_effect=_scan,
                ) as scan_mock,
                mock.patch(
                    "ethernity.extensions.published.resolve_required_auth_payload",
                    return_value=(SimpleNamespace(sign_pub=b"\x44" * 32), "verified"),
                ),
                mock.patch(
                    "ethernity.extensions.recovery.doc_id_and_hash_from_ciphertext",
                    return_value=(b"\x11" * 8, b"\x22" * 32),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "validate_published_recovery_document_carrier",
                    return_value=None,
                ),
            ):
                inspection = inspect_from_args(ExtensionRequest(publish_root=str(root_dir)))

        self.assertEqual(scan_mock.call_args_list, [mock.call([str(qr_path)], quiet=False)])
        self.assertEqual(inspection.discovered_extension_dirs, (1,))

    def test_inspect_from_args_rejects_invalid_recovery_document_without_machine_scan(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.workflows.extension.planning._inspect_root_recovery",
                return_value=_root_recovery(),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            extension_dir = root_dir / "extensions" / "01"
            qr_path = extension_dir / "qr_document-01-1111111111111111.pdf"
            recovery_path = extension_dir / "recovery_document-01-1111111111111111.pdf"
            extension_dir.mkdir(parents=True)
            qr_path.write_bytes(b"x")
            recovery_path.write_bytes(b"not a pdf and not fallback text")
            (extension_dir / "recovery_kit-01-1111111111111111.pdf").write_bytes(b"kit")

            with (
                mock.patch(
                    "ethernity.workflows.extension.planning.scan_extension_carriers",
                    return_value=(
                        b"extension-ciphertext",
                        [
                            Frame(
                                version=1,
                                frame_type=FrameType.AUTH,
                                doc_id=b"\x11" * 8,
                                index=0,
                                total=1,
                                data=b"auth",
                            )
                        ],
                    ),
                ) as scan_mock,
                mock.patch(
                    "ethernity.extensions.published.resolve_required_auth_payload",
                    return_value=(SimpleNamespace(sign_pub=b"\x44" * 32), "verified"),
                ),
                mock.patch(
                    "ethernity.extensions.recovery.doc_id_and_hash_from_ciphertext",
                    return_value=(b"\x11" * 8, b"\x22" * 32),
                ),
            ):
                inspection = inspect_from_args(ExtensionRequest(publish_root=str(root_dir)))

        self.assertEqual(scan_mock.call_args_list, [mock.call([str(qr_path)], quiet=False)])
        self.assertEqual(inspection.discovered_extension_dirs, ())
        self.assertEqual(inspection.available_extensions, ())
        self.assertEqual(inspection.blocking_issues[0].code, "EXTENSION_LAYOUT_INVALID")
        self.assertIn(
            "recovery_document carrier could not be validated",
            inspection.blocking_issues[0].message,
        )

    def test_inspect_from_args_rejects_valid_prefix_when_suffix_is_invalid(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.workflows.extension.planning._inspect_root_recovery",
                return_value=_root_recovery(),
            ),
            mock.patch(
                "ethernity.workflows.extension.planning._inspect_published_extension_inventory",
                return_value=_extension_inventory(
                    extensions=(_discovered_extension(),),
                    failure=RecoveryReplayFailure(
                        stage="discovery",
                        message="missing required MAIN documents",
                        head_index=2,
                        head_dir_name="02",
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

            inspection = inspect_from_args(ExtensionRequest(publish_root=str(root_dir)))

        self.assertEqual(inspection.input_kind, "standalone_root")
        self.assertEqual(inspection.discovered_extension_dirs, ())
        self.assertEqual(inspection.available_extensions, ())
        self.assertEqual(inspection.blocking_issues[0].code, "EXTENSION_LAYOUT_INVALID")
        self.assertIn(
            "missing required MAIN documents",
            inspection.blocking_issues[0].message,
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
            ExtensionRequest(shard_frames=[shard_frame]),
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
                **_root_inspection(passphrase="secret", authenticated=True).__dict__,
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
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(unlocked_root, "none"),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning.extract_root_logical_state",
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
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        input_paths=[str(local_dir / "alpha.txt")],
                        base_directory=str(local_dir),
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

    def test_scanned_chain_resolution_reuses_root_selection_decrypt_session(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        base_root = _root_inspection(passphrase="secret")
        unlocked_root = replace(
            base_root,
            unlock=replace(base_root.unlock, satisfied=True),
        )
        imported_document = _discovered_extension()
        decoded_import_session = SimpleNamespace(root_document=mock.sentinel.root_document)

        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir()
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(
                        unlocked_root,
                        "none",
                        (imported_document,),
                        decoded_import_session,
                    ),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    side_effect=AssertionError("root ciphertext was decrypted twice"),
                ) as decode_root_manifest,
                mock.patch(
                    "ethernity.workflows.extension.planning.decode_imported_root_manifest",
                    return_value=(manifest, payload),
                ) as decode_imported_root_manifest,
                mock.patch(
                    "ethernity.workflows.extension.planning."
                    "_scan_extension_inventory_from_imported_documents",
                    return_value=_extension_inventory(),
                ) as scan_extension_inventory,
            ):
                resolved = resolve_extend_state(
                    ExtensionRequest(publish_root=str(root_dir), passphrase="secret")
                )

        self.assertEqual(resolved.inspection.validated_head_index, 0)
        decode_root_manifest.assert_not_called()
        decode_imported_root_manifest.assert_called_once_with(
            mock.sentinel.root_document,
            decoded_import_session=decoded_import_session,
        )
        self.assertIs(
            scan_extension_inventory.call_args.kwargs["decoded_import_session"],
            decoded_import_session,
        )

    def test_inspect_from_args_reports_unlock_unsatisfied_when_decrypt_fails(self) -> None:
        base_root = _root_inspection(passphrase="wrong-passphrase")
        unlocked_root = replace(
            base_root,
            unlock=replace(
                base_root.unlock,
                passphrase_provided=True,
                satisfied=True,
                resolved_passphrase="wrong-passphrase",
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir()
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(unlocked_root, "none"),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    side_effect=ValueError("decrypt failed"),
                ),
            ):
                inspection = inspect_from_args(
                    ExtensionRequest(publish_root=str(root_dir), passphrase="wrong-passphrase")
                )

        self.assertFalse(inspection.unlock["satisfied"])
        self.assertIsNone(inspection.source_summary)
        self.assertIn("UNLOCK_FAILED", {issue.code for issue in inspection.blocking_issues})

    def test_inspect_from_args_blocks_directory_scope_deletes(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (
                PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),
                PayloadPart(path="beta.txt", data=b"beta", mtime=1),
            ),
            sealed=False,
            signing_seed=b"\x33" * 32,
            created_at=1.0,
            input_origin="directory",
            input_roots=("scope",),
        )
        unlocked_root = RecoveryInspection(
            **{
                **_root_inspection(passphrase="secret", authenticated=True).__dict__,
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
            local_dir = Path(tmpdir) / "scope"
            root_dir.mkdir()
            local_dir.mkdir()
            (local_dir / "alpha.txt").write_text("alpha", encoding="utf-8")
            alpha_mtime = int((local_dir / "alpha.txt").stat().st_mtime)
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(unlocked_root, "none"),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning.extract_root_logical_state",
                    return_value=(
                        LogicalFileState(
                            path="alpha.txt",
                            size=5,
                            sha256=manifest.files[0].sha256,
                            mtime=alpha_mtime,
                            data=b"alpha",
                        ),
                        LogicalFileState(
                            path="beta.txt",
                            size=4,
                            sha256=manifest.files[1].sha256,
                            mtime=1,
                            data=b"beta",
                        ),
                    ),
                ),
            ):
                inspection = inspect_from_args(
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        input_directories=[str(local_dir)],
                        base_directory=str(local_dir),
                        passphrase="secret",
                    )
                )

        self.assertEqual(inspection.diff_summary["missing_paths"], ["beta.txt"])
        self.assertIn(
            {
                "code": api_codes.DELETE_NOT_SUPPORTED,
                "message": (
                    "selected scope omits previously backed paths; Add Files cannot delete or "
                    "rename paths. Create a New Backup from the desired files and retire the "
                    "superseded carriers"
                ),
                "details": {"missing_paths": ["beta.txt"]},
            },
            tuple(issue.to_dict() for issue in inspection.blocking_issues),
        )

    def test_inspect_from_args_blocks_exact_file_path_alias_without_base_dir(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="docs/a.txt", data=b"old", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            created_at=1.0,
            input_origin="directory",
            input_roots=("scope",),
        )
        unlocked_root = RecoveryInspection(
            **{
                **_root_inspection(passphrase="secret", authenticated=True).__dict__,
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
            local_docs = Path(tmpdir) / "scope" / "docs"
            root_dir.mkdir()
            local_docs.mkdir(parents=True)
            (local_docs / "a.txt").write_text("new", encoding="utf-8")
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(unlocked_root, "none"),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning.extract_root_logical_state",
                    return_value=(
                        LogicalFileState(
                            path="docs/a.txt",
                            size=3,
                            sha256=manifest.files[0].sha256,
                            mtime=1,
                            data=b"old",
                        ),
                    ),
                ),
            ):
                inspection = inspect_from_args(
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        input_paths=[str(local_docs / "a.txt")],
                        passphrase="secret",
                    )
                )

        self.assertEqual(inspection.diff_summary["new_paths"], ["a.txt"])
        self.assertIn(
            {
                "code": api_codes.INVALID_INPUT,
                "message": (
                    "selected input paths would create new logical paths that look like existing "
                    "backed paths; provide --base-dir to disambiguate"
                ),
                "details": {
                    "path_aliases": [
                        {"selected_path": "a.txt", "existing_path": "docs/a.txt"},
                    ]
                },
            },
            tuple(issue.to_dict() for issue in inspection.blocking_issues),
        )

    def test_resolve_extend_state_carries_validated_root_shard_policy(self) -> None:
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
                    mode="shards",
                    passphrase_provided=False,
                    validated_shard_count=2,
                    required_shard_threshold=2,
                    shard_share_count=5,
                    satisfied=True,
                    resolved_passphrase="secret",
                    blocking_issues=(),
                ),
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir()
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(unlocked_root, "root"),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning.extract_root_logical_state",
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
                resolved = resolve_extend_state(ExtensionRequest(publish_root=str(root_dir)))

        self.assertEqual(resolved.root_passphrase_shard_threshold, 2)
        self.assertEqual(resolved.root_passphrase_shard_count, 5)
        self.assertEqual(resolved.inspection.unlock["mode"], "shards")
        self.assertEqual(resolved.inspection.unlock["validated_shard_count"], 2)
        self.assertEqual(resolved.inspection.unlock["required_shard_threshold"], 2)
        self.assertEqual(resolved.inspection.unlock["shard_share_count"], 5)

    def test_resolve_extend_state_defers_published_root_shard_policy_with_passphrase(
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

        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir()
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(unlocked_root, "none"),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning.extract_root_logical_state",
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
                resolved = resolve_extend_state(
                    ExtensionRequest(publish_root=str(root_dir), passphrase="secret")
                )

        self.assertIsNone(resolved.root_passphrase_shard_threshold)
        self.assertEqual(resolved.root_passphrase_shard_count, 0)

    def test_inspect_root_recovery_ignores_fallback_only_root_recovery_document(self) -> None:
        root_inspection = _root_inspection(passphrase="secret")
        qr_path = Path("/tmp/root/qr_document.pdf")
        recovery_path = Path("/tmp/root/recovery_document.pdf")
        root_frame = Frame(1, FrameType.MAIN_DOCUMENT, b"\x11" * 8, 0, 1, b"root")

        def _scan(paths: list[str], *, quiet: bool = False) -> FrameInputResult:
            _ = quiet
            self.assertEqual(len(paths), 1)
            if paths == [str(qr_path)]:
                return FrameInputResult(frames=(root_frame,))
            if paths == [str(recovery_path)]:
                raise NoQrFramesError(
                    f"scan failed: explicit scan input contains no QR codes: {recovery_path}"
                )
            raise AssertionError(f"unexpected scan paths: {paths!r}")

        with (
            mock.patch(
                "ethernity.workflows.extension.planning._published_root_scan_paths",
                return_value=[str(qr_path), str(recovery_path)],
            ),
            mock.patch(
                "ethernity.workflows.extension.planning.recovery_frames_from_scan",
                side_effect=_scan,
            ) as recovery_frames_from_scan,
            mock.patch(
                "ethernity.workflows.extension.planning._shard_frames_from_extend_args",
                return_value=([], [], [], []),
            ),
            mock.patch(
                "ethernity.workflows.extension.planning.inspect_recovery_inputs",
                return_value=root_inspection,
            ) as inspect_recovery_inputs,
        ):
            recovery = _inspect_root_recovery(
                Path("/tmp/root"),
                ExtensionRequest(publish_root="/tmp/root", passphrase="secret"),
                extension_inventory=None,
            )

        self.assertEqual(recovery.shard_unlock_target, "none")
        self.assertEqual(recovery_frames_from_scan.call_count, 2)
        inspect_recovery_inputs.assert_called_once()
        self.assertEqual(inspect_recovery_inputs.call_args.kwargs["frames"], [root_frame])

    def test_inspect_root_recovery_surfaces_extension_shard_selection_failure(self) -> None:
        root_inspection = replace(_root_inspection(), doc_id=b"\x11" * 8)
        shard_frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x33" * 8,
            index=0,
            total=1,
            data=b"shard",
        )
        inventory = _recovery_chain_inspection(
            extensions=(_discovered_extension(doc_hash=b"\x44" * 32),)
        ).inventory

        with (
            mock.patch(
                "ethernity.workflows.extension.planning._published_root_scan_paths",
                return_value=[Path("/tmp/root/recovery.pdf")],
            ),
            mock.patch(
                "ethernity.workflows.extension.planning.recovery_frames_from_scan",
                return_value=FrameInputResult(
                    frames=(Frame(1, FrameType.MAIN_DOCUMENT, b"\x11" * 8, 0, 1, b"root"),)
                ),
            ),
            mock.patch(
                "ethernity.workflows.extension.planning._shard_frames_from_extend_args",
                return_value=([shard_frame], [], ["/tmp/shards.txt"], []),
            ),
            mock.patch(
                "ethernity.workflows.extension.planning.inspect_recovery_inputs",
                return_value=root_inspection,
            ),
            mock.patch(
                "ethernity.workflows.extension.planning."
                "select_root_import_document_from_passphrase_shards",
                side_effect=ValueError(
                    "shard payloads do not match any imported recovery document"
                ),
            ),
        ):
            recovery = _inspect_root_recovery(
                Path("/tmp/root"),
                ExtensionRequest(publish_root="/tmp/root", shard_payload_files=["/tmp/shards.txt"]),
                extension_inventory=inventory,
            )

        self.assertEqual(recovery.shard_unlock_target, "extension")
        issue = recovery.inspection.blocking_issues[-1]
        self.assertEqual(issue["code"], api_codes.PASSPHRASE_SHARDS_INVALID)
        self.assertIn(
            "shard payloads do not match any imported recovery document",
            str(issue["message"]),
        )
        self.assertEqual(issue["details"], {"stage": "extension_shard_unlock"})
        self.assertEqual(recovery.inspection.shard_payloads_file, ("/tmp/shards.txt",))

    def test_published_append_resource_admission_precedes_extension_shard_unlock(self) -> None:
        root_inspection = replace(_root_inspection(), doc_id=b"\x11" * 8)
        shard_frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x33" * 8,
            index=0,
            total=1,
            data=b"shard",
        )
        extension = _discovered_extension(doc_hash=b"\x44" * 32)
        inventory = _recovery_chain_inspection(extensions=(extension,)).inventory

        with (
            mock.patch(
                "ethernity.workflows.extension.planning._published_root_scan_paths",
                return_value=[Path("/tmp/root/recovery.pdf")],
            ),
            mock.patch(
                "ethernity.workflows.extension.planning.recovery_frames_from_scan",
                return_value=FrameInputResult(
                    frames=(Frame(1, FrameType.MAIN_DOCUMENT, b"\x11" * 8, 0, 1, b"root"),)
                ),
            ),
            mock.patch(
                "ethernity.workflows.extension.planning._shard_frames_from_extend_args",
                return_value=([shard_frame], [], ["/tmp/shards.txt"], []),
            ),
            mock.patch(
                "ethernity.workflows.extension.planning.inspect_recovery_inputs",
                return_value=root_inspection,
            ) as inspect_recovery_inputs,
            mock.patch(
                "ethernity.workflows.extension.planning.require_chain_resource_limits",
                side_effect=ValueError("extension append exceeds resource limit"),
            ) as require_resource_limits,
            mock.patch(
                "ethernity.workflows.extension.planning."
                "select_root_import_document_from_passphrase_shards",
            ) as select_root,
            self.assertRaisesRegex(ValueError, "exceeds resource limit"),
        ):
            _inspect_root_recovery(
                Path("/tmp/root"),
                ExtensionRequest(publish_root="/tmp/root", shard_payload_files=["/tmp/shards.txt"]),
                extension_inventory=inventory,
            )

        require_resource_limits.assert_called_once_with(
            document_count=3,
            total_ciphertext_bytes=(len(b"root") + len(extension.ciphertext) + 1),
            operation="extension append",
        )
        inspect_recovery_inputs.assert_not_called()
        select_root.assert_not_called()

    def test_inspect_root_recovery_blocks_extension_shards_for_wrong_root(self) -> None:
        root_inspection = replace(_root_inspection(), doc_id=b"\x11" * 8)
        shard_frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x33" * 8,
            index=0,
            total=1,
            data=b"shard",
        )
        inventory = _recovery_chain_inspection(
            extensions=(_discovered_extension(doc_hash=b"\x44" * 32),)
        ).inventory
        selection = SimpleNamespace(
            root_document=SimpleNamespace(doc_id=b"\x99" * 8, doc_hash=b"\xaa" * 32),
            unlock=RecoveryUnlockStatus(
                mode="shards",
                passphrase_provided=False,
                validated_shard_count=2,
                required_shard_threshold=2,
                shard_share_count=3,
                satisfied=True,
                resolved_passphrase="secret",
                blocking_issues=(),
            ),
        )

        with (
            mock.patch(
                "ethernity.workflows.extension.planning._published_root_scan_paths",
                return_value=[Path("/tmp/root/recovery.pdf")],
            ),
            mock.patch(
                "ethernity.workflows.extension.planning.recovery_frames_from_scan",
                return_value=FrameInputResult(
                    frames=(Frame(1, FrameType.MAIN_DOCUMENT, b"\x11" * 8, 0, 1, b"root"),)
                ),
            ),
            mock.patch(
                "ethernity.workflows.extension.planning._shard_frames_from_extend_args",
                return_value=([shard_frame], [], ["/tmp/shards.txt"], []),
            ),
            mock.patch(
                "ethernity.workflows.extension.planning.inspect_recovery_inputs",
                return_value=root_inspection,
            ),
            mock.patch(
                "ethernity.workflows.extension.planning."
                "select_root_import_document_from_passphrase_shards",
                return_value=selection,
            ),
        ):
            recovery = _inspect_root_recovery(
                Path("/tmp/root"),
                ExtensionRequest(publish_root="/tmp/root", shard_payload_files=["/tmp/shards.txt"]),
                extension_inventory=inventory,
            )

        issue = recovery.inspection.blocking_issues[-1]
        self.assertEqual(issue["code"], api_codes.PASSPHRASE_SHARDS_INVALID)
        self.assertIn("resolved a different root document", str(issue["message"]))
        self.assertEqual(issue["details"]["stage"], "extension_shard_unlock")
        self.assertEqual(issue["details"]["expected_root_doc_id"], "11" * 8)
        self.assertEqual(issue["details"]["selected_root_doc_id"], "99" * 8)

    def test_root_only_head_authority_requires_verified_auth_status(self) -> None:
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
                **_root_inspection(passphrase="secret", auth_status="missing").__dict__,
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
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(unlocked_root, "none"),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning.extract_root_logical_state",
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
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        input_paths=[str(root_dir / "alpha.txt")],
                        passphrase="secret",
                    )
                )

        self.assertEqual(inspection.validated_head_index, 0)
        self.assertEqual(inspection.validated_head_auth_status, "missing")
        self.assertFalse(inspection.validated_head_root_authority_verified)

    def test_published_root_shard_policy_does_not_infer_under_quorum_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            (root_dir / "renamed-root-shard.pdf").write_bytes(b"pdf")

            with (
                mock.patch(
                    "ethernity.workflows.extension.root_shards.root_level_key_frames_from_scan",
                    return_value=[object()],
                ),
                mock.patch(
                    "ethernity.workflows.extension.root_shards.root_shard_quorum_from_frames",
                    side_effect=InsufficientShardError(
                        threshold=2,
                        provided_count=1,
                        share_count=3,
                        secret_label="passphrase",
                    ),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "under quorum"):
                    published_root_passphrase_shard_policy(
                        root_dir,
                        root_doc_id=b"\x01" * 8,
                        root_doc_hash=b"\x02" * 32,
                        sign_pub=b"\x03" * 32,
                        quiet=True,
                    )

    def test_published_root_shard_policy_rejects_symlinked_shards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            target = root_dir / "outside.pdf"
            target.write_bytes(b"pdf")
            (root_dir / "renamed-root-shard.pdf").symlink_to(target)

            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                published_root_passphrase_shard_policy(
                    root_dir,
                    root_doc_id=b"\x01" * 8,
                    root_doc_hash=b"\x02" * 32,
                    sign_pub=b"\x03" * 32,
                    quiet=True,
                )

    def test_published_root_shard_policy_rejects_unsigned_auto_discovered_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            (root_dir / "renamed-root-shard.pdf").write_bytes(b"pdf")

            with (
                mock.patch(
                    "ethernity.workflows.extension.root_shards.root_level_key_frames_from_scan",
                    return_value=[object()],
                ),
                mock.patch(
                    "ethernity.workflows.extension.root_shards.has_potential_root_shard_frames",
                    return_value=True,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "verified root signing authority"):
                    published_root_passphrase_shard_policy(
                        root_dir,
                        root_doc_id=b"\x01" * 8,
                        root_doc_hash=b"\x02" * 32,
                        sign_pub=None,
                        quiet=True,
                    )

    def test_resolve_extend_state_uses_configured_chunking_for_new_chain(self) -> None:
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

        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            config_path = Path(tmpdir) / "config.toml"
            root_dir.mkdir()
            config_path.write_text(
                """
[defaults.backup]
qr_payload_codec = "raw"

[extension.chunking]
target_size = 16384
min_size = 4096
max_size = 65536
""",
                encoding="utf-8",
            )
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(unlocked_root, "none"),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning.extract_root_logical_state",
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
                resolved = resolve_extend_state(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        passphrase="secret",
                    )
                )

        self.assertIsNotNone(resolved.chunking)
        assert resolved.chunking is not None
        self.assertEqual(resolved.chunking.target_size, 16384)
        self.assertEqual(resolved.chunking.min_size, 4096)
        self.assertEqual(resolved.chunking.max_size, 65536)

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
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(unlocked_root, "none"),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning.extract_root_logical_state",
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
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        input_paths=[str(root_dir / "alpha.txt")],
                        passphrase="secret",
                    )
                )

        self.assertEqual(inspection.signing_authority["available"], True)
        self.assertEqual(inspection.signing_authority["satisfied"], False)
        self.assertIsNone(inspection.signing_authority["source"])
        self.assertEqual(inspection.blocking_issues[0].code, "ROOT_AUTHORITY_MISMATCH")

    def test_inspect_from_args_reports_post_unlock_state_errors_as_chain_invalid(self) -> None:
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

        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir()
            with (
                mock.patch(
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(unlocked_root, "none"),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning.extract_root_logical_state",
                    side_effect=ValueError("invalid logical root state"),
                ),
            ):
                inspection = inspect_from_args(
                    ExtensionRequest(publish_root=str(root_dir), passphrase="secret")
                )

        issue_codes = {issue.code for issue in inspection.blocking_issues}
        self.assertIn(api_codes.CHAIN_INVALID, issue_codes)
        self.assertNotIn("UNLOCK_FAILED", issue_codes)
        self.assertEqual(inspection.blocking_issues[0].details, {"stage": "chain"})

    def test_expected_head_guard_canonicalizes_args_on_mismatch(self) -> None:
        args = ExtensionRequest(expected_head_doc_hash=f" {'AA' * 32} ")
        issue = _expected_head_issue(
            args,
            validated_head_index=1,
            validated_head_doc_hash="22" * 32,
        )

        self.assertIsNotNone(issue)
        assert issue is not None
        self.assertEqual(args.expected_head_doc_hash, "aa" * 32)
        self.assertEqual(issue.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(
            issue.details["expected_head_doc_hash"],
            "aa" * 32,
        )

    def test_scan_mode_requires_expected_head_or_explicit_stale_ack(self) -> None:
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
        cases = (
            ({}, True),
            ({"expected_head_doc_hash": "22" * 32}, False),
            ({"allow_stale_head": True}, False),
        )
        for arg_overrides, should_block in cases:
            with self.subTest(arg_overrides=arg_overrides), tempfile.TemporaryDirectory() as tmpdir:
                root_dir = Path(tmpdir) / "publish-root"
                with (
                    mock.patch(
                        "ethernity.workflows.extension.planning._inspect_root_recovery",
                        return_value=_RootRecoveryInspection(unlocked_root, "none"),
                    ),
                    mock.patch(
                        "ethernity.workflows.extension.planning._decode_root_manifest",
                        return_value=(manifest, payload),
                    ),
                    mock.patch(
                        "ethernity.workflows.extension.planning.extract_root_logical_state",
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
                        ExtensionRequest(
                            publish_root=str(root_dir),
                            scan_paths=["root.pdf"],
                            passphrase="secret",
                            **arg_overrides,
                        )
                    )

            issue_codes = [issue.code for issue in inspection.blocking_issues]
            self.assertEqual(inspection.input_kind, "scanned_chain")
            self.assertEqual(inspection.validated_head_doc_hash, "22" * 32)
            if should_block:
                self.assertIn(api_codes.RECOVERY_HEAD_UNTRUSTED, issue_codes)
                issue = inspection.blocking_issues[0]
                self.assertEqual(issue.details["validated_head_index"], 0)
                self.assertEqual(issue.details["validated_head_doc_hash"], "22" * 32)
                self.assertEqual(issue.details["freshness_scope"], "supplied_carriers_only")
            else:
                self.assertNotIn(api_codes.RECOVERY_HEAD_UNTRUSTED, issue_codes)

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
                **_root_inspection(passphrase="secret", authenticated=True).__dict__,
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
                "latest supplied recovery head could not be trusted: "
                "extension directory 02 is missing "
                "required MAIN documents: recovery_document"
            ),
            details={
                "stage": "replay",
                "failure_stage": "discovery",
                "failure_message": (
                    "extension directory 02 is missing required MAIN documents: recovery_document"
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
        extension = ImportedRecoveryDocument.from_ciphertext(
            ciphertext=b"extension-01",
            auth_frames=(),
            source_label="01",
            extension_index=1,
            extension_dir_name="01",
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
                            "extension directory 02 is missing required MAIN documents: "
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
                    "ethernity.workflows.extension.planning._inspect_published_extension_inventory",
                    return_value=chain_inspection.inventory,
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(unlocked_root, "none"),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning.extract_root_logical_state",
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
                    "ethernity.workflows.extension.planning._inspect_published_extension_chain",
                    return_value=chain_inspection,
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._replay_authenticated_chain_state",
                    return_value=mock.sentinel.validated_chain_state,
                ),
            ):
                inspection = inspect_from_args(
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        input_paths=[str(root_dir / "alpha.txt")],
                        passphrase="secret",
                    )
                )

        self.assertEqual(inspection.input_kind, "extended_root")
        self.assertEqual(inspection.discovered_extension_dirs, (1,))
        self.assertEqual(inspection.validated_head_index, 0)
        self.assertEqual(inspection.validated_head_doc_hash, "22" * 32)
        self.assertEqual(inspection.validated_head_auth_status, "verified")
        self.assertTrue(inspection.validated_head_root_authority_verified)
        self.assertEqual(inspection.available_extensions, ())
        expected_details = {
            **degraded_refusal.details,
            "validated_head_auth_status": "verified",
            "validated_head_root_authority_verified": True,
        }
        self.assertEqual(inspection.blocking_issues[0].code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(inspection.blocking_issues[0].details, expected_details)
        self.assertEqual(inspection.blocking_issues[0].details["failure_stage"], "discovery")
        self.assertEqual(inspection.blocking_issues[0].details["validated_head_index"], 0)
        self.assertNotIn("CHAIN_INVALID", [issue.code for issue in inspection.blocking_issues])
        self.assertNotIn(
            "EXTENSION_LAYOUT_INVALID",
            [issue.code for issue in inspection.blocking_issues],
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
                **_root_inspection(passphrase="secret", authenticated=True).__dict__,
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
        extension = ImportedRecoveryDocument.from_ciphertext(
            ciphertext=b"extension-01",
            auth_frames=(),
            source_label="01",
            extension_index=1,
            extension_dir_name="01",
        )
        decoded_link = mock.Mock(
            auth_status="verified",
            root_authority_verified=True,
            link=mock.Mock(doc_hash=extension.doc_hash),
        )
        decoded_link.link.document.header.index = 1
        decoded_link.link.document.chunks = ()
        decoded_link.link.document.inline_chunk_raw_bytes = 0
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
                    "ethernity.workflows.extension.planning._inspect_root_recovery",
                    return_value=_RootRecoveryInspection(unlocked_root, "none"),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._decode_root_manifest",
                    return_value=(manifest, payload),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning.extract_root_logical_state",
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
                    "ethernity.workflows.extension.planning._inspect_published_extension_inventory",
                    return_value=_extension_inventory(extensions=(extension,)),
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._inspect_published_extension_chain",
                    return_value=chain_inspection,
                ),
                mock.patch(
                    "ethernity.workflows.extension.planning._replay_authenticated_chain_state",
                    return_value=mock.sentinel.validated_chain_state,
                ),
            ):
                inspection = inspect_from_args(
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        input_paths=[str(root_dir / "alpha.txt")],
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
                    "index": 1,
                    "dir_name": "01",
                    "doc_id": extension.doc_id_hex,
                    "doc_hash": extension.doc_hash.hex(),
                    "auth_status": "verified",
                    "root_authority_verified": True,
                },
            ),
        )
