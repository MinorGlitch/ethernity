"""Standalone backups and recovery quorums publish only after complete validation."""

from pathlib import Path
from unittest import mock

import pytest

from ethernity.config import AppConfig
from ethernity.core.models import DocumentPlan, ShardingConfig, SigningSeedMode
from ethernity.crypto import sharding
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import VERSION, Frame, FrameType, encode_frame
from ethernity.encoding.qr_payloads import encode_qr_payload
from ethernity.qr.codec import QrConfig
from ethernity.render.checks import RenderValidationError
from ethernity.render.types import DocumentOrigin
from ethernity.workflows.backup import execution
from ethernity.workflows.rebuild.service import execute_rebuild_operation
from ethernity.workflows.recovery.frame_inputs import frames_from_scan
from ethernity.workflows.shared.operation_types import InputFile, RebuildOperationRequest

_CONFIG = AppConfig(
    design_name="sentinel", paper_size="A4", qr_config=QrConfig(), qr_chunk_size=1024
)


def _create_backup(path: Path, *, sealed: bool = False, sharded: bool = False):
    return execution.run_backup(
        input_files=[InputFile(None, "hello.txt", b"paper-first backup", 0)],
        base_dir=None,
        output_dir=str(path),
        plan=DocumentPlan(
            version=1,
            sealed=sealed,
            sharding=ShardingConfig(2, 3) if sharded else None,
            signing_seed_mode=SigningSeedMode.SHARDED if sharded else SigningSeedMode.EMBEDDED,
        ),
        passphrase="test passphrase",
        config=_CONFIG,
        render_origin=DocumentOrigin(kind="root_backup"),
        quiet=True,
    )


def _backup_identity(result):
    output = Path(result.qr_path).parent
    expected = {Path(result.qr_path), Path(result.recovery_path)}
    if result.kit_index_path is not None:
        expected.add(Path(result.kit_index_path))
    assert set(output.iterdir()) == expected
    frames = frames_from_scan([str(output)])
    ciphertext = reassemble_payload(
        [frame for frame in frames if frame.frame_type == FrameType.MAIN_DOCUMENT]
    )
    _, root_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    assert result.doc_hash == root_hash
    auth = execution.signing_module.decode_auth_payload(
        next(frame.data for frame in frames if frame.frame_type == FrameType.AUTH)
    )
    return root_hash, auth.sign_pub


@pytest.mark.parametrize("sealed", (False, True))
def test_create_and_rebuild_publish_only_backup_documents(tmp_path: Path, sealed: bool) -> None:
    original = _create_backup(tmp_path / "original", sealed=sealed)
    first = _backup_identity(original)
    rebuilt = execute_rebuild_operation(
        RebuildOperationRequest(
            scan=[original.qr_path],
            output_dir=str(tmp_path / "rebuilt"),
            passphrase="test passphrase",
            expected_head_doc_hash=first[0].hex(),
            quiet=True,
        )
    )
    second = _backup_identity(rebuilt)
    assert first[0] != second[0]
    assert rebuilt.signing_key_preserved is (not sealed)
    if not sealed:
        assert first[1] == second[1]


def test_sharded_create_reconstructs_both_secrets_from_staged_carriers(tmp_path: Path) -> None:
    with (
        mock.patch.object(
            sharding, "recover_passphrase", wraps=sharding.recover_passphrase
        ) as passphrase,
        mock.patch.object(
            sharding, "recover_signing_seed", wraps=sharding.recover_signing_seed
        ) as signing,
    ):
        result = _create_backup(tmp_path / "root", sharded=True)
    assert passphrase.call_count == signing.call_count == 1
    assert len(passphrase.call_args.args[0]) == len(signing.call_args.args[0]) == 2
    assert len(result.shard_paths) == len(result.signing_key_shard_paths) == 3


@pytest.mark.parametrize("failure", ("document", "quorum"))
def test_validation_failure_leaves_no_published_backup(tmp_path: Path, failure: str) -> None:
    output = tmp_path / "failed"
    if failure == "document":
        validate = execution.validate_rendered_pdf_document

        def reject_document(*args, **kwargs):
            if kwargs["inputs"].doc_type == "recovery":
                raise RenderValidationError("invalid recovery fallback")
            return validate(*args, **kwargs)

        patcher = mock.patch.object(execution, "validate_rendered_pdf_document", reject_document)
    else:
        patcher = mock.patch.object(sharding, "recover_passphrase", return_value="wrong secret")
    with patcher, pytest.raises((ValueError, RenderValidationError)):
        _create_backup(output, sharded=failure == "quorum")
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mismatch", ("identity", "hash", "signing_key"))
def test_staged_shard_quorum_rejects_wrong_root_binding(mismatch: str) -> None:
    seed = b"s" * 32
    sign_pub = derive_public_key(seed)
    shard_seed = b"x" * 32 if mismatch == "signing_key" else seed
    root_hash = b"r" * 32
    root_id = b"i" * 8
    shares = sharding.split_passphrase(
        "test passphrase",
        threshold=2,
        shares=3,
        doc_hash=b"x" * 32 if mismatch == "hash" else root_hash,
        sign_priv=shard_seed,
        sign_pub=derive_public_key(shard_seed),
    )
    frame = Frame(
        VERSION,
        FrameType.KEY_DOCUMENT,
        b"x" * 8 if mismatch == "identity" else root_id,
        0,
        1,
        sharding.encode_shard_payload(shares[0]),
    )
    with (
        mock.patch.object(
            execution, "scan_qr_payloads", return_value=[encode_qr_payload(encode_frame(frame))]
        ),
        pytest.raises(ValueError, match="root"),
    ):
        execution._read_staged_shard_quorum(
            ["sheet.pdf"],
            doc_id=root_id,
            doc_hash=root_hash,
            sign_pub=sign_pub,
            qr_payload_codec="base64",
        )
