"""Backup documents validate in order and report only completed work."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ethernity.crypto import sharding
from ethernity.render.checks import RenderValidationError
from ethernity.render.types import (
    DocumentOrigin,
    RenderedDocumentSummary,
    RenderInputs,
    RenderResult,
)
from ethernity.workflows.backup import execution
from ethernity.workflows.shared import events, shard_rendering
from ethernity.workflows.shared.execution_control import (
    ExecutionControl,
    OperationCancelled,
    execution_session,
)


@pytest.fixture
def render_sequence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    origin = DocumentOrigin(kind="root_backup")

    def inputs(doc_type: str, **context: object) -> RenderInputs:
        return RenderInputs(
            frames=(),
            output_path=tmp_path / f"{doc_type}.pdf",
            context=context,
            doc_type=doc_type,
            origin=origin,
            render_qr=False,
            render_fallback=False,
        )

    qr = inputs("qr")
    recovery = inputs("recovery")
    kit = inputs("kit_index", inventory_rows=[{"component_id": "root-123"}])

    def render_document(document: RenderInputs) -> RenderResult:
        if document is kit:
            assert document.context["kit_qr_page_count"] == 4
        return RenderResult(
            document_summary=RenderedDocumentSummary(
                output_path=str(document.output_path),
                doc_type=document.doc_type,
                frame_digests=(),
                encoded_payload_count=0,
                physical_qr_count=0,
                page_count=4,
            )
        )

    renderer = Mock(side_effect=render_document)
    validator = Mock()
    shard_renderer = Mock(
        side_effect=lambda shard, **_kwargs: str(
            tmp_path / f"{shard.key_type}-{shard.share_index}.pdf"
        )
    )
    monkeypatch.setattr(execution.render_module, "render_frames_to_pdf", renderer)
    monkeypatch.setattr(execution, "validate_rendered_pdf_document", validator)
    monkeypatch.setattr(shard_rendering, "render_shard_document", shard_renderer)
    return SimpleNamespace(
        args={
            "qr_inputs": qr,
            "recovery_inputs": recovery,
            "kit_index_inputs": kit,
            "shard_payloads": [],
            "signing_key_shard_payloads": [],
            "doc_id": b"d" * 8,
            "output_dir": str(tmp_path),
            "render_service": Mock(),
            "layout_debug_dir": str(tmp_path / "layout"),
            "qr_payload_codec": "raw",
            "origin": origin,
        },
        renderer=renderer,
        validator=validator,
        shard_renderer=shard_renderer,
        sink=Mock(spec=events.EventSink),
    )


def _document_progress(sink: Mock) -> list[dict]:
    return [call.kwargs for call in sink.emit.call_args_list if call.args == ("progress",)]


@pytest.mark.parametrize("include_index", (False, True))
def test_render_sequence_validates_documents_and_orders_both_shard_groups(
    render_sequence, include_index: bool
) -> None:
    sequence = render_sequence
    args = sequence.args
    seed, public_key = execution.signing_module.generate_signing_keypair()
    for field, split, secret in (
        ("shard_payloads", sharding.split_passphrase, "test passphrase"),
        ("signing_key_shard_payloads", sharding.split_signing_seed, seed),
    ):
        args[field] = list(
            reversed(
                split(
                    secret,
                    threshold=2,
                    shares=3,
                    doc_hash=b"h" * 32,
                    sign_priv=seed,
                    sign_pub=public_key,
                )
            )
        )
    if not include_index:
        args["kit_index_inputs"] = None

    with events.event_session(sequence.sink):
        passphrase_paths, signing_paths = execution._render_all_documents(**args)

    documents = [args["qr_inputs"], args["recovery_inputs"]]
    if include_index:
        documents.append(args["kit_index_inputs"])
    assert [call.args[0] for call in sequence.renderer.call_args_list] == documents
    assert [call.kwargs["inputs"] for call in sequence.validator.call_args_list] == documents
    if include_index:
        assert sequence.validator.call_args.kwargs["expected_text"] == ("root-123",)
    assert [call.args[0].share_index for call in sequence.shard_renderer.call_args_list] == (
        [1, 2, 3] * 2
    )
    assert passphrase_paths == [
        str(Path(args["output_dir"]) / f"passphrase-{i}.pdf") for i in (1, 2, 3)
    ]
    assert signing_paths == [
        str(Path(args["output_dir"]) / f"signing-seed-{i}.pdf") for i in (1, 2, 3)
    ]
    progress = _document_progress(sequence.sink)
    total = len(documents) + 6
    assert [event["current"] for event in progress] == list(range(total + 1))
    assert all(event["total"] == total and event["unit"] == "documents" for event in progress)
    assert [event["details"]["kind"] for event in progress[1:]] == (
        ["qr_document", "recovery_document"]
        + (["recovery_kit_index"] if include_index else [])
        + ["shard_document"] * 3
        + ["signing_key_shard_document"] * 3
    )
    assert [event["details"]["path"] for event in progress[1:]] == (
        [str(document.output_path) for document in documents] + passphrase_paths + signing_paths
    )


def test_failed_validation_stops_rendering_before_reporting_completion(render_sequence) -> None:
    sequence = render_sequence
    sequence.validator.side_effect = [None, RenderValidationError("invalid recovery document")]
    with events.event_session(sequence.sink), pytest.raises(RenderValidationError):
        execution._render_all_documents(**sequence.args)
    assert sequence.renderer.call_count == 2
    sequence.shard_renderer.assert_not_called()
    assert [event["current"] for event in _document_progress(sequence.sink)] == [0, 1]


def test_pending_cancellation_stops_before_rendering(render_sequence) -> None:
    sequence = render_sequence
    control = ExecutionControl()
    assert control.request_cancel()
    with (
        execution_session(control),
        events.event_session(sequence.sink),
        pytest.raises(OperationCancelled),
    ):
        execution._render_all_documents(**sequence.args)
    sequence.renderer.assert_not_called()
    sequence.shard_renderer.assert_not_called()
