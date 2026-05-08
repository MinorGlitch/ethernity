from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import tooling.document_inspector as inspector

from ethernity.cli.shared.crypto import _doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.types import InputFile
from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.crypto.signing import derive_public_key, encode_auth_payload, sign_auth
from ethernity.encoding.chunking import chunk_payload
from ethernity.encoding.framing import VERSION, Frame, FrameType, encode_frame
from ethernity.encoding.qr_payloads import QR_PAYLOAD_CODEC_BASE64, encode_qr_payload
from ethernity.extensions import build_extension_document
from ethernity.formats.envelope_codec import build_manifest_and_payload, encode_envelope
from ethernity.formats.envelope_types import PayloadPart
from ethernity.formats.extension_envelope import ExtensionChunkingProfile
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC

_REPO_ROOT = Path(__file__).resolve().parents[2]
_V1_0_FIXTURES_ROOT = _REPO_ROOT / "tests" / "fixtures" / "v1_0" / "golden" / "base64"
_V1_1_FIXTURES_ROOT = _REPO_ROOT / "tests" / "fixtures" / "v1_1" / "golden" / "base64"
_V1_0_PASSPHRASE = "stable-v1-baseline-passphrase"
_V1_1_PASSPHRASE = "stable-v1_1-golden-passphrase"
_EXTENSION_TEST_PASSPHRASE = "document-inspector-extension-passphrase"


def _backup_shards(scenario_root: Path) -> list[Path]:
    return sorted((scenario_root / "backup").glob("shard-*.pdf"))


def _profile() -> ExtensionChunkingProfile:
    return ExtensionChunkingProfile(
        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
        target_size=64 * 1024,
        min_size=16 * 1024,
        max_size=256 * 1024,
    )


def _payload_text_from_frames(frames: list[Frame]) -> str:
    lines: list[str] = []
    for frame in frames:
        payload = encode_qr_payload(encode_frame(frame), codec=QR_PAYLOAD_CODEC_BASE64)
        lines.append(payload.decode("ascii") if isinstance(payload, bytes) else payload)
    return "\n".join(lines) + "\n"


def _encrypted_main_frames(plaintext: bytes, *, passphrase: str) -> tuple[list[Frame], bytes]:
    ciphertext, _ = encrypt_bytes_with_passphrase(plaintext, passphrase=passphrase)
    doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)
    frames = chunk_payload(
        ciphertext,
        doc_id=doc_id,
        frame_type=FrameType.MAIN_DOCUMENT,
        chunk_size=400,
    )
    return frames, doc_hash


def _extension_frames_with_auth(
    plaintext: bytes,
    *,
    passphrase: str,
    signing_seed: bytes,
) -> list[Frame]:
    frames, doc_hash = _encrypted_main_frames(plaintext, passphrase=passphrase)
    sign_pub = derive_public_key(signing_seed)
    auth_frame = Frame(
        version=VERSION,
        frame_type=FrameType.AUTH,
        doc_id=frames[0].doc_id,
        index=0,
        total=1,
        data=encode_auth_payload(
            doc_hash,
            sign_pub=sign_pub,
            signature=sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=signing_seed),
        ),
    )
    return [*frames, auth_frame]


