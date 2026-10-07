from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.sharding import (
    decode_shard_payload,
    encode_shard_payload,
    split_passphrase,
    split_signing_seed,
)
from ethernity.crypto.signing import (
    decode_auth_payload,
    derive_public_key,
    encode_auth_payload,
    sign_auth,
)
from ethernity.encoding.chunking import chunk_payload
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.formats.document_codec import build_single_file_manifest, encode_backup_document
from ethernity.tasks import recovery_check
from ethernity.tasks.recovery_check import (
    GeneratedRecoveryCheckRequest,
    GeneratedRecoveryPassphraseRequired,
    check_generated_recovery,
)
from ethernity.workflows.execution import (
    RecoveryExecutionResult,
    execute_recovery,
)
from ethernity.workflows.recovery.frame_inputs import frames_from_payloads
from ethernity.workflows.shared.requests import RecoveryRequest

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_PASSPHRASE = "generated-document-check-passphrase"
_PAYLOAD = b"Recovered solely to check document data."


@pytest.fixture(scope="module")
def signed_frames() -> tuple[tuple[Frame, ...], tuple[Frame, ...], Frame]:
    seed = b"\x33" * 32
    public_key = derive_public_key(seed)
    manifest = build_single_file_manifest("message.txt", _PAYLOAD, signing_seed=seed)
    document = encode_backup_document(_PAYLOAD, manifest)
    ciphertext, _ = encrypt_bytes_with_passphrase(document, passphrase=_PASSPHRASE)
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    main = chunk_payload(
        ciphertext,
        doc_id=doc_id,
        frame_type=FrameType.MAIN_DOCUMENT,
        chunk_size=len(ciphertext),
    )
    auth = Frame(
        version=VERSION,
        frame_type=FrameType.AUTH,
        doc_id=doc_id,
        index=0,
        total=1,
        data=encode_auth_payload(
            doc_hash,
            sign_pub=public_key,
            signature=sign_auth(doc_hash, sign_pub=public_key, sign_priv=seed),
        ),
    )
    shares = split_passphrase(
        _PASSPHRASE,
        threshold=2,
        shares=3,
        doc_hash=doc_hash,
        sign_priv=seed,
        sign_pub=public_key,
    )
    sheets = tuple(
        Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=encode_shard_payload(share),
        )
        for share in shares
    )
    signing_share = split_signing_seed(
        seed,
        threshold=2,
        shares=3,
        doc_hash=doc_hash,
        sign_priv=seed,
        sign_pub=public_key,
    )[0]
    signing_sheet = replace(sheets[0], data=encode_shard_payload(signing_share))
    return (*main, auth), sheets, signing_sheet


@pytest.fixture
def temporary_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    paths: list[Path] = []

    def temporary_directory(*, prefix: str) -> TemporaryDirectory[str]:
        directory = TemporaryDirectory(prefix=prefix, dir=tmp_path)
        paths.append(Path(directory.name))
        return directory

    monkeypatch.setattr(recovery_check, "TemporaryDirectory", temporary_directory)
    return paths


def _scan_frames(monkeypatch: pytest.MonkeyPatch, frames: tuple[Frame, ...]) -> None:
    monkeypatch.setattr(recovery_check.frame_inputs, "frames_from_scan", lambda paths: list(frames))


def test_generated_check_recovers_using_only_minimum_quorum_and_removes_plaintext(
    monkeypatch: pytest.MonkeyPatch, signed_frames, temporary_checks
) -> None:
    main, sheets, signing_sheet = signed_frames
    _scan_frames(monkeypatch, (*main, sheets[2], *sheets, signing_sheet))
    requests: list[RecoveryRequest] = []

    def recover(request: RecoveryRequest):
        requests.append(request)
        return execute_recovery(request)

    monkeypatch.setattr(recovery_check, "execute_recovery", recover)
    result = check_generated_recovery(
        GeneratedRecoveryCheckRequest(
            documents=(Path("arbitrary-name.pdf"),), passphrase="wrong cached phrase"
        )
    )

    assert result.file_count == 1
    assert result.total_bytes == len(_PAYLOAD)
    assert result.recovery_sheet_count == 2
    assert requests[0].shard_frames == sheets[:2]
    assert requests[0].passphrase is None
    assert requests[0].frames == main
    assert temporary_checks
    assert all(not path.exists() for path in temporary_checks)


