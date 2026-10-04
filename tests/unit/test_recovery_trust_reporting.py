from __future__ import annotations

from pathlib import Path

import pytest

from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.signing import AuthPayload, derive_public_key, sign_auth
from ethernity.formats.document_codec import build_manifest_and_payload, encode_backup_document
from ethernity.formats.manifest import BackupFile
from ethernity.workflows.recovery.planning import RecoveryPlan
from ethernity.workflows.recovery.service import execute_recover_plan


@pytest.mark.parametrize(
    ("sealed", "pinned", "authenticated", "expected_basis", "key_verified"),
    [
        (False, True, True, "matched_expected_head", True),
        (True, True, True, "matched_expected_head", False),
        (False, False, True, "internally_consistent", False),
        (True, False, True, "internally_consistent", False),
        (False, True, False, "unauthenticated", False),
    ],
)
def test_root_recovery_reports_only_the_trust_established_by_verification(
    tmp_path: Path,
    sealed: bool,
    pinned: bool,
    authenticated: bool,
    expected_basis: str,
    key_verified: bool,
) -> None:
    seed = b"s" * 32
    manifest, payload = build_manifest_and_payload(
        [BackupFile(path="secret.txt", data=b"recover me", mtime=1)],
        sealed=sealed,
        signing_seed=None if sealed else seed,
        input_origin="file",
        input_roots=[],
    )
    ciphertext, passphrase = encrypt_bytes_with_passphrase(
        encode_backup_document(payload, manifest), passphrase="trust-reporting-test"
    )
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    sign_pub = derive_public_key(seed)
    auth = AuthPayload(
        version=1,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        signature=sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=seed),
    )
    plan = RecoveryPlan(
        ciphertext=ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
        passphrase=passphrase,
        auth_payload=auth if authenticated else None,
        auth_status="verified" if authenticated else "skipped",
        allow_unsigned=not authenticated,
        output_path=str(tmp_path / "restored.txt"),
        input_label="Backup documents",
        input_detail="trusted record test",
        main_frames=(),
        auth_frames=(),
        shard_frames=(),
        shard_fallback_files=(),
        shard_payloads_file=(),
        shard_scan=(),
        expected_head_doc_hash=doc_hash.hex() if pinned else None,
    )

    result = execute_recover_plan(plan, quiet=True)

    assert Path(result.written_paths[0]).read_bytes() == b"recover me"
    assert result.trust_basis == expected_basis
    assert result.signing_key_verified is key_verified
