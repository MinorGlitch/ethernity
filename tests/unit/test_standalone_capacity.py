from __future__ import annotations

import hashlib
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.config.types import DEFAULT_EXTENSION_CHUNKING_PROFILE
from ethernity.core.bounds import MAX_CIPHERTEXT_BYTES, MAX_MANIFEST_FILES
from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.signing import AuthPayload, derive_public_key, encode_auth_payload, sign_auth
from ethernity.encoding.chunking import chunk_payload
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.extensions.build import build_extension
from ethernity.extensions.chain import AuthenticatedExtensionChainLink, replay_authenticated_chain
from ethernity.formats import document_codec, payload_codec
from ethernity.formats.manifest import BackupFile
from ethernity.workflows.add_files.capacity import require_rebuildable_result
from ethernity.workflows.add_files.errors import AddFilesWorkflowError
from ethernity.workflows.add_files.request import AddFilesRequest
from ethernity.workflows.add_files.service import assess_add_files
from ethernity.workflows.backup.execution import _prepare_backup_document
from ethernity.workflows.shared import issue_codes, standalone
from ethernity.workflows.shared.input_scope import SelectedInputScope
from ethernity.workflows.shared.operation_types import InputFile

SIGNING_SEED = b"s" * 32
PASSPHRASE = "standalone-capacity-test-passphrase"


def _capacity(parts: tuple[BackupFile, ...]) -> int:
    return standalone.require_standalone_capacity(
        parts,
        signing_seed=SIGNING_SEED,
        passphrase=PASSPHRASE,
        input_origin="directory",
        input_roots=("reconstructed-state",),
    )


def _auth(doc_hash: bytes) -> AuthPayload:
    sign_pub = derive_public_key(SIGNING_SEED)
    return AuthPayload(
        version=1,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        signature=sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=SIGNING_SEED),
    )


def _scope(path: str, data: bytes) -> SelectedInputScope:
    return SelectedInputScope(
        raw_files=(path,),
        raw_directories=(),
        base_dir_arg=None,
        input_files=(InputFile(source_path=None, relative_path=path, data=data, mtime=1),),
        base_dir=None,
        input_origin="file",
        input_roots=(),
        exact_paths=(path,),
        directory_prefixes=(),
    )


def test_capacity_counts_manifest_and_encryption_overhead_for_incompressible_files() -> None:
    payload = random.Random(42).randbytes(MAX_CIPHERTEXT_BYTES - 1)
    assert len(payload) < MAX_CIPHERTEXT_BYTES
    with pytest.raises(ValueError, match="standalone ciphertext exceeds MAX_CIPHERTEXT_BYTES"):
        _capacity((BackupFile(path="data.bin", data=payload, mtime=1),))


def test_capacity_reserves_timestamp_growth_before_a_later_rebuild(monkeypatch) -> None:
    short_timestamp = 1_700_000_000
    long_timestamp = short_timestamp + 1
    monkeypatch.setattr(document_codec.time, "time", lambda: short_timestamp)
    entropy = random.Random(42)
    payload = entropy.randbytes(MAX_CIPHERTEXT_BYTES - 4096)

    def encode(data: bytes) -> bytes:
        return standalone.encode_standalone_backup(
            [BackupFile(path="data.bin", data=data, mtime=1)],
            sealed=False,
            signing_seed=SIGNING_SEED,
            input_origin="directory",
            input_roots=("reconstructed-state",),
        )[0]

    trial_ciphertext, _passphrase = encrypt_bytes_with_passphrase(
        encode(payload), passphrase=PASSPHRASE
    )
    remaining = MAX_CIPHERTEXT_BYTES - len(trial_ciphertext)
    boundary_payload = payload + entropy.randbytes(remaining)
    short_document = encode(boundary_payload)
    short_ciphertext, _passphrase = encrypt_bytes_with_passphrase(
        short_document, passphrase=PASSPHRASE
    )
    assert len(short_ciphertext) == MAX_CIPHERTEXT_BYTES
    assert document_codec.decode_backup_document(short_document)[0].created_at == short_timestamp

    # The old probe would accept this at the short timestamp, then overflow later.
    with pytest.raises(ValueError, match="standalone ciphertext exceeds MAX_CIPHERTEXT_BYTES"):
        _capacity((BackupFile(path="data.bin", data=boundary_payload, mtime=1),))

    monkeypatch.setattr(document_codec.time, "time", lambda: long_timestamp)
    long_document = encode(boundary_payload)
    assert len(long_document) == len(short_document) + 4
    assert document_codec.decode_backup_document(long_document)[0].created_at == long_timestamp

    # Reserving that growth accepts only a state which remains within the bound.
    accepted_payload = boundary_payload[:-4]
    assert (
        _capacity((BackupFile(path="data.bin", data=accepted_payload, mtime=1),))
        == MAX_CIPHERTEXT_BYTES
    )
    rebuilt_ciphertext, _passphrase = encrypt_bytes_with_passphrase(
        encode(accepted_payload), passphrase=PASSPHRASE
    )
    assert len(rebuilt_ciphertext) == MAX_CIPHERTEXT_BYTES


