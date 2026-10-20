from pathlib import Path
from unittest.mock import Mock

import pytest

from ethernity.tasks import recovery_inputs
from ethernity.tasks.models import TaskIssue
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