class TestDocumentInspectorTool(unittest.TestCase):
    def _decoded_trust_report(self, result: inspector.InspectionResult) -> dict[str, object]:
        decoded_report = json.loads(result.report_json)
        report_trust = decoded_report.get("trust_diagnostic")
        if result.trust_diagnostic is None:
            self.assertIsNone(report_trust)
            return decoded_report

        self.assertIsNotNone(report_trust)
        self.assertEqual(report_trust["status"], result.trust_diagnostic.status)
        self.assertEqual(report_trust["code"], result.trust_diagnostic.code)
        self.assertEqual(report_trust["message"], result.trust_diagnostic.message)
        self.assertEqual(report_trust["details"], result.trust_diagnostic.details)
        self.assertIn(
            f"Trust message: {result.trust_diagnostic.message}",
            result.projection_diagnostics_text,
        )
        if result.trust_diagnostic.code is not None:
            self.assertIn(
                f"Trust code: {result.trust_diagnostic.code}",
                result.projection_diagnostics_text,
            )
        return decoded_report

    def test_inspect_main_payloads_exposes_round_trip_views(self) -> None:
        payload_text = (_V1_0_FIXTURES_ROOT / "file_no_shard" / "main_payloads.txt").read_text(
            encoding="utf-8"
        )

        result = inspector.inspect_pasted_text(
            payload_text,
            selected_mode=inspector.MODE_AUTO,
            passphrase=_V1_0_PASSPHRASE,
            source_label="fixture main payloads",
        )

        self.assertEqual(result.input_mode, inspector.MODE_PAYLOADS)
        self.assertEqual(result.parsed_frame_count, 3)
        self.assertIn("MAIN FRAME", result.combined_fallback_text)
        self.assertIn("AUTH FRAME", result.combined_fallback_text)
        self.assertIsNotNone(result.document_json_text)
        self.assertEqual(len(result.files), 1)
        self.assertIn("format_version", result.document_json_text or "")
        decoded_report = self._decoded_trust_report(result)
        self.assertIn("document", decoded_report)
        self.assertEqual(result.trust_diagnostic.code, None)
        self.assertEqual(result.trust_diagnostic.message, "root backup authority verified")

    def test_inspect_shard_payloads_recovers_passphrase(self) -> None:
        payload_text = (
            _V1_1_FIXTURES_ROOT / "sharded_embedded" / "shard_payloads_threshold.txt"
        ).read_text(encoding="utf-8")

        result = inspector.inspect_pasted_text(
            payload_text,
            selected_mode=inspector.MODE_AUTO,
            passphrase=None,
            source_label="fixture shard payloads",
        )

        self.assertEqual(result.parsed_frame_count, 2)
        self.assertEqual(len(result.recovered_secrets), 1)
        secret = result.recovered_secrets[0]
        self.assertEqual(secret.label, "passphrase")
        self.assertEqual(secret.status, "recoverable")
        self.assertIn(_V1_1_PASSPHRASE, secret.detail_text)

    def test_collect_scan_files_recurses_directory(self) -> None:
        files = inspector._collect_scan_files([_V1_0_FIXTURES_ROOT / "file_no_shard" / "backup"])

        self.assertGreaterEqual(len(files), 2)
        self.assertTrue(any(path.name == "qr_document.pdf" for path in files))
        self.assertTrue(all(path.suffix.lower() == ".pdf" for path in files))

    def test_payload_text_from_scan_paths_decodes_fixture_pdf(self) -> None:
        payload_text, warnings = inspector._payload_text_from_scan_paths(
            [_V1_0_FIXTURES_ROOT / "file_no_shard" / "backup" / "qr_document.pdf"]
        )

        self.assertEqual(warnings, [])
        result = inspector.inspect_pasted_text(
            payload_text,
            selected_mode=inspector.MODE_AUTO,
            passphrase=_V1_0_PASSPHRASE,
            source_label="fixture qr document",
        )
        self.assertEqual(result.parsed_frame_count, 3)

    def test_payload_text_from_multiple_shard_pdfs_reaches_quorum(self) -> None:
        scenario_root = _V1_1_FIXTURES_ROOT / "sharded_embedded"
        shard_paths = _backup_shards(scenario_root)
        payload_text, warnings = inspector._payload_text_from_scan_paths(shard_paths[:2])

        self.assertEqual(warnings, [])
        result = inspector.inspect_pasted_text(
            payload_text,
            selected_mode=inspector.MODE_AUTO,
            passphrase=None,
            source_label="fixture shard pdfs",
        )

        self.assertEqual(result.parsed_frame_count, 2)
        self.assertEqual(len(result.recovered_secrets), 1)
        self.assertEqual(result.recovered_secrets[0].status, "recoverable")

    def test_combined_backup_and_shards_auto_decrypts_from_recovered_passphrase(self) -> None:
        scenario_root = _V1_1_FIXTURES_ROOT / "sharded_embedded"
        shard_paths = _backup_shards(scenario_root)
        payload_text, warnings = inspector._payload_text_from_scan_paths(
            [scenario_root / "backup" / "qr_document.pdf", *shard_paths[:2]]
        )

        self.assertEqual(warnings, [])
        result = inspector.inspect_pasted_text(
            payload_text,
            selected_mode=inspector.MODE_AUTO,
            passphrase=None,
            source_label="fixture backup plus shards",
        )

        self.assertIsNotNone(result.document_json_text)
        self.assertGreaterEqual(len(result.files), 1)
        self.assertIn("Decrypted via: recovered passphrase shards", result.summary_text)

    def test_inspect_extension_payloads_require_root_backup_authority_context(self) -> None:
        extension = build_extension_document(
            index=1,
            parent_doc_hash=b"\x10" * 32,
            root_doc_hash=b"\x20" * 32,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="docs/notes.txt",
                    data=b"extension-only file\n",
                    mtime=1712666400,
                ),
            ),
            input_origin="directory",
            input_roots=("demo",),
            chunker=lambda data, _profile: (data,),
        )
        extension_signing_seed = b"\x41" * 32
        extension_frames = _extension_frames_with_auth(
            extension.document.encode(),
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            signing_seed=extension_signing_seed,
        )

        result = inspector.inspect_pasted_text(
            _payload_text_from_frames(extension_frames),
            selected_mode=inspector.MODE_AUTO,
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            source_label="extension payloads",
        )

        self.assertIsNone(result.document_json_text)
        self.assertEqual(result.files, ())
        self.assertIn(
            (
                "Document decode failed: latest recovery head could not be trusted: "
                "extension preview requires the root backup to validate root authority"
            ),
            result.diagnostics_text,
        )
        self.assertIn("Trust status: refused", result.projection_diagnostics_text)
        self.assertIn("Failure stage: authority_context", result.projection_diagnostics_text)
        self.assertIn("Validated head: none", result.projection_diagnostics_text)
        self._decoded_trust_report(result)
        self.assertIsNotNone(result.trust_diagnostic)
        self.assertEqual(result.trust_diagnostic.code, "RECOVERY_HEAD_UNTRUSTED")
        self.assertEqual(result.trust_diagnostic.details["latest_head_index"], 1)

    def test_inspect_root_payloads_rejects_invalid_auth(self) -> None:
        manifest, payload = build_manifest_and_payload(
            [PayloadPart(path="alpha.txt", data=b"root-alpha\n", mtime=1712666401)],
            sealed=False,
            signing_seed=b"\x41" * 32,
            input_origin="directory",
            input_roots=("demo",),
        )
        root_plaintext = encode_envelope(payload, manifest)
        root_frames, root_doc_hash = _encrypted_main_frames(
            root_plaintext,
            passphrase=_EXTENSION_TEST_PASSPHRASE,
        )
        mismatched_sign_pub = derive_public_key(b"\x42" * 32)
        root_auth = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=root_frames[0].doc_id,
            index=0,
            total=1,
            data=encode_auth_payload(
                root_doc_hash,
                sign_pub=mismatched_sign_pub,
                signature=sign_auth(
                    root_doc_hash,
                    sign_pub=mismatched_sign_pub,
                    sign_priv=b"\x42" * 32,
                ),
            ),
        )

        result = inspector.inspect_pasted_text(
            _payload_text_from_frames([*root_frames, root_auth]),
            selected_mode=inspector.MODE_AUTO,
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            source_label="root payloads",
        )

        self.assertIsNone(result.document_json_text)
        self.assertEqual(result.files, ())
        self.assertIn(
            (
                "Document decode failed: embedded signing seed does not match "
                "the verified root AUTH authority"
            ),
            result.diagnostics_text,
        )
        self.assertIn("Trust code: ROOT_AUTHORITY_MISMATCH", result.projection_diagnostics_text)
        self.assertIn("Failure stage: root_authority", result.projection_diagnostics_text)
        self._decoded_trust_report(result)
        self.assertIsNotNone(result.trust_diagnostic)
        self.assertEqual(result.trust_diagnostic.code, "ROOT_AUTHORITY_MISMATCH")
        self.assertEqual(result.trust_diagnostic.details["validated_head_index"], None)

    def test_chain_projection_requires_verified_root_auth(self) -> None:
        root_manifest, root_payload = build_manifest_and_payload(
            (PayloadPart(path="docs/root.txt", data=b"root\n", mtime=1712666400),),
            sealed=False,
            signing_seed=b"\x41" * 32,
            input_origin="directory",
            input_roots=("demo",),
        )
        root_plaintext = encode_envelope(root_payload, root_manifest)
        root_frames, root_doc_hash = _encrypted_main_frames(
            root_plaintext,
            passphrase=_EXTENSION_TEST_PASSPHRASE,
        )
        extension = build_extension_document(
            index=1,
            parent_doc_hash=root_doc_hash,
            root_doc_hash=root_doc_hash,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="docs/root.txt",
                    data=b"root!\n",
                    mtime=1712666401,
                ),
            ),
            input_origin="directory",
            input_roots=("demo",),
            chunker=lambda data, _profile: (data,),
        )
        extension_frames = _extension_frames_with_auth(
            extension.document.encode(),
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            signing_seed=b"\x41" * 32,
        )

        result = inspector.inspect_pasted_text(
            _payload_text_from_frames([*root_frames, *extension_frames]),
            selected_mode=inspector.MODE_AUTO,
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            source_label="root plus extension payloads",
        )

        self.assertIsNone(result.document_json_text)
        self.assertIn(
            (
                "Document decode failed: latest recovery head could not be trusted: "
                "root AUTH validation failed (skipped)"
            ),
            result.diagnostics_text,
        )
        self.assertIn("Trust code: RECOVERY_HEAD_UNTRUSTED", result.projection_diagnostics_text)
        self.assertIn("Failure stage: auth", result.projection_diagnostics_text)
        self._decoded_trust_report(result)
        self.assertIsNotNone(result.trust_diagnostic)
        self.assertEqual(result.trust_diagnostic.code, "RECOVERY_HEAD_UNTRUSTED")
        self.assertEqual(result.trust_diagnostic.details["latest_head_index"], 1)
        self.assertEqual(result.trust_diagnostic.details["validated_head_index"], None)

    def test_chain_projection_rejects_root_authority_mismatch(self) -> None:
        root_manifest, root_payload = build_manifest_and_payload(
            (PayloadPart(path="docs/root.txt", data=b"root\n", mtime=1712666400),),
            sealed=False,
            signing_seed=b"\x41" * 32,
            input_origin="directory",
            input_roots=("demo",),
        )
        root_plaintext = encode_envelope(root_payload, root_manifest)
        root_frames, root_doc_hash = _encrypted_main_frames(
            root_plaintext,
            passphrase=_EXTENSION_TEST_PASSPHRASE,
        )
        mismatched_root_sign_pub = derive_public_key(b"\x42" * 32)
        root_auth = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=root_frames[0].doc_id,
            index=0,
            total=1,
            data=encode_auth_payload(
                root_doc_hash,
                sign_pub=mismatched_root_sign_pub,
                signature=sign_auth(
                    root_doc_hash,
                    sign_pub=mismatched_root_sign_pub,
                    sign_priv=b"\x42" * 32,
                ),
            ),
        )
        extension = build_extension_document(
            index=1,
            parent_doc_hash=root_doc_hash,
            root_doc_hash=root_doc_hash,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="docs/root.txt",
                    data=b"root!\n",
                    mtime=1712666401,
                ),
            ),
            input_origin="directory",
            input_roots=("demo",),
            chunker=lambda data, _profile: (data,),
        )
        extension_frames = _extension_frames_with_auth(
            extension.document.encode(),
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            signing_seed=b"\x41" * 32,
        )

        result = inspector.inspect_pasted_text(
            _payload_text_from_frames([*root_frames, root_auth, *extension_frames]),
            selected_mode=inspector.MODE_AUTO,
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            source_label="root plus extension payloads",
        )

        self.assertIsNone(result.document_json_text)
        self.assertIn(
            (
                "Document decode failed: embedded signing seed does not match "
                "the verified root AUTH authority"
            ),
            result.diagnostics_text,
        )
        self.assertIn("Trust code: ROOT_AUTHORITY_MISMATCH", result.projection_diagnostics_text)
        self.assertIn("Failure stage: root_authority", result.projection_diagnostics_text)
        self._decoded_trust_report(result)
        self.assertIsNotNone(result.trust_diagnostic)
        self.assertEqual(result.trust_diagnostic.code, "ROOT_AUTHORITY_MISMATCH")
        self.assertEqual(result.trust_diagnostic.details["latest_head_index"], 1)
        self.assertEqual(result.trust_diagnostic.details["validated_head_index"], None)

    def test_inspect_extension_payloads_requiring_reused_chunks_fails_closed(self) -> None:
        root_chunk = b"root and extension-only data\n"
        extension = build_extension_document(
            index=1,
            parent_doc_hash=b"\x10" * 32,
            root_doc_hash=b"\x20" * 32,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="docs/notes.txt",
                    data=root_chunk,
                    mtime=1712666400,
                ),
            ),
            input_origin="directory",
            input_roots=("demo",),
            chunker=lambda data, _profile: (data,),
            existing_chunks={hashlib.sha256(root_chunk).digest(): root_chunk},
        )
        extension_frames = _extension_frames_with_auth(
            extension.document.encode(),
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            signing_seed=b"\x41" * 32,
        )

        result = inspector.inspect_pasted_text(
            _payload_text_from_frames(extension_frames),
            selected_mode=inspector.MODE_AUTO,
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            source_label="extension payloads with reused chunks",
        )

        self.assertIsNone(result.document_json_text)
        self.assertEqual(result.files, ())
        self.assertIn(
            (
                "Document decode failed: latest recovery head could not be trusted: "
                "extension preview requires the root backup to validate root authority"
            ),
            result.diagnostics_text,
        )
        self.assertIn("Trust status: refused", result.projection_diagnostics_text)
        self.assertIn("Failure stage: authority_context", result.projection_diagnostics_text)
        self._decoded_trust_report(result)
        self.assertIsNotNone(result.trust_diagnostic)
        self.assertEqual(result.trust_diagnostic.code, "RECOVERY_HEAD_UNTRUSTED")

    def test_inspect_root_and_extension_payloads_reconstructs_latest_state(self) -> None:
        manifest, payload = build_manifest_and_payload(
            [
                PayloadPart(path="alpha.txt", data=b"root-alpha\n", mtime=1712666401),
            ],
            sealed=False,
            signing_seed=b"\x41" * 32,
            input_origin="directory",
            input_roots=("demo",),
        )
        root_signing_seed = b"\x41" * 32
        root_frames, root_doc_hash = _encrypted_main_frames(
            encode_envelope(payload, manifest),
            passphrase=_EXTENSION_TEST_PASSPHRASE,
        )
        root_sign_pub = derive_public_key(root_signing_seed)
        root_auth = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=root_frames[0].doc_id,
            index=0,
            total=1,
            data=encode_auth_payload(
                root_doc_hash,
                sign_pub=root_sign_pub,
                signature=sign_auth(
                    root_doc_hash,
                    sign_pub=root_sign_pub,
                    sign_priv=root_signing_seed,
                ),
            ),
        )
        extension = build_extension_document(
            index=1,
            parent_doc_hash=root_doc_hash,
            root_doc_hash=root_doc_hash,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="beta.txt",
                    data=b"extension-beta\n",
                    mtime=1712666402,
                ),
            ),
            input_origin="directory",
            input_roots=("demo",),
            chunker=lambda data, _profile: (data,),
        )
        extension_frames = _extension_frames_with_auth(
            extension.document.encode(),
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            signing_seed=root_signing_seed,
        )

        result = inspector.inspect_pasted_text(
            _payload_text_from_frames([*root_frames, root_auth, *extension_frames]),
            selected_mode=inspector.MODE_AUTO,
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            source_label="root plus extension payloads",
        )

        self.assertIn("Decoded document kind: extension_chain", result.summary_text)
        self.assertEqual({record.path for record in result.files}, {"alpha.txt", "beta.txt"})
        decoded = json.loads(result.document_json_text or "{}")
        self.assertEqual(decoded["kind"], "extension_chain")
        self.assertEqual(decoded["root"]["auth_status"], "verified")
        self.assertTrue(decoded["root"]["root_authority_verified"])
        self.assertEqual(decoded["latest_state"]["file_count"], 2)
        self._decoded_trust_report(result)
        self.assertIsNotNone(result.trust_diagnostic)
        self.assertEqual(result.trust_diagnostic.code, None)
        self.assertEqual(result.trust_diagnostic.message, "latest recovery head trusted")
        self.assertEqual(result.trust_diagnostic.details["validated_head_index"], 1)
        self.assertEqual(result.trust_diagnostic.details["validated_head_auth_status"], "verified")
        self.assertEqual(
            result.trust_diagnostic.details["validated_head_root_authority_verified"], True
        )
        self.assertIn(
            "Authority model: root-derived via root backup",
            result.projection_diagnostics_text,
        )
        self.assertIn(
            "Extension AUTH: verified against root authority for 1 extension(s)",
            result.projection_diagnostics_text,
        )

    def test_chain_projection_extension_authority_mismatch_fails_closed(self) -> None:
        manifest, payload = build_manifest_and_payload(
            [
                PayloadPart(path="alpha.txt", data=b"root-alpha\n", mtime=1712666401),
            ],
            sealed=False,
            signing_seed=b"\x41" * 32,
            input_origin="directory",
            input_roots=("demo",),
        )
        root_signing_seed = b"\x41" * 32
        root_frames, root_doc_hash = _encrypted_main_frames(
            encode_envelope(payload, manifest),
            passphrase=_EXTENSION_TEST_PASSPHRASE,
        )
        root_sign_pub = derive_public_key(root_signing_seed)
        root_auth = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=root_frames[0].doc_id,
            index=0,
            total=1,
            data=encode_auth_payload(
                root_doc_hash,
                sign_pub=root_sign_pub,
                signature=sign_auth(
                    root_doc_hash,
                    sign_pub=root_sign_pub,
                    sign_priv=root_signing_seed,
                ),
            ),
        )
        extension = build_extension_document(
            index=1,
            parent_doc_hash=root_doc_hash,
            root_doc_hash=root_doc_hash,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="beta.txt",
                    data=b"extension-beta\n",
                    mtime=1712666402,
                ),
            ),
            input_origin="directory",
            input_roots=("demo",),
            chunker=lambda data, _profile: (data,),
        )
        extension_frames = _extension_frames_with_auth(
            extension.document.encode(),
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            signing_seed=b"\x42" * 32,
        )

        result = inspector.inspect_pasted_text(
            _payload_text_from_frames([*root_frames, root_auth, *extension_frames]),
            selected_mode=inspector.MODE_AUTO,
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            source_label="root plus extension payloads",
        )

        self.assertIsNone(result.document_json_text)
        self.assertIn(
            (
                "Document decode failed: latest recovery head could not be trusted: "
                "extension 1 AUTH does not match root authority"
            ),
            result.diagnostics_text,
        )
        self.assertIn("Trust code: RECOVERY_HEAD_UNTRUSTED", result.projection_diagnostics_text)
        self.assertIn("Failure stage: auth", result.projection_diagnostics_text)
        self.assertIn("Validated head: index=0", result.projection_diagnostics_text)
        self._decoded_trust_report(result)
        self.assertIsNotNone(result.trust_diagnostic)
        self.assertEqual(result.trust_diagnostic.code, "RECOVERY_HEAD_UNTRUSTED")
        self.assertEqual(result.trust_diagnostic.details["latest_head_index"], 1)
        self.assertEqual(result.trust_diagnostic.details["validated_head_index"], 0)

    def test_inspect_valid_root_and_bad_extension_refuses_partial_projection(self) -> None:
        manifest, payload = build_manifest_and_payload(
            [
                PayloadPart(path="alpha.txt", data=b"root-alpha\n", mtime=1712666401),
            ],
            sealed=False,
            signing_seed=b"\x41" * 32,
            input_origin="directory",
            input_roots=("demo",),
        )
        root_plaintext = encode_envelope(payload, manifest)
        root_frames, root_doc_hash = _encrypted_main_frames(
            root_plaintext,
            passphrase=_EXTENSION_TEST_PASSPHRASE,
        )
        root_sign_pub = derive_public_key(b"\x41" * 32)
        root_auth = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=root_frames[0].doc_id,
            index=0,
            total=1,
            data=encode_auth_payload(
                root_doc_hash,
                sign_pub=root_sign_pub,
                signature=sign_auth(
                    root_doc_hash,
                    sign_pub=root_sign_pub,
                    sign_priv=b"\x41" * 32,
                ),
            ),
        )
        bad_extension_ciphertext, _ = encrypt_bytes_with_passphrase(
            b"not-an-extension-envelope",
            passphrase=_EXTENSION_TEST_PASSPHRASE,
        )
        bad_extension_doc_id, bad_extension_doc_hash = _doc_id_and_hash_from_ciphertext(
            bad_extension_ciphertext
        )
        bad_extension_frames = list(
            chunk_payload(
                bad_extension_ciphertext,
                doc_id=bad_extension_doc_id,
                frame_type=FrameType.MAIN_DOCUMENT,
                chunk_size=400,
            )
        )
        bad_extension_auth = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=bad_extension_doc_id,
            index=0,
            total=1,
            data=encode_auth_payload(
                bad_extension_doc_hash,
                sign_pub=root_sign_pub,
                signature=sign_auth(
                    bad_extension_doc_hash,
                    sign_pub=root_sign_pub,
                    sign_priv=b"\x41" * 32,
                ),
            ),
        )

        result = inspector.inspect_pasted_text(
            _payload_text_from_frames(
                [*root_frames, root_auth, *bad_extension_frames, bad_extension_auth]
            ),
            selected_mode=inspector.MODE_AUTO,
            passphrase=_EXTENSION_TEST_PASSPHRASE,
            source_label="root plus broken extension",
        )

        self.assertIsNone(result.document_json_text)
        self.assertIn(
            (
                "Document decode failed: latest recovery head could not be trusted: "
                "some decoded documents failed reassembly or envelope decoding; "
                "refusing partial projection"
            ),
            result.diagnostics_text,
        )
        self.assertIn("Trust code: RECOVERY_HEAD_UNTRUSTED", result.projection_diagnostics_text)
        self.assertIn("Failure stage: decode", result.projection_diagnostics_text)
        self.assertIn("Validated head: index=0", result.projection_diagnostics_text)
        self._decoded_trust_report(result)
        self.assertIsNotNone(result.trust_diagnostic)
        self.assertEqual(result.trust_diagnostic.code, "RECOVERY_HEAD_UNTRUSTED")
        self.assertEqual(result.trust_diagnostic.details["validated_head_index"], 0)

    def test_build_batch_report_includes_success_and_error_entries(self) -> None:
        entries = [
            inspector.BatchReportEntry(
                source_label="good",
                source_path="/tmp/good.pdf",
                frame_count=3,
                doc_ids=("abcd",),
                frame_types=("AUTH", "MAIN_DOCUMENT"),
                warnings=("warn-1",),
                error=None,
            ),
            inspector.BatchReportEntry(
                source_label="bad",
                source_path="/tmp/bad.pdf",
                frame_count=0,
                doc_ids=(),
                frame_types=(),
                warnings=(),
                error="scan failed",
            ),
        ]

        text, json_text = inspector.build_batch_report(entries)
        decoded = json.loads(json_text)

        self.assertIn("/tmp/good.pdf", text)
        self.assertIn("ERROR - scan failed", text)
        self.assertEqual(len(decoded["entries"]), 2)


if __name__ == "__main__":
    unittest.main()