def test_generated_check_requires_deliberate_passphrase_when_no_sheets_are_supplied(
    monkeypatch: pytest.MonkeyPatch, signed_frames, temporary_checks
) -> None:
    main, _, signing_sheet = signed_frames
    _scan_frames(monkeypatch, (*main, signing_sheet))

    with pytest.raises(GeneratedRecoveryPassphraseRequired, match="printed"):
        check_generated_recovery(GeneratedRecoveryCheckRequest(documents=(Path("document.pdf"),)))

    assert not temporary_checks
    result = check_generated_recovery(
        GeneratedRecoveryCheckRequest(documents=(Path("document.pdf"),), passphrase=_PASSPHRASE)
    )
    assert result.file_count == 1
    assert result.recovery_sheet_count == 0
    assert all(not path.exists() for path in temporary_checks)


def test_generated_check_rejects_under_quorum_even_when_a_cached_phrase_is_available(
    monkeypatch: pytest.MonkeyPatch, signed_frames, temporary_checks
) -> None:
    main, sheets, _ = signed_frames
    _scan_frames(monkeypatch, (*main, sheets[0]))

    with pytest.raises(ValueError, match="at least 2"):
        check_generated_recovery(
            GeneratedRecoveryCheckRequest(documents=(Path("document.pdf"),), passphrase=_PASSPHRASE)
        )

    assert not temporary_checks


def test_printed_check_rejects_another_valid_backup_and_removes_temporary_storage(
    monkeypatch: pytest.MonkeyPatch, signed_frames, temporary_checks
) -> None:
    main, sheets, _ = signed_frames
    _scan_frames(monkeypatch, (*main, *sheets))

    with pytest.raises(ValueError, match="does not match expected head"):
        check_generated_recovery(
            GeneratedRecoveryCheckRequest(
                documents=(Path("photographed-backup.png"), Path("photographed-sheets.png")),
                expected_head_doc_hash="99" * 32,
            )
        )

    assert temporary_checks
    assert all(not path.exists() for path in temporary_checks)


def test_generated_check_rejects_tampered_extra_sheet_before_choosing_a_quorum(
    monkeypatch: pytest.MonkeyPatch, signed_frames, temporary_checks
) -> None:
    main, sheets, _ = signed_frames
    payload = decode_shard_payload(sheets[2].data)
    invalid = replace(payload, signature=bytes([payload.signature[0] ^ 1]) + payload.signature[1:])
    _scan_frames(
        monkeypatch, (*main, *sheets[:2], replace(sheets[2], data=encode_shard_payload(invalid)))
    )

    with pytest.raises(ValueError, match="invalid shard signature"):
        check_generated_recovery(GeneratedRecoveryCheckRequest(documents=(Path("document.pdf"),)))

    assert not temporary_checks


def test_generated_check_rejects_authentication_failure_instead_of_prompting_for_passphrase(
    monkeypatch: pytest.MonkeyPatch, signed_frames, temporary_checks
) -> None:
    main, _, _ = signed_frames
    payload = decode_auth_payload(main[-1].data)
    invalid_signature = bytes([payload.signature[0] ^ 1]) + payload.signature[1:]
    tampered_auth = replace(
        main[-1],
        data=encode_auth_payload(
            payload.doc_hash, sign_pub=payload.sign_pub, signature=invalid_signature
        ),
    )
    _scan_frames(monkeypatch, (*main[:-1], tampered_auth))

    with pytest.raises(ValueError, match="invalid auth signature"):
        check_generated_recovery(GeneratedRecoveryCheckRequest(documents=(Path("document.pdf"),)))

    assert not temporary_checks