def test_capacity_reserves_timestamp_growth_at_the_manifest_limit(monkeypatch) -> None:
    parts = (BackupFile(path="notes.txt", data=b"notes", mtime=1),)
    backup_document, _payload = standalone.encode_standalone_backup(
        parts,
        sealed=False,
        signing_seed=SIGNING_SEED,
        input_origin="directory",
        input_roots=("reconstructed-state",),
        created_at=1_700_000_000,
    )
    manifest = document_codec.decode_backup_document(backup_document)[0]
    shorter_manifest_bytes = len(document_codec.encode_manifest(manifest))
    monkeypatch.setattr(document_codec, "MAX_MANIFEST_CBOR_BYTES", shorter_manifest_bytes)
    monkeypatch.setattr(document_codec.time, "time", lambda: 1_700_000_000)
    with pytest.raises(ValueError, match="manifest exceeds MAX_MANIFEST_CBOR_BYTES"):
        _capacity(parts)


def test_assessment_rejects_overgrown_merged_state_without_publishing(tmp_path: Path) -> None:
    entropy = random.Random(42)
    root_document, _payload = standalone.encode_standalone_backup(
        [BackupFile(path="first.bin", data=entropy.randbytes(700 * 1024), mtime=1)],
        sealed=False,
        signing_seed=SIGNING_SEED,
        input_origin="file",
        input_roots=(),
    )
    ciphertext, _passphrase = encrypt_bytes_with_passphrase(root_document, passphrase=PASSPHRASE)
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    auth = _auth(doc_hash)
    frames = (
        *chunk_payload(ciphertext, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT),
        Frame(
            VERSION,
            FrameType.AUTH,
            doc_id,
            0,
            1,
            encode_auth_payload(doc_hash, sign_pub=auth.sign_pub, signature=auth.signature),
        ),
    )
    addition = tmp_path / "second.bin"
    added_bytes = entropy.randbytes(700 * 1024)
    addition.write_bytes(added_bytes)
    assessment = assess_add_files(
        AddFilesRequest(
            config_path=str(DEFAULT_CONFIG_PATH),
            frames=frames,
            passphrase=PASSPHRASE,
            expected_head_doc_hash=doc_hash.hex(),
            input_paths=(str(addition),),
            base_directory=str(tmp_path),
            output_dir=str(tmp_path / "output-parent" / "update"),
        )
    )
    assert not assessment.ready
    assert assessment.issues[0].code == issue_codes.ADD_FILES_NOT_REBUILDABLE
    assert assessment.issues[0].details["stage"] == "rebuild_capacity"
    assert addition.read_bytes() == added_bytes
    assert sorted(path.name for path in tmp_path.iterdir()) == ["second.bin"]


def test_capacity_uses_compression_instead_of_rejecting_large_raw_files() -> None:
    payload = b"paper recovery contents\n" * 100_000
    assert len(payload) > MAX_CIPHERTEXT_BYTES
    assert _capacity((BackupFile(path="notes.txt", data=payload, mtime=1),)) < 10_000


def test_capacity_checks_standalone_manifest_size_even_when_all_files_are_empty() -> None:
    entropy = random.Random(42)
    parts = tuple(
        BackupFile(path=entropy.randbytes(256).hex(), data=b"", mtime=1)
        for _index in range(MAX_MANIFEST_FILES)
    )
    with pytest.raises(ValueError, match="manifest exceeds MAX_MANIFEST_CBOR_BYTES"):
        _capacity(parts)


