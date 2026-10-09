"""Failure provenance survives wording changes and adapter boundaries."""

from __future__ import annotations

import pytest
from textual.worker import WorkerState

from ethernity.app.execution import execution_failure_section, normalize_execution_outcome
from ethernity.core.failures import FailureInfo, FailureStage
from ethernity.crypto.age_runtime import AgeError, PassphraseAuthenticationError
from ethernity.tasks.models import TaskIssue, TaskValidation, TaskValidationError
from ethernity.workflows.execution import WorkflowExecutionError
from ethernity.workflows.shared.events import CommandError
from ethernity.workflows.shared.failures import failure_from_exception


@pytest.mark.parametrize("message", ["Something failed.", "decrypt signature destination password"])
@pytest.mark.parametrize(
    ("stage", "section"),
    [
        (FailureStage.SOURCE, "source"),
        (FailureStage.OUTPUT, "output"),
        (FailureStage.UNLOCK, "unlock"),
        (FailureStage.AUTHENTICATION, "authentication"),
        (FailureStage.SELECTION, "target"),
    ],
)
def test_routing_uses_failure_stage_not_copy(
    message: str, stage: FailureStage, section: str
) -> None:
    error = WorkflowExecutionError(code="SPECIFIC_FAILURE", message=message, stage=stage)
    outcome = normalize_execution_outcome(WorkerState.ERROR, error=error)
    assert execution_failure_section("restore", outcome) == section
    assert outcome.result.failure == FailureInfo("SPECIFIC_FAILURE", stage)
    assert outcome.error_message == message


def test_unknown_error_copy_cannot_choose_an_editor() -> None:
    outcome = normalize_execution_outcome(
        WorkerState.ERROR, error=RuntimeError("destination decrypt signature passphrase")
    )
    assert execution_failure_section("restore", outcome) is None


def test_phase_is_a_machine_identifier_not_a_display_label() -> None:
    error = OSError("no location or action mentioned")
    outcome = normalize_execution_outcome(WorkerState.ERROR, error=error, phase="write")
    assert execution_failure_section("restore", outcome) == "output"
    label_only = normalize_execution_outcome(WorkerState.ERROR, error=error, phase="Writing files")
    assert execution_failure_section("restore", label_only) is None


def test_specific_failure_survives_generic_wrapper_and_phase() -> None:
    cause = PassphraseAuthenticationError(AgeError(backend="test", detail="renamed explanation"))
    wrapper = WorkflowExecutionError(code="RUNTIME_ERROR", message="worker stopped")
    wrapper.__cause__ = cause
    failure = failure_from_exception(wrapper, phase="write")
    assert failure == FailureInfo("PASSPHRASE_AUTH_FAILED", FailureStage.UNLOCK)


def test_explicit_command_stage_survives_adapter() -> None:
    error = CommandError("INVALID_INPUT", "renamed explanation", stage=FailureStage.SELECTION)
    wrapper = WorkflowExecutionError(
        code=error.code, message="adapter", details=dict(error.details)
    )
    wrapper.__cause__ = error
    assert failure_from_exception(wrapper) == FailureInfo("INVALID_INPUT", FailureStage.SELECTION)


def test_task_validation_uses_first_blocking_issue_and_retains_editor() -> None:
    validation = TaskValidation(
        sections=(),
        issues=(
            TaskIssue(code="NOTICE", message="destination", severity="warning", section="output"),
            TaskIssue(code="INVALID_POLICY", message="anything", section="signature"),
        ),
    )
    with pytest.raises(TaskValidationError) as raised:
        validation.require_ready("not ready")
    outcome = normalize_execution_outcome(WorkerState.ERROR, error=raised.value, phase="write")
    assert outcome.result.failure is not None
    assert outcome.result.failure.code == "INVALID_POLICY"
    assert execution_failure_section("backup", outcome) == "signature"