def test_generated_check_cleans_temporary_files_after_execution_failure(
    monkeypatch: pytest.MonkeyPatch, signed_frames, temporary_checks
) -> None:
    main, sheets, _ = signed_frames
    _scan_frames(monkeypatch, (*main, *sheets))

    def fail_after_write(request: RecoveryRequest):
        assert request.output_path is not None
        request.output_path.write_bytes(b"partial recovered plaintext")
        raise ValueError("failed file validation")

    monkeypatch.setattr(recovery_check, "execute_recovery", fail_after_write)
    with pytest.raises(ValueError, match="failed file validation"):
        check_generated_recovery(GeneratedRecoveryCheckRequest(documents=(Path("document.pdf"),)))

    assert temporary_checks
    assert all(not path.exists() for path in temporary_checks)


def test_generated_check_preserves_root_and_update_ancestry_from_payload_inputs(
    monkeypatch: pytest.MonkeyPatch, temporary_checks, tmp_path: Path
) -> None:
    chain = _FIXTURES / "v1_2/extension_golden/raw/large_raw_two_extension_chain"
    snapshot = json.loads((chain / "snapshot.json").read_text(encoding="utf-8"))
    new_frames = tuple(frames_from_payloads(str(chain / "extension_02_payloads.txt")))
    _scan_frames(monkeypatch, new_frames)
    base_frames = tuple(frames_from_payloads(str(chain / "extension_01_payloads.txt")))
    sheets = tuple(frames_from_payloads(str(chain / "root_shard_payloads_threshold.txt")))
    permanent_destination = tmp_path / "user-output"

    result = check_generated_recovery(
        GeneratedRecoveryCheckRequest(
            documents=(Path("new-update.pdf"),),
            base_request=RecoveryRequest(
                frames=base_frames,
                payloads_file=chain / "root_payloads.txt",
                shard_frames=sheets,
                output_path=permanent_destination,
            ),
            expected_head_doc_hash=snapshot["extension_doc_hashes"]["extension_02"],
        )
    )

    assert result.file_count == 3
    assert result.total_bytes == 40960 + 20480 + 28672
    assert result.recovery_sheet_count == 2
    assert not permanent_destination.exists()
    assert all(not path.exists() for path in temporary_checks)


def test_generated_check_requires_document_paths(temporary_checks) -> None:
    with pytest.raises(ValueError, match="Choose backup documents"):
        check_generated_recovery(GeneratedRecoveryCheckRequest(documents=()))

    assert not temporary_checks


def test_generated_check_cleans_temporary_storage_after_wrong_passphrase(
    monkeypatch: pytest.MonkeyPatch, signed_frames, temporary_checks
) -> None:
    main, _, _ = signed_frames
    _scan_frames(monkeypatch, main)

    with pytest.raises(Exception) as failure:
        check_generated_recovery(
            GeneratedRecoveryCheckRequest(
                documents=(Path("document.pdf"),), passphrase="incorrect phrase"
            )
        )

    assert not isinstance(failure.value, GeneratedRecoveryPassphraseRequired)
    assert temporary_checks
    assert all(not path.exists() for path in temporary_checks)


def test_generated_check_rejects_empty_recovery_results_and_removes_temporary_storage(
    monkeypatch: pytest.MonkeyPatch, signed_frames, temporary_checks
) -> None:
    main, sheets, _ = signed_frames
    _scan_frames(monkeypatch, (*main, *sheets))
    monkeypatch.setattr(
        recovery_check,
        "execute_recovery",
        lambda request: RecoveryExecutionResult(written_paths=()),
    )

    with pytest.raises(ValueError, match="No files were recovered"):
        check_generated_recovery(GeneratedRecoveryCheckRequest(documents=(Path("document.pdf"),)))

    assert temporary_checks
    assert all(not path.exists() for path in temporary_checks)
