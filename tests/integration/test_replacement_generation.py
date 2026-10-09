"""Replacement rendering reports validated work and publishes complete output only."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from ethernity.config import AppConfig, BackupDefaults, CliDefaults
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.signing import AuthPayload, derive_public_key
from ethernity.extensions.recovery import ChainRecoveryResult, ValidatedRecoveryHead
from ethernity.formats.manifest import BackupManifest
from ethernity.qr.codec import QrConfig
from ethernity.render.checks import RenderValidationError
from ethernity.render.types import RenderInputs, RenderResult
from ethernity.workflows.recovery.planning import RecoveryPlan
from ethernity.workflows.recovery.source_state import recovery_source_fields
from ethernity.workflows.replacement_recovery import service
from ethernity.workflows.shared import events, shard_rendering
from ethernity.workflows.shared.execution_control import (
    ExecutionControl,
    OperationCancelled,
    execution_session,
)
from ethernity.workflows.shared.operation_types import ReplacementRecoveryOperationResult
from ethernity.workflows.shared.requests import ReplacementRecoveryRequest


@dataclass
class ReplacementRun:
    plan: RecoveryPlan
    chain: ChainRecoveryResult
    config: AppConfig
    request: ReplacementRecoveryRequest
    rendered: list[RenderInputs]
    validator: Mock
    sink: Mock
    parent: Path

    def execute(self) -> ReplacementRecoveryOperationResult:
        with events.event_session(self.sink):
            return service._replacement_from_plan(
                plan=self.plan,
                config=self.config,
                args=self.request,
                passphrase_shard_frames=[],
                signing_key_frames=[],
                debug=False,
            )

    def progress(self) -> list[dict]:
        return [
            call.kwargs
            for call in self.sink.emit.call_args_list
            if call.args == ("progress",) and call.kwargs["phase"] == "render"
        ]


@pytest.fixture
def replacement_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ReplacementRun:
    seed = b"s" * 32
    ciphertext = b"authenticated root ciphertext"
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    auth = AuthPayload(
        version=1, doc_hash=doc_hash, sign_pub=derive_public_key(seed), signature=b"a" * 64
    )
    plan = RecoveryPlan(
        source=recovery_source_fields(None, None, (), ()),
        ciphertext=ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
        auth_payload=auth,
        auth_status="verified",
        allow_unsigned=False,
        passphrase="test replacement passphrase",
        output_path=None,
    )
    chain = ChainRecoveryResult(
        manifest=BackupManifest(created_at=0, signing_seed=seed, files=()),
        extracted=(),
        head=ValidatedRecoveryHead(
            doc_id=b"e" * 8,
            doc_hash=b"e" * 32,
            ciphertext=b"selected extension ciphertext",
            auth_payload=None,
            auth_status="verified",
            extension_index=2,
        ),
        validated_chain=None,
    )
    parent = tmp_path / "outputs"
    parent.mkdir()
    (parent / "keep.txt").write_text("unrelated output")
    run = ReplacementRun(
        plan=plan,
        chain=chain,
        config=AppConfig(
            design_name="sentinel",
            paper_size="A4",
            qr_config=QrConfig(),
            qr_chunk_size=1024,
            cli_defaults=CliDefaults(backup=BackupDefaults(qr_payload_codec="base64")),
        ),
        request=ReplacementRecoveryRequest(
            output_dir=parent / "replacement",
            layout_debug_dir=tmp_path / "layout",
            shard_threshold=2,
            shard_count=3,
            signing_key_shard_threshold=1,
            signing_key_shard_count=2,
        ),
        rendered=[],
        validator=Mock(),
        sink=Mock(spec=events.EventSink),
        parent=parent,
    )

    def render(inputs: RenderInputs) -> RenderResult:
        run.rendered.append(inputs)
        Path(inputs.output_path).write_bytes(b"rendered document")
        return RenderResult()

    monkeypatch.setattr(service, "_recover_replacement_chain", lambda *_args, **_kwargs: run.chain)
    monkeypatch.setattr(shard_rendering.render_module, "render_frames_to_pdf", render)
    monkeypatch.setattr(shard_rendering, "validate_rendered_pdf_document", run.validator)
    return run


def _assert_unpublished(run: ReplacementRun) -> None:
    assert list(run.parent.iterdir()) == [run.parent / "keep.txt"]
    assert (run.parent / "keep.txt").read_text() == "unrelated output"


@pytest.mark.parametrize("passphrase,signing", [(True, True), (True, False), (False, True)])
def test_replacement_publishes_both_or_either_document_group(
    replacement_run: ReplacementRun, passphrase: bool, signing: bool
) -> None:
    run = replacement_run
    run.request = replace(
        run.request, create_passphrase_shards=passphrase, create_signing_key_shards=signing
    )
    result = run.execute()
    paths = result.shard_paths + result.signing_key_shard_paths
    total = (3 if passphrase else 0) + (2 if signing else 0)
    assert len(paths) == total
    assert all(Path(path).parent == run.parent / "replacement" for path in paths)
    assert all(Path(path).read_bytes() == b"rendered document" for path in paths)
    assert not list(run.parent.glob(".staging-*"))
    assert result.doc_id == run.plan.doc_id
    assert result.doc_hash == run.plan.doc_hash
    assert result.selected_extension_index == 2
    assert result.selected_extension_doc_hash == (b"e" * 32).hex()
    assert result.signing_key_source == "embedded signing seed"
    assert run.validator.call_count == total
    assert all(inputs.frames[0].doc_id == run.plan.doc_id for inputs in run.rendered)
    assert all(inputs.origin.kind == "replacement_recovery" for inputs in run.rendered)
    assert all(inputs.layout_debug_json_path is not None for inputs in run.rendered)
    progress = run.progress()
    assert [event["current"] for event in progress] == list(range(1, total + 1))
    assert all(event["total"] == total and event["unit"] == "documents" for event in progress)
    assert [event["label"] for event in progress] == (
        ([f"Rendered passphrase shard {i} of 3" for i in (1, 2, 3)] if passphrase else [])
        + ([f"Rendered signing-key shard {i} of 2" for i in (1, 2)] if signing else [])
    )


@pytest.mark.parametrize("failure_index", [1, 4])
def test_validation_failure_discards_all_staged_documents(
    replacement_run: ReplacementRun, failure_index: int
) -> None:
    run = replacement_run
    error = RenderValidationError("invalid replacement document")
    run.validator.side_effect = [None] * (failure_index - 1) + [error]
    with pytest.raises(RenderValidationError) as caught:
        run.execute()
    assert caught.value is error
    assert len(run.rendered) == failure_index
    assert len(run.progress()) == failure_index - 1
    _assert_unpublished(run)


@pytest.mark.parametrize("cancel_index", [1, 4])
def test_cancellation_between_documents_discards_all_staged_output(
    replacement_run: ReplacementRun, cancel_index: int
) -> None:
    run = replacement_run
    control = ExecutionControl()

    def cancel_after_validation(**_kwargs: object) -> None:
        if len(run.rendered) == cancel_index:
            assert control.request_cancel()

    run.validator.side_effect = cancel_after_validation
    with execution_session(control), pytest.raises(OperationCancelled):
        run.execute()
    assert len(run.rendered) == cancel_index
    assert len(run.progress()) == cancel_index - 1
    _assert_unpublished(run)


def test_publication_failure_discards_staging(
    replacement_run: ReplacementRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = replacement_run
    error = OSError("publication failed")
    monkeypatch.setattr(service, "commit_prepared_output_dir", Mock(side_effect=error))
    with pytest.raises(OSError) as caught:
        run.execute()
    assert caught.value is error
    assert len(run.rendered) == 5
    _assert_unpublished(run)


def test_replacement_rejects_manifest_seed_that_does_not_match_root_auth(
    replacement_run: ReplacementRun,
) -> None:
    run = replacement_run
    run.chain = replace(run.chain, manifest=replace(run.chain.manifest, signing_seed=b"x" * 32))
    with pytest.raises(ValueError, match="signing key does not match the authenticated backup"):
        run.execute()
    assert not run.rendered
    _assert_unpublished(run)


def test_sealed_manifest_requires_signing_key_shards(replacement_run: ReplacementRun) -> None:
    run = replacement_run
    run.chain = replace(run.chain, manifest=replace(run.chain.manifest, signing_seed=None))
    with pytest.raises(events.CommandError) as caught:
        run.execute()
    assert caught.value.code == "SIGNING_KEY_SHARDS_REQUIRED"
    assert not run.rendered
    _assert_unpublished(run)
