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

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import ethernity.cli.features.recover.chain as recover_chain_module
from ethernity.cli.features.recover.chain import (
    DecodedExtensionLink,
    DiscoveredRecoveryExtension,
    decode_authenticated_extension_link,
    detect_recovery_root_dir,
    discover_recovery_extensions,
    recover_chain_entries,
    scan_extension_carriers,
)
from ethernity.cli.features.recover.planning import RecoveryPlan
from ethernity.cli.shared.crypto import _doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.types import InputFile
from ethernity.crypto.signing import AuthPayload, derive_public_key, encode_auth_payload, sign_auth
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.extensions.build import build_extension_document
from ethernity.extensions.chain import ExtensionChainLink
from ethernity.extensions.discovery import (
    DiscoveredExtensionDirectory,
    DiscoveredExtensionMainCarrier,
    ValidatedExtensionDiscovery,
)
from ethernity.formats.envelope_codec import (
    build_manifest_and_payload,
    decode_any_envelope,
    encode_envelope,
    encode_extension_envelope,
)
from ethernity.formats.envelope_types import PayloadPart
from ethernity.formats.extension_envelope import ExtensionChunkingProfile, ExtensionEnvelope
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC


def _root_ciphertext() -> tuple[bytes, bytes, bytes]:
    manifest, payload = build_manifest_and_payload(
        (PayloadPart(path="a.txt", data=b"root", mtime=1),),
        sealed=False,
        signing_seed=b"\x33" * 32,
        input_origin="file",
        input_roots=(),
    )
    envelope = encode_envelope(payload, manifest)
    doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(envelope)
    return envelope, doc_id, doc_hash


def _extension_ciphertext(
    root_doc_hash: bytes,
    *,
    index: int = 1,
    parent_doc_hash: bytes | None = None,
    reuse_root_chunk: bool = False,
    input_origin: str = "file",
    input_roots: tuple[str, ...] = (),
    relative_path: str = "a.txt",
    data: bytes = b"root!",
) -> bytes:
    root_chunk = b"root"
    updated = data
    built = build_extension_document(
        index=index,
        parent_doc_hash=parent_doc_hash or root_doc_hash,
        root_doc_hash=root_doc_hash,
        chunking=ExtensionChunkingProfile(
            algorithm_id=CHUNK_ALGORITHM_FASTCDC,
            target_size=64 * 1024,
            min_size=16 * 1024,
            max_size=256 * 1024,
        ),
        input_files=(
            InputFile(
                source_path=None,
                relative_path=relative_path,
                data=updated,
                mtime=2,
            ),
        ),
        input_origin=input_origin,
        input_roots=input_roots,
        chunker=(
            (lambda data, _profile: (root_chunk, data[len(root_chunk) :]))
            if reuse_root_chunk
            else (lambda data, _profile: (data,))
        ),
        existing_chunks=(
            {hashlib.sha256(root_chunk).digest(): root_chunk} if reuse_root_chunk else None
        ),
    )
    return encode_extension_envelope(built.document)


def _extension_auth_frame(
    extension_doc_id: bytes,
    extension_doc_hash: bytes,
    *,
    signing_seed: bytes = b"\x33" * 32,
) -> Frame:
    sign_pub = derive_public_key(signing_seed)
    return Frame(
        version=VERSION,
        frame_type=FrameType.AUTH,
        doc_id=extension_doc_id,
        index=0,
        total=1,
        data=encode_auth_payload(
            extension_doc_hash,
            sign_pub=sign_pub,
            signature=sign_auth(
                extension_doc_hash,
                sign_pub=sign_pub,
                sign_priv=signing_seed,
            ),
        ),
    )


