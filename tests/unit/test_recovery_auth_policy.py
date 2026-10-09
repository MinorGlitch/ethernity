"""Inspection and execution must apply the same AUTH policy."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.signing import derive_public_key, encode_auth_payload, sign_auth
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.workflows.recovery.inspection import inspect_recovery_inputs
from ethernity.workflows.recovery.keys import resolve_auth_payload

_CIPHERTEXT = b"encrypted backup for AUTH policy tests"
_DOC_ID, _DOC_HASH = doc_id_and_hash_from_ciphertext(_CIPHERTEXT)
_SIGNING_SEED = b"s" * 32
_SIGN_PUB = derive_public_key(_SIGNING_SEED)
_MAIN = Frame(VERSION, FrameType.MAIN_DOCUMENT, _DOC_ID, 0, 1, _CIPHERTEXT)


def _auth_frame(*, doc_hash: bytes = _DOC_HASH, invalid_signature: bool = False) -> Frame:
    signature = sign_auth(doc_hash, sign_pub=_SIGN_PUB, sign_priv=_SIGNING_SEED)
    if invalid_signature:
        signature = b"\0" * len(signature)
    return Frame(
        VERSION,
        FrameType.AUTH,
        _DOC_ID,
        0,
        1,
        encode_auth_payload(doc_hash, sign_pub=_SIGN_PUB, signature=signature),
    )


@pytest.fixture
def auth_cases() -> dict[str, list[Frame]]:
    valid = _auth_frame()
    return {
        "valid": [valid],
        "missing": [],
        "multiple": [valid, replace(valid, doc_id=b"x" * len(_DOC_ID))],
        "wrong_id": [replace(valid, doc_id=b"x" * len(_DOC_ID))],
        "multiframe": [replace(valid, total=2, index=1)],
        "malformed": [replace(valid, data=b"invalid AUTH")],
        "wrong_hash": [_auth_frame(doc_hash=b"x" * len(_DOC_HASH))],
        "bad_signature": [_auth_frame(invalid_signature=True)],
    }


@pytest.mark.parametrize("allow_unsigned", [False, True])
@pytest.mark.parametrize(
    ("case", "status", "unsigned_status", "code"),
    [
        ("valid", "verified", "verified", None),
        ("missing", "missing", "skipped", "AUTH_PAYLOAD_MISSING"),
        ("multiple", "invalid", "invalid", "AUTH_PAYLOAD_MULTIPLE"),
        ("wrong_id", "invalid", "ignored", "AUTH_PAYLOAD_DOC_ID_MISMATCH"),
        ("multiframe", "invalid", "invalid", "AUTH_PAYLOAD_FRAME_INVALID"),
        ("malformed", "invalid", "invalid", "AUTH_PAYLOAD_INVALID"),
        ("wrong_hash", "ignored", "ignored", "AUTH_DOC_HASH_MISMATCH"),
        ("bad_signature", "ignored", "ignored", "AUTH_SIGNATURE_INVALID"),
    ],
)
def test_inspection_and_execution_agree_on_auth_policy(
    auth_cases: dict[str, list[Frame]],
    case: str,
    status: str,
    unsigned_status: str,
    code: str | None,
    allow_unsigned: bool,
) -> None:
    auth_frames = auth_cases[case]
    expected_status = unsigned_status if allow_unsigned else status
    blocks = code is not None and (not allow_unsigned or case in {"multiple", "multiframe"})
    execution_notices = []
    kwargs = {
        "doc_id": _DOC_ID,
        "doc_hash": _DOC_HASH,
        "allow_unsigned": allow_unsigned,
        "require_auth": not allow_unsigned,
        "_notice_sink": execution_notices.append,
    }
    if blocks:
        with pytest.raises(ValueError):
            resolve_auth_payload(auth_frames, **kwargs)
        execution_payload = None
    else:
        execution_payload, execution_status = resolve_auth_payload(auth_frames, **kwargs)
        assert execution_status == expected_status

    inspection_notices = []
    inspection = inspect_recovery_inputs(
        frames=[_MAIN],
        extra_auth_frames=auth_frames,
        shard_frames=[],
        passphrase="  exact custom passphrase  ",
        allow_unsigned=allow_unsigned,
        input_label=None,
        input_detail=None,
        shard_fallback_files=[],
        shard_payloads_file=[],
        shard_scan=[],
        _notice_sink=inspection_notices.append,
    )
    assert inspection.auth_status == expected_status
    assert inspection.auth_payload == execution_payload
    assert inspection_notices == execution_notices
    assert inspection.unlock.satisfied is not blocks
    assert [issue["code"] for issue in inspection.blocking_issues] == ([code] if blocks else [])
    assert inspection.unlock.resolved_passphrase == (
        None if blocks else "  exact custom passphrase  "
    )


def test_required_auth_cannot_be_bypassed_with_unsigned_policy() -> None:
    notices = []
    with pytest.raises(ValueError, match="missing auth payload"):
        resolve_auth_payload(
            [],
            doc_id=_DOC_ID,
            doc_hash=_DOC_HASH,
            allow_unsigned=True,
            require_auth=True,
            _notice_sink=notices.append,
        )
    assert notices == []
