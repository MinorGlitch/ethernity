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

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

from ethernity import publication
from ethernity.config import AppConfig
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.extensions.build import VerifiedExtensionCandidate
from ethernity.extensions.chain import ValidatedChainState
from ethernity.workflows.add_files import execution
from ethernity.workflows.add_files.errors import AddFilesWorkflowError
from ethernity.workflows.add_files.models import (
    EncryptedExtension,
    ExtensionOutputSettings,
    ExtensionPublication,
    ExtensionRenderResult,
    PreparedAddFilesRun,
)
from ethernity.workflows.add_files.planning import (
    AppendParent,
    AppendSigningKey,
    ResolvedAddFilesPlan,
)
from ethernity.workflows.add_files.reporting import EventAddFilesReporter
from ethernity.workflows.add_files.request import AddFilesRequest
from ethernity.workflows.shared import events, issue_codes
from ethernity.workflows.shared.execution_control import (
    ExecutionControl,
    OperationCancelled,
    execution_session,
)
from ethernity.workflows.shared.input_scope import InputScopeDiff, SelectedInputScope


@pytest.fixture(autouse=True)
def valid_rebuild_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep publication tests focused on their prevalidated reviewed payload."""

    monkeypatch.setattr(execution, "require_rebuildable_result", lambda *_args: 100)


@pytest.fixture
def assessed(tmp_path: Path) -> execution.AssessedAddFilesRun:
    source = tmp_path / "carrier.pdf"
    source.write_bytes(b"already assessed document")
    request = AddFilesRequest(
        scan_paths=(str(source),),
        output_dir=str(tmp_path / "chosen-output"),
        input_paths=(str(tmp_path / "file.txt"),),
    )
    prepared = PreparedAddFilesRun(
        request=request,
        plan=ResolvedAddFilesPlan(
            diff=InputScopeDiff(
                new_paths=("file.txt",), changed_paths=(), unchanged_paths=(), missing_paths=()
            ),
            parent=AppendParent(root_doc_hash=b"r" * 32, head_doc_hash=b"h" * 32, head_index=2),
            signing_key=AppendSigningKey(signing_seed=b"s" * 32),
        ),
        selected_input=mock.Mock(spec=SelectedInputScope),
        validated_chain=mock.Mock(spec=ValidatedChainState),
        chain_document_count=3,
        chain_ciphertext_bytes=100,
        chain_decoded_chunk_bytes=10,
        encryption_passphrase="secret",
    )
    ciphertext = b"exact reviewed ciphertext"
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    encrypted = EncryptedExtension(
        built=mock.Mock(spec=VerifiedExtensionCandidate),
        plaintext=b"reviewed plaintext",
        ciphertext=ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
    )
    output_settings = ExtensionOutputSettings(
        config=mock.Mock(spec=AppConfig),
        qr_chunk_size=10,
        qr_payload_codec="raw",
        layout_debug_dir=None,
        sign_pub=b"p" * 32,
    )
    return execution.AssessedAddFilesRun(
        prepared=prepared, encrypted=encrypted, output_settings=output_settings
    )


@pytest.fixture
def render_stub(monkeypatch: pytest.MonkeyPatch) -> list[ExtensionPublication]:
    plans: list[ExtensionPublication] = []

    def render(plan: ExtensionPublication, **_kwargs: object) -> ExtensionRenderResult:
        plans.append(plan)
        for path in (
            plan.paths.qr_document_path,
            plan.paths.recovery_document_path,
        ):
            path.write_bytes(plan.encrypted.ciphertext)
        output_settings = _kwargs["output_settings"]
        if output_settings.layout_debug_dir is not None:
            (Path(output_settings.layout_debug_dir) / "carrier.layout.json").write_text(
                "{}", encoding="utf-8"
            )
        return ExtensionRenderResult(
            recovery_document_fallback_frames=(
                Frame(
                    VERSION,
                    FrameType.MAIN_DOCUMENT,
                    plan.encrypted.doc_id,
                    0,
                    1,
                    plan.encrypted.ciphertext,
                ),
            )
        )

    monkeypatch.setattr(execution.add_files_rendering, "render_extension_documents", render)
    monkeypatch.setattr(execution, "validate_staged_extension_documents", lambda *_args: None)
    return plans


def test_execute_publishes_assessed_payload_after_source_is_removed(
    assessed: execution.AssessedAddFilesRun,
    render_stub: list[ExtensionPublication],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    Path(assessed.prepared.request.scan_paths[0]).unlink()
    monkeypatch.setattr(
        execution,
        "encrypt_prepared_extension_document",
        lambda *_args: pytest.fail("execution must retain the assessed ciphertext"),
    )
    executed = execution.execute_assessed_add_files(assessed)
    assert executed.result.final_dir == tmp_path / "chosen-output"
    assert render_stub[0].encrypted is assessed.encrypted
    assert executed.result.qr_document_path.read_bytes() == assessed.encrypted.ciphertext
    assert sorted(path.name for path in tmp_path.iterdir()) == ["chosen-output"]
    assert executed.result.parent_head_doc_hash == (b"h" * 32).hex()
    assert executed.result.recovery_frames[0].data == assessed.encrypted.ciphertext


@pytest.mark.parametrize("phase", ["validate", "save"])
def test_update_cancellation_respects_publication_boundary(
    assessed: execution.AssessedAddFilesRun,
    render_stub: list[ExtensionPublication],
    tmp_path: Path,
    phase: str,
) -> None:
    control = ExecutionControl()
    accepted = []

    class CancelAtPhase:
        def emit(self, event_type, **payload):
            if event_type == "phase" and payload.get("id") == phase:
                accepted.append(control.request_cancel())

    with execution_session(control), events.event_session(CancelAtPhase()):
        if phase == "save":
            result = execution.execute_assessed_add_files(
                assessed, reporter=EventAddFilesReporter()
            )
            assert result.result.qr_document_path.is_file()
            assert accepted == [False]
        else:
            with pytest.raises(OperationCancelled):
                execution.execute_assessed_add_files(assessed, reporter=EventAddFilesReporter())
            assert accepted == [True]
            assert sorted(path.name for path in tmp_path.iterdir()) == ["carrier.pdf"]
    assert not render_stub[0].paths.staging_dir.exists()


def test_execute_refuses_output_created_after_assessment(
    assessed: execution.AssessedAddFilesRun,
    render_stub: list[ExtensionPublication],
    tmp_path: Path,
) -> None:
    output = tmp_path / "chosen-output"
    output.mkdir()
    user_file = output / "user.txt"
    user_file.write_bytes(b"keep this")
    with pytest.raises(AddFilesWorkflowError) as caught:
        execution.execute_assessed_add_files(assessed)
    assert caught.value.code == issue_codes.EXTENSION_PUBLISH_TARGET_INVALID
    assert render_stub == []
    assert user_file.read_bytes() == b"keep this"


def test_execute_rechecks_rebuild_capacity_before_rendering_or_creating_output(
    assessed: execution.AssessedAddFilesRun,
    render_stub: list[ExtensionPublication],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def reject_capacity(*_args: object) -> None:
        raise AddFilesWorkflowError(
            code=issue_codes.ADD_FILES_NOT_REBUILDABLE,
            message="updated state exceeds standalone capacity",
        )

    monkeypatch.setattr(execution, "require_rebuildable_result", reject_capacity)
    with pytest.raises(AddFilesWorkflowError) as caught:
        execution.execute_assessed_add_files(assessed)
    assert caught.value.code == issue_codes.ADD_FILES_NOT_REBUILDABLE
    assert render_stub == []
    assert sorted(path.name for path in tmp_path.iterdir()) == ["carrier.pdf"]


def test_destination_collision_during_render_preserves_competing_output(
    assessed: execution.AssessedAddFilesRun,
    render_stub: list[ExtensionPublication],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "chosen-output"

    def create_competing_output(*_args: object, **_kwargs: object) -> None:
        output.mkdir()
        (output / "user.txt").write_bytes(b"another publication")

    monkeypatch.setattr(execution, "validate_staged_extension_documents", create_competing_output)
    with pytest.raises(ValueError, match="final directory already exists"):
        execution.execute_assessed_add_files(assessed)
    assert (output / "user.txt").read_bytes() == b"another publication"
    assert not render_stub[0].paths.staging_dir.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["carrier.pdf", "chosen-output"]


def test_publication_rejects_carrier_change_after_validation_snapshot(
    assessed: execution.AssessedAddFilesRun,
    render_stub: list[ExtensionPublication],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def change_carrier(plan: ExtensionPublication, _rendered: ExtensionRenderResult) -> None:
        plan.paths.qr_document_path.write_bytes(b"changed after snapshot")

    monkeypatch.setattr(execution, "validate_staged_extension_documents", change_carrier)
    with pytest.raises(ValueError, match="staged files changed before promotion"):
        execution.execute_assessed_add_files(assessed)
    assert not (tmp_path / "chosen-output").exists()
    assert not render_stub[0].paths.staging_dir.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["carrier.pdf"]


def test_extension_publication_requires_durable_output(
    assessed: execution.AssessedAddFilesRun,
    render_stub: list[ExtensionPublication],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_sync(_fd: int) -> None:
        raise OSError("sync unavailable")

    monkeypatch.setattr(publication.os, "fsync", fail_sync)
    with pytest.raises(OSError, match="sync unavailable"):
        execution.execute_assessed_add_files(assessed)
    assert not (tmp_path / "chosen-output").exists()
    assert not render_stub[0].paths.staging_dir.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["carrier.pdf"]


def test_assessment_does_not_create_the_destination_or_parent_directories(
    assessed: execution.AssessedAddFilesRun,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepared = replace(
        assessed.prepared,
        request=replace(
            assessed.prepared.request,
            output_dir=str(tmp_path / "new-parent" / "chosen-output"),
        ),
    )
    monkeypatch.setattr(
        execution.add_files_output_settings,
        "resolve_add_files_output_settings",
        lambda *_args, **_kwargs: assessed.output_settings,
    )
    monkeypatch.setattr(
        execution, "encrypt_prepared_extension_document", lambda *_args: assessed.encrypted
    )
    result = execution.assess_prepared_add_files(prepared)
    assert result.encrypted is assessed.encrypted
    assert sorted(path.name for path in tmp_path.iterdir()) == ["carrier.pdf"]


def test_failed_debug_sidecar_promotion_preserves_published_documents(
    assessed: execution.AssessedAddFilesRun,
    render_stub: list[ExtensionPublication],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepared = replace(
        assessed.prepared,
        request=replace(
            assessed.prepared.request,
            layout_debug_directory=str(tmp_path / "debug"),
        ),
    )

    def fail_debug_promotion(*_args: object, **_kwargs: object) -> None:
        raise OSError("diagnostic destination unavailable")

    monkeypatch.setattr(execution, "_replace_layout_debug_sidecars", fail_debug_promotion)
    reporter = mock.Mock()
    result = execution.execute_assessed_add_files(
        replace(assessed, prepared=prepared), reporter=reporter
    )
    assert result.result.qr_document_path.read_bytes() == assessed.encrypted.ciphertext
    assert not render_stub[0].paths.staging_dir.exists()
    assert list((tmp_path / "debug").iterdir()) == []
    reporter.warning.assert_called_once()
    assert "Extension published" in reporter.warning.call_args.args[0]


def test_assessment_rejects_diagnostics_inside_output_without_writing(
    assessed: execution.AssessedAddFilesRun,
    tmp_path: Path,
) -> None:
    prepared = replace(
        assessed.prepared,
        request=replace(
            assessed.prepared.request,
            layout_debug_directory=str(tmp_path / "chosen-output" / "debug"),
        ),
    )
    with pytest.raises(AddFilesWorkflowError) as caught:
        execution.assess_prepared_add_files(prepared)
    assert caught.value.code == issue_codes.ADD_FILES_RENDER_OPTIONS_INVALID
    assert sorted(path.name for path in tmp_path.iterdir()) == ["carrier.pdf"]
