"""Expected task failures become command errors without hiding programming defects."""

import errno

import pytest
from click.testing import CliRunner

from ethernity.crypto.age_runtime import AgeError
from ethernity.qr.scan import QrScanError
from ethernity.run.cli import cli
from ethernity.security.resource_worker import DisposableWorkerError
from ethernity.tasks.backup import BackupTaskState
from ethernity.workflows.add_files.errors import AddFilesWorkflowError
from ethernity.workflows.execution import WorkflowExecutionError
from ethernity.workflows.shared.execution_control import OperationCancelled


@pytest.fixture
def failing_backup(monkeypatch):
    def invoke(method, error, mode="--yes"):
        def fail(_self, **_kwargs):
            raise error

        monkeypatch.setattr(BackupTaskState, method, fail, raising=False)
        return CliRunner().invoke(cli, ["backup", "--input", "secret.txt", mode])

    return invoke


@pytest.mark.parametrize(
    "error",
    [
        ValueError("Invalid task input."),
        FileNotFoundError(errno.ENOENT, "input file not found", "missing.txt"),
        PermissionError("Cannot read the selected file."),
        OSError("Cannot write the destination."),
        WorkflowExecutionError(code="SOURCE_INVALID", message="Invalid source."),
        AddFilesWorkflowError(code="UPDATE_INVALID", message="Invalid update."),
        AgeError(backend="test", detail="Encryption backend failed."),
        QrScanError("Cannot scan the selected PDF."),
        DisposableWorkerError("Recovery worker exceeded its limit."),
    ],
)
@pytest.mark.parametrize(
    ("method", "mode"),
    [
        ("prepare_review", "--preview"),
        ("prepare_review", "--yes"),
        ("validate_task", "--preview"),
        ("validate_task", "--yes"),
        ("preview", "--preview"),
        ("preview", "--yes"),
        ("execute", "--yes"),
    ],
)
def test_expected_task_failures_use_command_error(failing_backup, method, mode, error) -> None:
    result = failing_backup(method, error, mode)

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert f"Error: {error}" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("option", ["--input", "--input-dir"])
def test_real_missing_input_reports_its_path_without_writing(tmp_path, option) -> None:
    missing = tmp_path / "missing [input]"
    output = tmp_path / "output"
    result = CliRunner().invoke(
        cli, ["backup", option, str(missing), "--output-dir", str(output), "--yes"]
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "Error:" in result.output
    assert "not found" in result.output
    assert str(missing) in result.output
    assert "Traceback" not in result.output
    assert not output.exists()


@pytest.mark.parametrize("method", ["prepare_review", "validate_task", "preview", "execute"])
@pytest.mark.parametrize(
    "error",
    [
        TypeError("Invalid internal argument."),
        AssertionError("Broken invariant."),
        KeyError("missing_internal_field"),
        RuntimeError("Unexpected internal state."),
        KeyboardInterrupt(),
    ],
)
def test_unexpected_errors_and_interrupts_are_not_command_failures(
    failing_backup, method, error
) -> None:
    result = failing_backup(method, error)

    assert result.exit_code != 0
    if isinstance(error, KeyboardInterrupt):
        assert "Aborted!" in result.output
    else:
        assert result.exception is error
    assert "Error:" not in result.output


def test_cooperative_cancellation_propagates_unchanged(failing_backup) -> None:
    error = OperationCancelled()
    with pytest.raises(OperationCancelled) as raised:
        failing_backup("execute", error)
    assert raised.value is error
