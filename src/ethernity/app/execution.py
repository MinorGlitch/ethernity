from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from textual.worker import WorkerState

from ethernity.config import get_config_snapshot, resolve_config_snapshot_path
from ethernity.core.failures import FailureStage
from ethernity.tasks.models import (
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskPreview,
    TaskValidation,
    TaskValidationError,
)
from ethernity.tasks.presentation.models import ReviewDetail
from ethernity.tasks.presentation.registry import build_review_details
from ethernity.tasks.task_types import TaskKey, TaskState
from ethernity.workflows.shared.failures import failure_from_exception


@dataclass(frozen=True, slots=True)
class ReviewedConfig:
    """Exact validated config contents approved during final review."""

    source_path: Path
    contents: bytes = field(repr=False)

    @classmethod
    def capture(cls, path: Path | None) -> ReviewedConfig:
        source_path = resolve_config_snapshot_path(path)
        contents = source_path.read_bytes()
        with _temporary_config(
            contents,
            prefix="ethernity-config-validation-",
        ) as validation_path:
            snapshot = get_config_snapshot(validation_path)
            if snapshot.status != "valid":
                raise ValueError(f"Ethernity could not load the configuration ({snapshot.status}).")
        return cls(source_path=source_path, contents=contents)

    @contextmanager
    def temporary_path(self) -> Iterator[Path]:
        """Expose the captured bytes at a private path for path-based task APIs."""

        with _temporary_config(
            self.contents,
            prefix="ethernity-reviewed-config-",
        ) as config_path:
            yield config_path


@dataclass(frozen=True, slots=True)
class ReviewedTask:
    """The exact task state and plan approved for one execution attempt."""

    task: TaskKey
    state_snapshot: TaskState = field(repr=False)
    validation: TaskValidation = field(repr=False)
    preview: TaskPreview = field(repr=False)
    plan: TaskExecutionPlan = field(repr=False)
    review_details: tuple[ReviewDetail, ...] = field(repr=False)
    reviewed_config: ReviewedConfig = field(repr=False)

    @classmethod
    def capture(cls, task: TaskKey, state: TaskState) -> ReviewedTask:
        snapshot = state.model_copy(deep=True)
        reviewed_config = ReviewedConfig.capture(snapshot.config_path)
        with reviewed_config.temporary_path() as config_path:
            snapshot.config_path = config_path
            prepare_review = getattr(snapshot, "prepare_review", None)
            if callable(prepare_review):
                prepare_review()
            validation = snapshot.validate_task()
            preview = snapshot.preview()
            plan = snapshot.execution_plan()
        snapshot.config_path = reviewed_config.source_path
        review_details = build_review_details(task, snapshot, plan)
        return cls(
            task=task,
            state_snapshot=snapshot,
            validation=validation,
            preview=preview,
            plan=plan,
            review_details=review_details,
            reviewed_config=reviewed_config,
        )

    def execution_state(self) -> TaskState:
        """Return an isolated copy so retries preserve the reviewed snapshot."""

        return self.state_snapshot.model_copy(deep=True)

    def execute(self) -> TaskExecutionResult:
        """Execute with the reviewed state and config, never their live counterparts."""

        state = self.execution_state()
        with self.reviewed_config.temporary_path() as config_path:
            state.config_path = config_path
            return state.execute()


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """A worker terminal state normalized for result presentation."""

    result: TaskExecutionResult
    error_message: str | None = None
    error_detail: str | None = None
    allow_retry: bool = True
    failed_stage: str | None = None
    output_note: str | None = None
    failure_section: str | None = None


def execution_failure_section(task: TaskKey, outcome: ExecutionOutcome) -> str | None:
    """Map typed failure provenance to the corresponding task editor."""

    if outcome.failure_section is not None:
        return outcome.failure_section
    failure = outcome.result.failure
    if failure is None:
        return None
    if failure.stage == FailureStage.OUTPUT:
        return "output"
    if failure.stage == FailureStage.LAYOUT:
        return "layout"
    if failure.stage in {FailureStage.INPUT, FailureStage.SOURCE}:
        return "files" if task in {"backup", "add_files"} else "source"
    if failure.stage == FailureStage.UNLOCK:
        return "advanced" if task == "backup" else "unlock"
    if failure.stage == FailureStage.AUTHENTICATION:
        return {
            "restore": "authentication",
            "backup": "signature",
            "replace_recovery_docs": "signature",
        }.get(task, "source")
    if failure.stage == FailureStage.SELECTION:
        return "target" if task == "restore" else "freshness"
    if failure.stage == FailureStage.RECOVERY:
        return "recovery"
    return None


def normalize_execution_outcome(
    state: WorkerState,
    *,
    value: object = None,
    error: BaseException | None = None,
    phase: str | None = None,
) -> ExecutionOutcome:
    """Convert every worker terminal state into one result-screen value."""

    if state == WorkerState.SUCCESS:
        if isinstance(value, TaskExecutionResult):
            return ExecutionOutcome(result=value)
        actual_type = type(value).__qualname__
        return ExecutionOutcome(
            result=TaskExecutionResult(
                status="failed",
                message="Ethernity received an invalid task result.",
            ),
            error_detail=f"Expected TaskExecutionResult, got {actual_type}.",
        )

    if state == WorkerState.ERROR:
        if error is None:
            return ExecutionOutcome(
                result=TaskExecutionResult(status="failed", message="The task failed."),
                error_message="The task stopped without an error message.",
                error_detail="The execution worker exited without an exception.",
            )
        message = str(error).strip() or "The task failed without an error message."
        return ExecutionOutcome(
            result=TaskExecutionResult(
                status="failed",
                message="The task failed.",
                failure=failure_from_exception(error, phase=phase),
            ),
            failure_section=error.section if isinstance(error, TaskValidationError) else None,
            error_message=message,
            error_detail=f"{type(error).__qualname__}: {error}",
        )

    if state == WorkerState.CANCELLED:
        return ExecutionOutcome(
            result=TaskExecutionResult(
                status="failed",
                message="The write was cancelled before completion.",
            ),
            error_detail=(
                "The write thread has stopped. Check the destination before starting another write."
            ),
            allow_retry=False,
        )

    raise ValueError(f"Worker state {state!s} is not terminal.")


@contextmanager
def _temporary_config(contents: bytes, *, prefix: str) -> Iterator[Path]:
    with TemporaryDirectory(prefix=prefix) as directory:
        config_path = Path(directory) / "config.toml"
        config_path.write_bytes(contents)
        yield config_path