def _recovery_plan(
    root_ciphertext: bytes,
    root_doc_id: bytes,
    root_doc_hash: bytes,
    *,
    extension_index: int | None = 1,
    extension_doc_hash: str | None = None,
    auth_payload: AuthPayload | None = None,
    auth_status: str = "verified",
    allow_unsigned: bool = False,
) -> RecoveryPlan:
    resolved_auth_payload = auth_payload
    if resolved_auth_payload is None and not allow_unsigned:
        root_sign_pub = derive_public_key(b"\x33" * 32)
        resolved_auth_payload = AuthPayload(
            version=1,
            doc_hash=root_doc_hash,
            sign_pub=root_sign_pub,
            signature=b"\x99" * 64,
        )
    return RecoveryPlan(
        ciphertext=root_ciphertext,
        doc_id=root_doc_id,
        doc_hash=root_doc_hash,
        passphrase="secret",
        auth_payload=resolved_auth_payload,
        auth_status=auth_status,
        allow_unsigned=allow_unsigned,
        output_path=None,
        input_label="Backup root directory",
        input_detail="/tmp/root",
        main_frames=(),
        auth_frames=(),
        shard_frames=(),
        shard_fallback_files=(),
        shard_payloads_file=(),
        shard_scan=(),
        root_dir="/tmp/root",
        extension_index=extension_index,
        extension_doc_hash=extension_doc_hash,
    )


def _validated_discovery(
    *directories: DiscoveredExtensionDirectory,
    first_invalid_dir_name: str | None = None,
    first_invalid_message: str | None = None,
) -> ValidatedExtensionDiscovery:
    return ValidatedExtensionDiscovery(
        directories=directories,
        first_invalid_dir_name=first_invalid_dir_name,
        first_invalid_message=first_invalid_message,
    )


