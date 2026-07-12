from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, Literal, Protocol, TypeVar

from textual.worker import Worker, WorkerState, WorkType

from ethernity.app.app_types import ActiveTask
from ethernity.app.execution import (
    ExecutionContext,
    ExecutionOutcome,
    normalize_execution_outcome,
)
from ethernity.app.task_catalog import TASK_TITLES
from ethernity.tasks.models import TaskExecutionResult

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

    def _present_execution_start(self, task: ActiveTask) -> None: ...

    def _present_execution_outcome(
        self,
        context: ExecutionContext,
        outcome: ExecutionOutcome,
    ) -> None: ...


class ExecutionController:
    """Own the worker state machine for one physical write at a time."""

    def __init__(self, app: ExecutionControllerApp) -> None:
        self._app = app
        self._running_task: ActiveTask | None = None
        self._running_worker: Worker[Any] | None = None
        self._contexts: dict[Worker[Any], ExecutionContext] = {}
        self._active_token: object | None = None
        self._thread_finished = False
        self._cancelled_worker: Worker[Any] | None = None

    @property
    def running_task(self) -> ActiveTask | None:
        return self._running_task

    @property
    def running_worker(self) -> Worker[Any] | None:
        return self._running_worker

    def start(self, context: ExecutionContext) -> None:
        if self._running_task is not None:
            self._app.notify(f"{TASK_TITLES[self._running_task]} is already running.")
            return

        self._running_task = context.task
        execution_token = object()
        self._active_token = execution_token
        self._thread_finished = False
        self._cancelled_worker = None
        self._app._present_execution_start(context.task)
        try:
            worker = self._app.run_worker(
                partial(self._execute_in_thread, context, execution_token),
                name=context.task,
                group="task-execution",
                exit_on_error=False,
                exclusive=True,
                thread=True,
            )
        except Exception as error:
            self._clear_execution()
            self._app._present_execution_outcome(
                context,
                normalize_execution_outcome(WorkerState.ERROR, error=error),
            )
            return

        self._running_worker = worker
        self._contexts[worker] = context

    def handle_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != "task-execution":
            return
        if event.state not in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }:
            return

        context = self._contexts.get(event.worker)
        if context is None:
            return
        if event.state == WorkerState.CANCELLED:
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

        self._contexts.pop(event.worker, None)
        self._release_lock(event.worker)
        self._app._present_execution_outcome(
            context,
            normalize_execution_outcome(
                event.state,
                value=event.worker.result if event.state == WorkerState.SUCCESS else None,
                error=event.worker.error if event.state == WorkerState.ERROR else None,
            ),
        )

    def _execute_in_thread(
        self,
        context: ExecutionContext,
        execution_token: object,
    ) -> TaskExecutionResult:
        try:
            return context.execute()
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
        context = self._contexts.pop(worker, None)
        if context is None:
            return
        self._release_lock(worker)
        self._app._present_execution_outcome(
            context,
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
