"""Replacement review and execution require the same unused destination."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from ethernity.run.cli import cli
from ethernity.tasks.models import TaskValidationError
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.workflows.replacement_recovery import service


def _state(output: Path | None) -> ReplaceRecoveryDocsTaskState:
    return ReplaceRecoveryDocsTaskState(
        source_paths=[Path("scan.pdf")],
        passphrase="secret",
        allow_stale_head=True,
        output_dir=output,
    )


@pytest.mark.parametrize("kind", ["empty", "populated", "file", "symlink", "dangling"])
def test_existing_destination_blocks_review_and_execution(tmp_path, kind, monkeypatch) -> None:
    output = tmp_path / "replacement"
    if kind in {"empty", "populated"}:
        output.mkdir()
        if kind == "populated":
            (output / "keep.txt").write_text("original")
    elif kind == "file":
        output.write_text("original")
    else:
        target = tmp_path / "target"
        if kind == "symlink":
            target.mkdir()
        try:
            output.symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip("Symlink creation unavailable")

    state = _state(output)
    validation = state.validate_task()
    (issue,) = validation.issues
    section = next(section for section in validation.sections if section.key == "output")

    assert not validation.ready
    assert issue.code == "REPLACE_RECOVERY_OUTPUT_EXISTS"
    assert issue.severity == "error"
    assert issue.section == "output"
    assert section.status == "blocked"
    assert section.detail == issue.message
    assert "choose a new folder" in issue.message
    assert not any(warning.section == "output" for warning in state.preview().warnings)
    assert not any("may be replaced" in warning.message for warning in state.preview().warnings)

    with pytest.raises(ValueError) as workflow_error:
        service.require_replacement_recovery_output_available(output)
    assert str(workflow_error.value) == issue.message

    monkeypatch.setattr(
        "ethernity.tasks.replace_recovery_docs.execute_replacement_recovery",
        lambda _request: pytest.fail("Blocked destination reached the workflow"),
    )
    with pytest.raises(TaskValidationError) as task_error:
        state.execute()
    assert task_error.value.code == issue.code
    assert task_error.value.section == "output"
    if kind == "populated":
        assert (output / "keep.txt").read_text() == "original"
    elif kind == "file":
        assert output.read_text() == "original"


def test_unused_destination_is_ready_without_creating_directories(tmp_path) -> None:
    output = tmp_path / "new-parent" / "replacement"
    state = _state(output)
    validation = state.validate_task()

    assert validation.ready
    assert (
        next(section for section in validation.sections if section.key == "output").status
        == "ready"
    )
    assert service.require_replacement_recovery_output_available(output) == output
    assert not output.parent.exists()
    output.parent.mkdir()
    output.mkdir()
    assert not state.validate_task().ready


def test_home_relative_destination_uses_workflow_normalization(tmp_path, set_home) -> None:
    set_home(tmp_path)
    output = tmp_path / "replacement"
    output.mkdir()

    assert (
        _state(Path("~/replacement")).validate_task().issues[0].code
        == "REPLACE_RECOVERY_OUTPUT_EXISTS"
    )


def test_missing_destination_remains_missing() -> None:
    validation = _state(None).validate_task()
    assert validation.issues[0].code == "REPLACE_RECOVERY_OUTPUT_REQUIRED"
    assert (
        next(section for section in validation.sections if section.key == "output").status
        == "missing"
    )


def test_explicit_parent_mode_still_creates_a_named_child(tmp_path) -> None:
    output = service._ensure_replacement_output_dir(
        tmp_path, "deadbeef", existing_directory_is_parent=True
    )
    assert Path(output) == tmp_path / "replacement-recovery-deadbeef"
    assert not Path(output).exists()


@pytest.mark.parametrize("mode", ["--preview", "--yes"])
def test_command_reports_conflict_before_execution(tmp_path, monkeypatch, mode) -> None:
    output = tmp_path / "replacement"
    output.mkdir()
    (output / "keep.txt").write_text("original")
    monkeypatch.setattr(
        ReplaceRecoveryDocsTaskState,
        "execute",
        lambda _state: pytest.fail("Blocked command reached execution"),
    )
    result = CliRunner().invoke(
        cli,
        [
            "replace-recovery-docs",
            "--scan",
            "scan.pdf",
            "--passphrase",
            "secret",
            "--allow-stale-head",
            "--output-dir",
            str(output),
            mode,
        ],
    )

    assert result.exit_code == (0 if mode == "--preview" else 1)
    message = " ".join(result.output.split())
    assert "choose a new folder" in message
    assert "may be replaced" not in message
    assert (output / "keep.txt").read_text() == "original"