class TestRecoverChain(unittest.TestCase):
    def test_detect_recovery_root_dir_finds_root_backup_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "qr_document.pdf").write_bytes(b"x")
            self.assertEqual(detect_recovery_root_dir([str(root)]), root)

    def test_detect_recovery_root_dir_rejects_symlinked_backup_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            root = Path(tmpdir) / "root"
            target.mkdir()
            (target / "qr_document.pdf").write_bytes(b"x")
            try:
                root.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            self.assertIsNone(detect_recovery_root_dir([str(root)]))

    def test_detect_recovery_root_dir_rejects_symlinked_root_main_carrier(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            external = Path(tmpdir) / "external-qr.pdf"
            root.mkdir()
            external.write_bytes(b"x")
            try:
                (root / "qr_document.pdf").symlink_to(external)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            self.assertIsNone(detect_recovery_root_dir([str(root)]))

    def test_scan_extension_carriers_prefers_valid_sibling_when_one_carrier_is_unreadable(
        self,
    ) -> None:
        auth_frame = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=b"\x11" * 16,
            index=0,
            total=1,
            data=b"auth",
        )

        def _scan(path: str, *, quiet: bool = False):
            _ = quiet
            if path.endswith("qr.pdf"):
                return b"ciphertext", (auth_frame,)
            raise ValueError(
                "recovery.pdf MAIN carrier is not independently recoverable: "
                "missing MAIN fallback section"
            )

        with mock.patch(
            "ethernity.cli.features.recover.chain._scan_single_extension_carrier",
            side_effect=_scan,
        ):
            ciphertext, auth_frames = scan_extension_carriers(
                [
                    "/tmp/root/extensions/01/qr.pdf",
                    "/tmp/root/extensions/01/recovery.pdf",
                ],
                quiet=True,
            )

        self.assertEqual(ciphertext, b"ciphertext")
        self.assertEqual(auth_frames, [auth_frame])

    def test_scan_single_extension_carrier_uses_recovery_pdf_fallback_when_qr_is_absent(
        self,
    ) -> None:
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x11" * 16,
            index=0,
            total=1,
            data=b"ciphertext",
        )

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                side_effect=ValueError("no QR codes found in scan inputs"),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.extract_pdf_fallback_lines_from_pdf",
                return_value=["Main Frame", "ybndr fghj kmnp qrst"],
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._frames_from_fallback_lines",
                return_value=[main_frame],
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.PdfReader",
                return_value=object(),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.reassemble_payload",
                return_value=b"ciphertext",
            ),
        ):
            ciphertext, auth_frames = recover_chain_module._scan_single_extension_carrier(
                "/tmp/root/extensions/01/recovery_document.pdf",
                quiet=True,
            )

        self.assertEqual(ciphertext, b"ciphertext")
        self.assertEqual(auth_frames, ())

    def test_scan_extension_carriers_rejects_auth_mismatch_across_matching_main_carriers(
        self,
    ) -> None:
        auth_frame_a = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=b"\x11" * 16,
            index=0,
            total=1,
            data=b"auth-a",
        )
        auth_frame_b = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=b"\x11" * 16,
            index=0,
            total=1,
            data=b"auth-b",
        )

        def _scan(path: str, *, quiet: bool = False):
            _ = quiet
            if path.endswith("qr.pdf"):
                return b"ciphertext", (auth_frame_a,)
            return b"ciphertext", (auth_frame_b,)

        with mock.patch(
            "ethernity.cli.features.recover.chain._scan_single_extension_carrier",
            side_effect=_scan,
        ):
            with self.assertRaisesRegex(ValueError, "AUTH payloads do not match"):
                scan_extension_carriers(
                    [
                        "/tmp/root/extensions/01/qr.pdf",
                        "/tmp/root/extensions/01/recovery.pdf",
                    ],
                    quiet=True,
                )

    def test_recover_chain_entries_replays_selected_extension_index(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        extension_auth = _extension_auth_frame(extension_doc_id, extension_doc_hash)

        plan = _recovery_plan(
            root_ciphertext,
            root_doc_id,
            root_doc_hash,
            extension_index=1,
        )

        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex=extension_doc_id.hex(),
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                ),
                shard_carriers=(),
            ),
        )
        frames_by_path = {
            "/tmp/root/extensions/01/qr.pdf": [
                Frame(
                    version=1,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=extension_doc_id,
                    index=0,
                    total=1,
                    data=extension_ciphertext,
                ),
                extension_auth,
            ]
        }

        def _scan(paths: list[str], *, quiet: bool = False):
            _ = quiet
            return list(frames_by_path[paths[0]])

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(*discovered),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                side_effect=_scan,
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            result = recover_chain_entries(plan, quiet=True, debug=False)

        self.assertEqual(result.selected_extension_index, 1)
        self.assertEqual(result.selected_extension_doc_hash, extension_doc_hash.hex())
        self.assertEqual(len(result.extracted), 1)
        self.assertEqual(result.extracted[0][0].path, "a.txt")
        self.assertEqual(result.extracted[0][1], b"root!")

    def test_discover_recovery_extensions_returns_root_only_before_scanning_extensions(
        self,
    ) -> None:
        with mock.patch(
            "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
            side_effect=AssertionError(
                "extension discovery should not run for root-only selection"
            ),
        ):
            result = discover_recovery_extensions(
                Path("/tmp/root"),
                quiet=True,
                requested_index=0,
            )

        self.assertEqual(result, ())

    def test_discover_recovery_extensions_accepts_directory_when_qr_carrier_is_valid(
        self,
    ) -> None:
        ciphertext = b"valid-ciphertext"
        doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)
        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex=doc_id.hex(),
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{doc_id.hex()}.pdf",
                        doc_id_hex=doc_id.hex(),
                    ),
                    DiscoveredExtensionMainCarrier(
                        doc_type="recovery_document",
                        path=Path("/tmp/root/extensions/01/recovery.pdf"),
                        filename=f"recovery_document-01-{doc_id.hex()}.pdf",
                        doc_id_hex=doc_id.hex(),
                    ),
                ),
                shard_carriers=(),
            ),
        )
        auth_frame = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"auth",
        )

        def _scan(path: str, *, quiet: bool = False):
            _ = quiet
            if path.endswith("qr.pdf"):
                return ciphertext, (auth_frame,)
            raise ValueError(
                "recovery.pdf MAIN carrier is not independently recoverable: "
                "missing MAIN fallback section"
            )

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(*discovered),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._scan_single_extension_carrier",
                side_effect=_scan,
            ),
        ):
            result = discover_recovery_extensions(Path("/tmp/root"), quiet=True)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].index, 1)
        self.assertEqual(result[0].doc_hash, doc_hash)

    def test_discover_recovery_extensions_uses_latest_validated_prefix_by_default(
        self,
    ) -> None:
        root_ciphertext, _root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        extension_auth = _extension_auth_frame(extension_doc_id, extension_doc_hash)
        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex=extension_doc_id.hex(),
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                ),
                shard_carriers=(),
            ),
        )

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(
                    *discovered,
                    first_invalid_dir_name="02",
                    first_invalid_message=(
                        "extension directory 02 is missing required payload MAIN carriers: "
                        "recovery_document"
                    ),
                ),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                return_value=[
                    Frame(
                        version=1,
                        frame_type=FrameType.MAIN_DOCUMENT,
                        doc_id=extension_doc_id,
                        index=0,
                        total=1,
                        data=extension_ciphertext,
                    ),
                    extension_auth,
                ],
            ),
        ):
            result = discover_recovery_extensions(Path("/tmp/root"), quiet=True)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].index, 1)
        self.assertEqual(result[0].doc_hash, extension_doc_hash)

    def test_discover_recovery_extensions_requested_invalid_suffix_raises_layout_error(
        self,
    ) -> None:
        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex="aa" * 8,
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{'aa' * 8}.pdf",
                        doc_id_hex="aa" * 8,
                    ),
                ),
                shard_carriers=(),
            ),
        )

        with mock.patch(
            "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
            return_value=_validated_discovery(
                *discovered,
                first_invalid_dir_name="02",
                first_invalid_message=(
                    "extension directory 02 is missing required payload MAIN carriers: "
                    "recovery_document"
                ),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "missing required payload MAIN carriers"):
                discover_recovery_extensions(Path("/tmp/root"), quiet=True, requested_index=2)

    def test_discover_recovery_extensions_allows_requested_earlier_index_before_invalid_suffix(
        self,
    ) -> None:
        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex="aa" * 8,
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{'aa' * 8}.pdf",
                        doc_id_hex="aa" * 8,
                    ),
                    DiscoveredExtensionMainCarrier(
                        doc_type="recovery_document",
                        path=Path("/tmp/root/extensions/01/recovery.pdf"),
                        filename=f"recovery_document-01-{'aa' * 8}.pdf",
                        doc_id_hex="aa" * 8,
                    ),
                ),
                shard_carriers=(),
            ),
        )

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(
                    *discovered,
                    first_invalid_dir_name="02",
                    first_invalid_message=(
                        "extension directory 02 is missing required payload MAIN carriers: "
                        "recovery_document"
                    ),
                ),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._discover_recovery_extension",
                return_value=DiscoveredRecoveryExtension(
                    index=1,
                    dir_name="01",
                    doc_id_hex="aa" * 8,
                    doc_hash=b"\xbb" * 32,
                    ciphertext=b"ciphertext",
                    auth_frames=(),
                ),
            ),
        ):
            result = discover_recovery_extensions(
                Path("/tmp/root"),
                quiet=True,
                requested_index=1,
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].index, 1)

    def test_recover_chain_entries_resolves_virtual_root_chunks(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash, reuse_root_chunk=True)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        extension_auth = _extension_auth_frame(extension_doc_id, extension_doc_hash)

        plan = _recovery_plan(
            root_ciphertext,
            root_doc_id,
            root_doc_hash,
            extension_index=1,
        )

        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex=extension_doc_id.hex(),
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                ),
                shard_carriers=(),
            ),
        )
        frames_by_path = {
            "/tmp/root/extensions/01/qr.pdf": [
                Frame(
                    version=1,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=extension_doc_id,
                    index=0,
                    total=1,
                    data=extension_ciphertext,
                ),
                extension_auth,
            ]
        }

        def _scan(paths: list[str], *, quiet: bool = False):
            _ = quiet
            return list(frames_by_path[paths[0]])

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(*discovered),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                side_effect=_scan,
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            result = recover_chain_entries(plan, quiet=True, debug=False)

        self.assertEqual(result.selected_extension_index, 1)
        self.assertEqual(result.selected_extension_doc_hash, extension_doc_hash.hex())
        self.assertEqual(result.extracted[0][1], b"root!")

    def test_recover_chain_entries_uses_selected_extension_input_metadata(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(
            root_doc_hash,
            input_origin="directory",
            input_roots=("docs",),
        )
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        extension_auth = _extension_auth_frame(extension_doc_id, extension_doc_hash)

        plan = _recovery_plan(
            root_ciphertext,
            root_doc_id,
            root_doc_hash,
            extension_index=1,
        )

        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex=extension_doc_id.hex(),
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                ),
                shard_carriers=(),
            ),
        )
        frames_by_path = {
            "/tmp/root/extensions/01/qr.pdf": [
                Frame(
                    version=1,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=extension_doc_id,
                    index=0,
                    total=1,
                    data=extension_ciphertext,
                ),
                extension_auth,
            ]
        }

        def _scan(paths: list[str], *, quiet: bool = False):
            _ = quiet
            return list(frames_by_path[paths[0]])

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(*discovered),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                side_effect=_scan,
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            result = recover_chain_entries(plan, quiet=True, debug=False)

        self.assertEqual(result.manifest.input_origin, "directory")
        self.assertEqual(result.manifest.input_roots, ("docs",))

    def test_recover_chain_entries_can_select_earlier_index_when_later_extension_is_corrupt(
        self,
    ) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        extension_auth = _extension_auth_frame(extension_doc_id, extension_doc_hash)

        plan = _recovery_plan(
            root_ciphertext,
            root_doc_id,
            root_doc_hash,
            extension_index=1,
        )
        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex=extension_doc_id.hex(),
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                ),
                shard_carriers=(),
            ),
            DiscoveredExtensionDirectory(
                index=2,
                dir_name="02",
                path=Path("/tmp/root/extensions/02"),
                doc_id_hex="bb" * 16,
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/02/qr.pdf"),
                        filename=f"qr_document-02-{'bb' * 16}.pdf",
                        doc_id_hex="bb" * 16,
                    ),
                ),
                shard_carriers=(),
            ),
        )
        frames_by_path = {
            "/tmp/root/extensions/01/qr.pdf": [
                Frame(
                    version=1,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=extension_doc_id,
                    index=0,
                    total=1,
                    data=extension_ciphertext,
                ),
                extension_auth,
            ]
        }

        def _scan(paths: list[str], *, quiet: bool = False):
            _ = quiet
            path = paths[0]
            if path not in frames_by_path:
                raise ValueError("extension 02 MAIN carriers could not be reconstructed")
            return list(frames_by_path[path])

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(*discovered),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                side_effect=_scan,
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            result = recover_chain_entries(plan, quiet=True, debug=False)

        self.assertEqual(result.selected_extension_index, 1)
        self.assertEqual(result.selected_extension_doc_hash, extension_doc_hash.hex())
        self.assertEqual(result.extracted[0][1], b"root!")

    def test_recover_chain_entries_can_select_earlier_doc_hash_when_later_extension_is_corrupt(
        self,
    ) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        extension_auth = _extension_auth_frame(extension_doc_id, extension_doc_hash)

        plan = _recovery_plan(
            root_ciphertext,
            root_doc_id,
            root_doc_hash,
            extension_index=None,
            extension_doc_hash=extension_doc_hash.hex(),
        )
        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex=extension_doc_id.hex(),
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                ),
                shard_carriers=(),
            ),
            DiscoveredExtensionDirectory(
                index=2,
                dir_name="02",
                path=Path("/tmp/root/extensions/02"),
                doc_id_hex="bb" * 16,
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/02/qr.pdf"),
                        filename=f"qr_document-02-{'bb' * 16}.pdf",
                        doc_id_hex="bb" * 16,
                    ),
                ),
                shard_carriers=(),
            ),
        )
        frames_by_path = {
            "/tmp/root/extensions/01/qr.pdf": [
                Frame(
                    version=1,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=extension_doc_id,
                    index=0,
                    total=1,
                    data=extension_ciphertext,
                ),
                extension_auth,
            ]
        }

        def _scan(paths: list[str], *, quiet: bool = False):
            _ = quiet
            path = paths[0]
            if path not in frames_by_path:
                raise ValueError("extension 02 MAIN carriers could not be reconstructed")
            return list(frames_by_path[path])

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(*discovered),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                side_effect=_scan,
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            result = recover_chain_entries(plan, quiet=True, debug=False)

        self.assertEqual(result.selected_extension_index, 1)
        self.assertEqual(result.selected_extension_doc_hash, extension_doc_hash.hex())

    def test_recover_chain_entries_rejects_extension_auth_from_wrong_authority(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        extension_auth = _extension_auth_frame(
            extension_doc_id,
            extension_doc_hash,
            signing_seed=b"\x77" * 32,
        )
        plan = _recovery_plan(
            root_ciphertext,
            root_doc_id,
            root_doc_hash,
            extension_index=1,
        )

        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex=extension_doc_id.hex(),
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                ),
                shard_carriers=(),
            ),
        )
        frames_by_path = {
            "/tmp/root/extensions/01/qr.pdf": [
                Frame(
                    version=1,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=extension_doc_id,
                    index=0,
                    total=1,
                    data=extension_ciphertext,
                ),
                extension_auth,
            ]
        }

        def _scan(paths: list[str], *, quiet: bool = False):
            _ = quiet
            return list(frames_by_path[paths[0]])

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(*discovered),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                side_effect=_scan,
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "signing key does not match root authority"):
                recover_chain_entries(plan, quiet=True, debug=False)

    def test_recover_chain_entries_rejects_wrong_authority_even_when_unsigned_allowed(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        extension_auth = _extension_auth_frame(
            extension_doc_id,
            extension_doc_hash,
            signing_seed=b"\x77" * 32,
        )
        plan = _recovery_plan(
            root_ciphertext,
            root_doc_id,
            root_doc_hash,
            extension_index=1,
            auth_payload=None,
            auth_status="missing",
            allow_unsigned=True,
        )

        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex=extension_doc_id.hex(),
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                ),
                shard_carriers=(),
            ),
        )
        frames_by_path = {
            "/tmp/root/extensions/01/qr.pdf": [
                Frame(
                    version=1,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=extension_doc_id,
                    index=0,
                    total=1,
                    data=extension_ciphertext,
                ),
                extension_auth,
            ]
        }

        def _scan(paths: list[str], *, quiet: bool = False):
            _ = quiet
            return list(frames_by_path[paths[0]])

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(*discovered),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                side_effect=_scan,
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "signing key does not match root authority"):
                recover_chain_entries(plan, quiet=True, debug=False)

    def test_recover_chain_entries_defaults_to_latest_validated_prefix_when_later_extension_fails(
        self,
    ) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        first_ciphertext = _extension_ciphertext(
            root_doc_hash,
            index=1,
            parent_doc_hash=root_doc_hash,
            data=b"root!",
        )
        first_doc_id, first_doc_hash = _doc_id_and_hash_from_ciphertext(first_ciphertext)
        first_plaintext = first_ciphertext
        first_version, first_decoded = decode_any_envelope(first_plaintext)
        assert first_version == 2
        assert isinstance(first_decoded, ExtensionEnvelope)
        first_link = DecodedExtensionLink(
            link=ExtensionChainLink(doc_hash=first_doc_hash, document=first_decoded),
            auth_payload=AuthPayload(
                version=1,
                doc_hash=first_doc_hash,
                sign_pub=derive_public_key(b"\x33" * 32),
                signature=b"\x11" * 64,
            ),
            auth_status="verified",
            root_authority_verified=True,
        )
        second_doc_id = b"\x44" * 16
        second_doc_hash = b"\x55" * 32
        inventory = (
            DiscoveredRecoveryExtension(
                index=1,
                dir_name="01",
                doc_id_hex=first_doc_id.hex(),
                doc_hash=first_doc_hash,
                ciphertext=first_ciphertext,
                auth_frames=(),
            ),
            DiscoveredRecoveryExtension(
                index=2,
                dir_name="02",
                doc_id_hex=second_doc_id.hex(),
                doc_hash=second_doc_hash,
                ciphertext=b"bad",
                auth_frames=(),
            ),
        )
        plan = _recovery_plan(
            root_ciphertext,
            root_doc_id,
            root_doc_hash,
            extension_index=None,
        )

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_recovery_extensions",
                return_value=inventory,
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.decode_authenticated_extension_link",
                side_effect=[
                    first_link,
                    ValueError("extension 02 AUTH signing key does not match root authority"),
                ],
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            result = recover_chain_entries(plan, quiet=True, debug=False)

        self.assertEqual(result.selected_extension_index, 1)
        self.assertEqual(result.selected_extension_doc_hash, first_doc_hash.hex())
        self.assertEqual(len(result.extracted), 1)
        self.assertEqual(result.extracted[0][1], b"root!")

    def test_decode_authenticated_extension_link_rejects_missing_auth_even_when_unsigned_allowed(
        self,
    ) -> None:
        root_ciphertext, _root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        discovered = DiscoveredRecoveryExtension(
            index=1,
            dir_name="01",
            doc_id_hex=extension_doc_id.hex(),
            doc_hash=extension_doc_hash,
            ciphertext=extension_ciphertext,
            auth_frames=(),
        )

        with mock.patch(
            "ethernity.cli.features.recover.chain.decrypt_bytes",
            side_effect=lambda data, *, passphrase, debug=False: data,
        ):
            with self.assertRaisesRegex(ValueError, "missing auth payload"):
                decode_authenticated_extension_link(
                    discovered,
                    passphrase="secret",
                    expected_sign_pub=derive_public_key(b"\x33" * 32),
                    allow_unsigned=True,
                    quiet=True,
                    debug=False,
                )

    def test_recover_chain_entries_rejects_root_auth_mismatch_with_embedded_seed(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        mismatched_sign_pub = derive_public_key(b"\x77" * 32)
        extension_auth = _extension_auth_frame(
            extension_doc_id,
            extension_doc_hash,
            signing_seed=b"\x77" * 32,
        )
        plan = _recovery_plan(
            root_ciphertext,
            root_doc_id,
            root_doc_hash,
            extension_index=1,
            auth_payload=AuthPayload(
                version=1,
                doc_hash=root_doc_hash,
                sign_pub=mismatched_sign_pub,
                signature=b"\x99" * 64,
            ),
        )

        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex=extension_doc_id.hex(),
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                ),
                shard_carriers=(),
            ),
        )
        frames_by_path = {
            "/tmp/root/extensions/01/qr.pdf": [
                Frame(
                    version=1,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=extension_doc_id,
                    index=0,
                    total=1,
                    data=extension_ciphertext,
                ),
                extension_auth,
            ]
        }

        def _scan(paths: list[str], *, quiet: bool = False):
            _ = quiet
            return list(frames_by_path[paths[0]])

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(*discovered),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                side_effect=_scan,
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "embedded signing seed does not match the verified root AUTH authority",
            ):
                recover_chain_entries(plan, quiet=True, debug=False)

    def test_recover_chain_entries_rejects_disagreeing_main_carriers(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, _extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        plan = _recovery_plan(
            root_ciphertext,
            root_doc_id,
            root_doc_hash,
            extension_index=1,
        )

        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex=extension_doc_id.hex(),
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                    DiscoveredExtensionMainCarrier(
                        doc_type="recovery_document",
                        path=Path("/tmp/root/extensions/01/recovery.pdf"),
                        filename=f"recovery_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                ),
                shard_carriers=(),
            ),
        )
        frames_by_path = {
            "/tmp/root/extensions/01/qr.pdf": [
                Frame(
                    version=1,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=extension_doc_id,
                    index=0,
                    total=1,
                    data=extension_ciphertext,
                ),
            ],
            "/tmp/root/extensions/01/recovery.pdf": [
                Frame(
                    version=1,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=extension_doc_id,
                    index=0,
                    total=1,
                    data=b"tampered-extension-ciphertext",
                ),
            ],
        }

        def _scan(paths: list[str], *, quiet: bool = False):
            _ = quiet
            frames: list[Frame] = []
            for path in paths:
                frames.extend(frames_by_path[path])
            return frames

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(*discovered),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                side_effect=_scan,
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "MAIN carrier does not match"):
                recover_chain_entries(plan, quiet=True, debug=False)

    def test_recover_chain_entries_ignores_recovery_kit_index_as_payload_source(self) -> None:
        root_ciphertext, root_doc_id, root_doc_hash = _root_ciphertext()
        extension_ciphertext = _extension_ciphertext(root_doc_hash)
        extension_doc_id, extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            extension_ciphertext
        )
        extension_auth = _extension_auth_frame(extension_doc_id, extension_doc_hash)
        plan = _recovery_plan(
            root_ciphertext,
            root_doc_id,
            root_doc_hash,
            extension_index=1,
        )

        discovered = (
            DiscoveredExtensionDirectory(
                index=1,
                dir_name="01",
                path=Path("/tmp/root/extensions/01"),
                doc_id_hex=extension_doc_id.hex(),
                main_carriers=(
                    DiscoveredExtensionMainCarrier(
                        doc_type="qr_document",
                        path=Path("/tmp/root/extensions/01/qr.pdf"),
                        filename=f"qr_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                    DiscoveredExtensionMainCarrier(
                        doc_type="recovery_document",
                        path=Path("/tmp/root/extensions/01/recovery.pdf"),
                        filename=f"recovery_document-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                    DiscoveredExtensionMainCarrier(
                        doc_type="recovery_kit_index",
                        path=Path("/tmp/root/extensions/01/index.pdf"),
                        filename=f"recovery_kit_index-01-{extension_doc_id.hex()}.pdf",
                        doc_id_hex=extension_doc_id.hex(),
                    ),
                ),
                shard_carriers=(),
                recovery_kit_index_carrier=None,
            ),
        )
        frames_by_path = {
            "/tmp/root/extensions/01/qr.pdf": [
                Frame(
                    version=1,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=extension_doc_id,
                    index=0,
                    total=1,
                    data=extension_ciphertext,
                ),
                extension_auth,
            ],
            "/tmp/root/extensions/01/recovery.pdf": [
                Frame(
                    version=1,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=extension_doc_id,
                    index=0,
                    total=1,
                    data=extension_ciphertext,
                ),
                extension_auth,
            ],
            "/tmp/root/extensions/01/index.pdf": [],
        }

        def _scan(paths: list[str], *, quiet: bool = False):
            _ = quiet
            frames: list[Frame] = []
            for path in paths:
                frames.extend(frames_by_path[path])
            return frames

        with (
            mock.patch(
                "ethernity.cli.features.recover.chain.discover_validated_extension_directories",
                return_value=_validated_discovery(*discovered),
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain._recovery_frames_from_scan",
                side_effect=_scan,
            ),
            mock.patch(
                "ethernity.cli.features.recover.chain.decrypt_bytes",
                side_effect=lambda data, *, passphrase, debug=False: data,
            ),
        ):
            result = recover_chain_entries(plan, quiet=True, debug=False)

        self.assertEqual(result.selected_extension_index, 1)
        self.assertEqual(result.selected_extension_doc_hash, extension_doc_hash.hex())