def test_capacity_checks_standalone_file_count() -> None:
    parts = tuple(
        BackupFile(path=f"file-{index}.txt", data=b"", mtime=None)
        for index in range(MAX_MANIFEST_FILES + 1)
    )
    with pytest.raises(ValueError, match="manifest files exceed MAX_MANIFEST_FILES"):
        _capacity(parts)


def test_capacity_checks_decoded_payload_limit_before_encryption(monkeypatch) -> None:
    monkeypatch.setattr(payload_codec, "MAX_DECOMPRESSED_PAYLOAD_BYTES", 16)
    with pytest.raises(ValueError, match="payload exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES"):
        _capacity((BackupFile(path="data.txt", data=b"x" * 17, mtime=None),))


def test_merged_state_is_checked_and_existing_oversized_chains_can_shrink() -> None:
    entropy = random.Random(42)
    first = entropy.randbytes(700 * 1024)
    second = entropy.randbytes(700 * 1024)
    manifest, payload = document_codec.build_manifest_and_payload(
        [BackupFile(path="first.bin", data=first, mtime=1)],
        signing_seed=SIGNING_SEED,
    )
    root_hash = hashlib.blake2b(b"authenticated root identity", digest_size=32).digest()
    root_auth = _auth(root_hash)
    root = replay_authenticated_chain(
        manifest,
        payload,
        root_doc_hash=root_hash,
        root_auth_payload=root_auth,
        expected_sign_pub=root_auth.sign_pub,
        extensions=(),
        root_chunking=DEFAULT_EXTENSION_CHUNKING_PROFILE,
    )
    oversized = build_extension(root, _scope("second.bin", second))
    prepared = SimpleNamespace(signing_seed=SIGNING_SEED, encryption_passphrase=PASSPHRASE)

    # Both individual documents fit; the resulting standalone state does not.
    assert _capacity((BackupFile(path="first.bin", data=first, mtime=1),)) < MAX_CIPHERTEXT_BYTES
    assert _capacity((BackupFile(path="second.bin", data=second, mtime=1),)) < MAX_CIPHERTEXT_BYTES
    with pytest.raises(AddFilesWorkflowError) as caught:
        require_rebuildable_result(prepared, oversized)
    assert caught.value.code == issue_codes.ADD_FILES_NOT_REBUILDABLE
    assert caught.value.details["stage"] == "rebuild_capacity"

    # Replay deliberately remains compatible with a chain made before this publication rule.
    extension_hash = hashlib.blake2b(b"existing extension identity", digest_size=32).digest()
    chain = replay_authenticated_chain(
        manifest,
        payload,
        root_doc_hash=root_hash,
        root_auth_payload=root_auth,
        expected_sign_pub=root_auth.sign_pub,
        extensions=(
            AuthenticatedExtensionChainLink(
                doc_hash=extension_hash,
                document=oversized.document,
                auth_payload=_auth(extension_hash),
                expected_sign_pub=root_auth.sign_pub,
            ),
        ),
        root_chunking=DEFAULT_EXTENSION_CHUNKING_PROFILE,
    )
    assert sum(item.size for item in chain.files) == 1400 * 1024
    reduced = build_extension(chain, _scope("second.bin", b"small replacement"))
    assert require_rebuildable_result(prepared, reduced) < MAX_CIPHERTEXT_BYTES
    assert next(item.data for item in reduced.resulting_state if item.path == "first.bin") == first


def test_shared_encoder_matches_backup_document(monkeypatch) -> None:
    monkeypatch.setattr(document_codec.time, "time", lambda: 1_700_000_000)
    data = b"compressible contents" * 1000
    parts = (BackupFile(path="notes.txt", data=data, mtime=1),)
    expected = standalone.encode_standalone_backup(
        parts,
        sealed=False,
        signing_seed=SIGNING_SEED,
        input_origin="file",
        input_roots=(),
    )
    actual = _prepare_backup_document(
        [InputFile(source_path=None, relative_path="notes.txt", data=data, mtime=1)],
        SimpleNamespace(sealed=False),
        SIGNING_SEED,
        "file",
        [],
    )
    assert actual == expected
