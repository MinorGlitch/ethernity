from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from functools import partial
from typing import Any, Literal, Protocol, TypeVar

from textual.worker import Worker, WorkerState, WorkType

from ethernity.app.execution import (
    ExecutionOutcome,
    ReviewedTask,
    normalize_execution_outcome,
)
from ethernity.app.operation_progress import OperationProgress, OperationProgressSink
from ethernity.app.task_catalog import TASK_TITLES
from ethernity.security.resource_worker import terminate_active_workers
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.task_types import TaskKey
from ethernity.workflows.shared.events import emit_finalizing, event_session
from ethernity.workflows.shared.execution_control import (
    ExecutionControl,
    OperationCancelled,
    cancellation_point,
    execution_session,
)

ResultType = TypeVar("ResultType")
CallThreadReturnType = TypeVar("CallThreadReturnType")


class ExecutionControllerApp(Protocol):
    """App operations required by the execution lifecycle."""

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: Literal["information", "warning", "error"] = "information",
        timeout: float | None = None,
        markup: bool = True,
    ) -> None: ...

    def refresh_task_view(self) -> None: ...

    def run_worker(
        self,
        work: WorkType[ResultType],
        *,
        name: str | None = "",
        group: str = "default",
        exit_on_error: bool = True,
        exclusive: bool = False,
        thread: bool = False,
    ) -> Worker[ResultType]: ...

    def call_from_thread(
        self,
        callback: Callable[..., CallThreadReturnType | Awaitable[CallThreadReturnType]],
        *args: Any,
        **kwargs: Any,
    ) -> CallThreadReturnType: ...

    def _present_execution_start(self, reviewed_task: ReviewedTask) -> None: ...

    def _present_execution_progress(self, progress: OperationProgress) -> None: ...

    def _present_execution_outcome(
        self,
        reviewed_task: ReviewedTask,
        outcome: ExecutionOutcome,
    ) -> None: ...


class ExecutionController:
    """Run one task at a time and track its worker."""

    def __init__(self, app: ExecutionControllerApp) -> None:
        self._app = app
        self._running_task: TaskKey | None = None
        self._running_worker: Worker[Any] | None = None
        self._reviewed_tasks: dict[Worker[Any], ReviewedTask] = {}
        self._active_token: object | None = None
        self._thread_finished = False
        self._cancelled_worker: Worker[Any] | None = None
        self._control = ExecutionControl()
        self._progress = OperationProgress()

    @property
    def running_task(self) -> TaskKey | None:
        return self._running_task

    @property
    def running_worker(self) -> Worker[Any] | None:
        return self._running_worker

    def start(self, reviewed_task: ReviewedTask) -> None:
        if self._running_task is not None:
            self._app.notify(f"{TASK_TITLES[self._running_task]} is already running.")
            return

        self._running_task = reviewed_task.task
        execution_token = object()
        self._active_token = execution_token
        self._thread_finished = False
        self._cancelled_worker = None
        self._control = ExecutionControl()
        self._progress = OperationProgress()
        self._app._present_execution_start(reviewed_task)
        try:
            worker = self._app.run_worker(
                partial(self._execute_in_thread, reviewed_task, execution_token),
                name=reviewed_task.task,
                group="task-execution",
                exit_on_error=False,
                exclusive=True,
                thread=True,
            )
        except Exception as error:
            self._clear_execution()
            self._app._present_execution_outcome(
                reviewed_task,
                normalize_execution_outcome(WorkerState.ERROR, error=error),
            )
            return

        self._running_worker = worker
        self._reviewed_tasks[worker] = reviewed_task

    def handle_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != "task-execution":
            return
        if event.state not in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }:
            return

        reviewed_task = self._reviewed_tasks.get(event.worker)
        if reviewed_task is None:
            return
        if event.state == WorkerState.CANCELLED:
            self._control.request_cancel()
            terminate_active_workers()
            self._cancelled_worker = event.worker
            if self._thread_finished:
                self._finish_cancelled(event.worker)
            else:
                self._app.notify(
                    "Cancellation was requested, but the write thread is still running. "
                    "Quit and new writes remain locked until it returns.",
                    severity="warning",
                )
                self._app.refresh_task_view()
            return

        self._reviewed_tasks.pop(event.worker, None)
        self._release_lock(event.worker)
        outcome = normalize_execution_outcome(
            event.state,
            value=event.worker.result if event.state == WorkerState.SUCCESS else None,
            error=event.worker.error if event.state == WorkerState.ERROR else None,
            phase=self._progress.phase,
        )
        if outcome.result.status == "failed":
            outcome = replace(
                outcome,
                failed_stage=self._progress.stage,
                output_note=(
                    "The save did not finish. Check the destination for output."
                    if self._control.committing
                    else "No output was saved."
                ),
            )
        self._app._present_execution_outcome(reviewed_task, outcome)

    def request_cancel(self) -> bool:
        return self._running_task is not None and self._control.request_cancel()

    def _on_progress(self, execution_token: object, progress: OperationProgress) -> None:
        if execution_token is self._active_token:
            self._progress = progress
            self._app._present_execution_progress(progress)

    def _execute_in_thread(
        self,
        reviewed_task: ReviewedTask,
        execution_token: object,
    ) -> TaskExecutionResult:
        sink = OperationProgressSink(
            self._control,
            lambda progress: self._app.call_from_thread(
                self._on_progress, execution_token, progress
            ),
        )
        try:
            with execution_session(self._control), event_session(sink):
                cancellation_point()
                if reviewed_task.task == "settings":
                    emit_finalizing()
                return reviewed_task.execute()
        except OperationCancelled:
            return TaskExecutionResult(
                status="cancelled", message="Cancelled. No output was saved."
            )
        finally:
            self._app.call_from_thread(self._on_thread_finished, execution_token)

    def _on_thread_finished(self, execution_token: object) -> None:
        if execution_token is not self._active_token:
            return
        self._thread_finished = True
        worker = self._cancelled_worker
        if worker is not None:
            self._finish_cancelled(worker)

    def _finish_cancelled(self, worker: Worker[Any]) -> None:
        reviewed_task = self._reviewed_tasks.pop(worker, None)
        if reviewed_task is None:
            return
        self._release_lock(worker)
        self._app._present_execution_outcome(
            reviewed_task,
            normalize_execution_outcome(WorkerState.CANCELLED),
        )

    def _release_lock(self, worker: Worker[Any]) -> None:
        if self._running_worker is not worker:
            return
        self._clear_execution()

    def _clear_execution(self) -> None:
        self._running_worker = None
        self._running_task = None
        self._active_token = None
        self._thread_finished = False
        self._cancelled_worker = None
