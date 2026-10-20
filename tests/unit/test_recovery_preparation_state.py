from pathlib import Path
from unittest.mock import Mock

import pytest

from ethernity.tasks import recovery_inputs, source_assessment
from ethernity.tasks.add_files import AddFilesTaskState, _AssessmentCache
from ethernity.tasks.models import TaskIssue
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.source_assessment import SourceAssessment


def _save_assessment(state: RestoreTaskState) -> SourceAssessment:
    request = state.source_assessment_request()
    assert request is not None
    assessment = SourceAssessment(
        source_kind=request.source_kind,
        source_label=request.source_label,
        source_summary=request.source_summary,
        issue=TaskIssue(code="SOURCE_INVALID", message="Invalid old input", section="source"),
    )
    assert state.store_source_assessment(request, assessment)
    return assessment


@pytest.mark.parametrize("change", ["edit", "replace", "delete"])
def test_source_file_changes_invalidate_assessment(tmp_path: Path, change: str) -> None:
    path = tmp_path / "input.txt"
    path.write_text("old input")
    state = RestoreTaskState(payloads_file=path)
    assessment = _save_assessment(state)
    assert state.current_source_assessment() is assessment
    if change == "edit":
        path.write_text("new input")
    elif change == "replace":
        replacement = tmp_path / "replacement.txt"
        replacement.write_text("new input")
        replacement.replace(path)
    else:
        path.unlink()
    assert state.current_source_assessment() is None
    assert all(issue.code != "SOURCE_INVALID" for issue in state.validate_task().issues)


def test_directory_membership_invalidates_assessment(tmp_path: Path) -> None:
    state = RestoreTaskState(source_paths=[tmp_path])
    _save_assessment(state)
    (tmp_path / "another.pdf").write_bytes(b"new document")
    assert state.current_source_assessment() is None


def test_assessment_cannot_publish_after_source_changes_during_read(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("old input")
    state = RestoreTaskState(payloads_file=path)
    old_request = state.source_assessment_request()
    assert old_request is not None
    old_result = _save_assessment(state)
    path.write_text("new input")
    assert not state.store_source_assessment(old_request, old_result)


def test_pasted_text_is_parsed_once_across_display_validation_and_execution(monkeypatch) -> None:
    parse = Mock(wraps=recovery_inputs.frames_from_fallback_text)
    monkeypatch.setattr(recovery_inputs, "frames_from_fallback_text", parse)
    state = RestoreTaskState(recovery_text="invalid recovery text")
    state.sections()
    state.validate_task()
    state.sections()
    with pytest.raises(ValueError):
        state.to_recovery_request()
    assert parse.call_count == 1
    state.recovery_text = "different invalid text"
    state.validate_task()
    assert parse.call_count == 2
    state.allow_unsigned = True
    state.validate_task()
    assert parse.call_count == 3


def test_review_config_copy_keeps_assessment_but_changed_config_invalidates_it(tmp_path) -> None:
    original = tmp_path / "config.toml"
    snapshot = tmp_path / "reviewed.toml"
    original.write_text("same configuration")
    snapshot.write_bytes(original.read_bytes())
    state = RestoreTaskState(source_paths=[tmp_path / "input.pdf"], config_path=original)
    assessment = _save_assessment(state)
    state.config_path = snapshot
    assert state.current_source_assessment() is assessment
    snapshot.write_text("changed configuration")
    assert state.current_source_assessment() is None


@pytest.mark.parametrize(
    "state_type",
    [
        RestoreTaskState,
        AddFilesTaskState,
        RebuildTaskState,
        ReplaceRecoveryDocsTaskState,
    ],
)
def test_presentation_reuses_source_revision_until_the_next_view(tmp_path, monkeypatch, state_type):
    source = tmp_path / "source"
    source.mkdir()
    for index in range(30):
        (source / f"page-{index}.pdf").write_bytes(b"source")
    config = tmp_path / "config.toml"
    config.write_text("config")
    state = state_type(source_paths=[source], config_path=config)
    assessment = _save_assessment(state)
    revision = Mock(wraps=source_assessment.source_files_version)
    monkeypatch.setattr(source_assessment, "source_files_version", revision)
    read = Mock(wraps=Path.read_bytes)
    monkeypatch.setattr(Path, "read_bytes", lambda path: read(path))

    with state.presentation_snapshot():
        for _ in range(3):
            assert state.current_source_assessment() is assessment
            state.sections()
            state.validate_task()
            state.preview()
    assert revision.call_count == read.call_count == 1

    (source / "new-page.pdf").write_bytes(b"changed")
    with state.presentation_snapshot():
        assert state.current_source_assessment() is None
    assert revision.call_count == read.call_count == 2


def test_presentation_scope_cleans_up_after_nested_failure(tmp_path):
    source = tmp_path / "payload.txt"
    source.write_text("old")
    state = RestoreTaskState(payloads_file=source)
    assessment = _save_assessment(state)
    with pytest.raises(RuntimeError, match="failed view"):
        with state.presentation_snapshot(), state.presentation_snapshot():
            assert state.current_source_assessment() is assessment
            raise RuntimeError("failed view")
    source.write_text("new")
    assert state.current_source_assessment() is None


@pytest.mark.parametrize("change", ["config", "destination"])
def test_add_files_display_reuses_review_key_without_retaining_stale_results(
    tmp_path, monkeypatch, change
):
    config = tmp_path / "config.toml"
    config.write_text("old")
    state = AddFilesTaskState(source_paths=[tmp_path / "backup.pdf"], config_path=config)
    cached = _AssessmentCache(
        state._assessment_key(),
        issue=TaskIssue(
            code="REVIEW_FAILED",
            message="Old review",
            section="source",
        ),
    )
    state._assessment_cache = cached
    read = Mock(wraps=Path.read_bytes)
    monkeypatch.setattr(Path, "read_bytes", lambda path: read(path))
    with state.presentation_snapshot():
        state.validate_task()
        state.preview()
        assert state._current_assessment_cache() is cached
    assert read.call_count == 1
    if change == "config":
        config.write_text("new")
    else:
        state.output_dir = tmp_path / "new-output"
    with state.presentation_snapshot():
        assert state._current_assessment_cache() is None
    assert read.call_count == 2


def test_presentation_snapshot_cannot_authorize_a_stale_completion(tmp_path):
    source = tmp_path / "payload.txt"
    source.write_text("old")
    state = RestoreTaskState(payloads_file=source)
    assessment = _save_assessment(state)
    with state.presentation_snapshot():
        request = state.source_assessment_request()
        assert request is not None
        source.write_text("changed")
        assert not state.store_source_assessment(request, assessment)
    assert state.current_source_assessment() is None
