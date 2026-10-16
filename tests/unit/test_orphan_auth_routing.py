"""Orphan AUTH handling uses error types and preserves authentication policy."""

from dataclasses import replace
from unittest.mock import Mock

import pytest

from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.extensions.errors import OrphanAuthFramesError
from ethernity.extensions.recovery import imported_documents_from_recovery_frames
from ethernity.workflows.recovery import root_selection
from ethernity.workflows.recovery.keys import AuthValidationError
from ethernity.workflows.recovery.planning import inspect_from_request, plan_from_request
from ethernity.workflows.shared.requests import RecoveryRequest


@pytest.fixture
def main_frames() -> list[Frame]:
    return [
        Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id_and_hash_from_ciphertext(data)[0],
            index=0,
            total=1,
            data=data,
        )
        for data in (b"first ciphertext", b"second ciphertext")
    ]


@pytest.fixture
def orphan_auth() -> Frame:
    return Frame(
        version=VERSION,
        frame_type=FrameType.AUTH,
        doc_id=b"orphan!!",
        index=0,
        total=1,
        data=b"unmatched authentication",
    )


@pytest.fixture(params=[False, True])
def error_wording(request, monkeypatch) -> None:
    if request.param:
        monkeypatch.setattr(OrphanAuthFramesError, "__str__", lambda _self: "Unrelated wording.")


def test_importer_reports_all_orphan_document_ids(main_frames, orphan_auth) -> None:
    orphans = [replace(orphan_auth, doc_id=bytes([i]) * 8) for i in range(5)]
    with pytest.raises(OrphanAuthFramesError) as raised:
        imported_documents_from_recovery_frames(
            [*main_frames, *reversed(orphans), orphans[0]], source_label="scanned backup"
        )

    assert raised.value.doc_ids == tuple(frame.doc_id for frame in orphans)
    assert raised.value.source_label == "scanned backup"
    assert str(raised.value).endswith(", ".join(frame.doc_id.hex() for frame in orphans[:3]))
    assert isinstance(raised.value, ValueError)


def test_single_document_defers_extra_auth_to_authentication(
    main_frames, orphan_auth, error_wording
) -> None:
    documents = root_selection.import_recovery_documents(
        main_frames[:1], [orphan_auth], source_label="single backup"
    )

    assert len(documents) == 1
    assert documents[0].doc_id == main_frames[0].doc_id
    assert documents[0].auth_frames == ()


def test_multiple_documents_never_ignore_extra_orphan_auth(
    main_frames, orphan_auth, error_wording
) -> None:
    with pytest.raises(OrphanAuthFramesError) as raised:
        root_selection.import_recovery_documents(
            main_frames, [orphan_auth], source_label="backup chain"
        )

    assert raised.value.doc_ids == (orphan_auth.doc_id,)
    assert raised.value.source_label == "backup chain"


@pytest.mark.parametrize("include_main", [False, True])
def test_orphan_auth_in_primary_carriers_is_never_dropped(
    main_frames, orphan_auth, error_wording, include_main
) -> None:
    frames = [*main_frames[:1], orphan_auth] if include_main else [orphan_auth]
    with pytest.raises(OrphanAuthFramesError):
        root_selection.import_recovery_documents(frames, [], source_label="primary carriers")


def test_matching_english_in_another_failure_cannot_trigger_fallback(
    main_frames, orphan_auth, monkeypatch
) -> None:
    error = ValueError("some other error contains AUTH frame(s) without matching MAIN")
    importer = Mock(side_effect=error)
    monkeypatch.setattr(root_selection, "imported_documents_from_recovery_frames", importer)

    with pytest.raises(ValueError) as raised:
        root_selection.import_recovery_documents(
            main_frames[:1], [orphan_auth], source_label="single backup"
        )
    assert raised.value is error
    importer.assert_called_once()


def test_retry_does_not_suppress_invalid_main_identity(main_frames, orphan_auth) -> None:
    with pytest.raises(ValueError, match="MAIN frame doc_id does not match"):
        root_selection.import_recovery_documents(
            [replace(main_frames[0], data=b"tampered")],
            [orphan_auth],
            source_label="single backup",
        )


@pytest.mark.parametrize("allow_unsigned", [False, True])
def test_single_document_fallback_preserves_strict_and_unsigned_authentication(
    main_frames, orphan_auth, error_wording, allow_unsigned
) -> None:
    request = RecoveryRequest(
        frames=tuple(main_frames[:1]),
        auth_frames=(orphan_auth,),
        passphrase="secret",
        allow_unsigned=allow_unsigned,
        quiet=True,
    )
    inspection = inspect_from_request(request)

    assert inspection.source.auth_frames == (orphan_auth,)
    if allow_unsigned:
        assert inspection.auth_status == "ignored"
        assert inspection.blocking_issues == ()
        plan = plan_from_request(request)
        assert plan.auth_status == "ignored"
        assert plan.source.auth_frames == (orphan_auth,)
    else:
        assert inspection.auth_status == "invalid"
        assert inspection.blocking_issues[0]["code"] == "AUTH_PAYLOAD_DOC_ID_MISMATCH"
        with pytest.raises(AuthValidationError) as raised:
            plan_from_request(request)
        assert raised.value.code == "AUTH_PAYLOAD_DOC_ID_MISMATCH"
