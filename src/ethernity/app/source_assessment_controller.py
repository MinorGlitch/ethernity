from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol, cast

from textual.app import App

from ethernity.app.workflow_state import WorkflowUiState
from ethernity.core.execution_control import (
    ExecutionControl,
    OperationCancelled,
    cancellation_point,
    execution_session,
)
from ethernity.tasks import source_assessment as source_assessment_module
from ethernity.tasks.source_assessment import (
    SourceAssessableTaskState,
    SourceAssessment,
    SourceAssessmentRequest,
)
from ethernity.tasks.task_types import TaskKey


class _SourceAssessmentHost(Protocol):
    active_task: TaskKey
    workflow_ui_states: dict[TaskKey, WorkflowUiState]

    @property
    def is_running(self) -> bool: ...

    def refresh_task_view(self) -> None: ...


@dataclass
class _AssessmentRun:
    request: SourceAssessmentRequest
    control: ExecutionControl = field(default_factory=ExecutionControl)
    completion: asyncio.Event = field(default_factory=asyncio.Event)

    def assess(self) -> SourceAssessment:
        with execution_session(self.control):
            cancellation_point()
            result = source_assessment_module.assess_source_request(self.request)
            cancellation_point()
            return result


class SourceAssessmentController:
    """Own the asynchronous lifecycle for read-only guided-source inspection."""

    def __init__(self, app: _SourceAssessmentHost) -> None:
        self._app = app
        self._runs: dict[TaskKey, _AssessmentRun] = {}
        self._closed = False

    def close(self) -> None:
        self._closed = True
        for task in tuple(self._runs):
            self._cancel(task)

    def _cancel(self, task: TaskKey) -> None:
        previous = self._runs.pop(task, None)
        if previous is not None:
            previous.control.request_cancel()
            previous.completion.set()
        self._refresh(task)

    def _refresh(self, task: TaskKey) -> None:
        ui_state = self._app.workflow_ui_states.get(task)
        if ui_state is not None:
            ui_state.source_assessment_loading = task in self._runs
        if self._app.is_running:
            self._app.refresh_task_view()

    def request(self, task: TaskKey) -> None:
        """Schedule an assessment after a source mutation without blocking the UI."""

        if self._closed:
            return
        state = self._state(task)
        ui_state = self._app.workflow_ui_states.get(task)
        if state is None or ui_state is None:
            self._cancel(task)
            self._app.refresh_task_view()
            return

        request = state.source_assessment_request()
        previous = self._runs.get(task)
        if request is not None and previous is not None and previous.request.key == request.key:
            return
        self._cancel(task)
        if request is None:
            return

        run = _AssessmentRun(request)
        self._runs[task] = run
        self._refresh(task)
        app = cast(App[object], self._app)
        app.run_worker(
            self._assess(task, run),
            name=f"assess-{task}-source",
            group=f"assess-{task}-source",
            exclusive=True,
        )

    async def ensure_current(self, task: TaskKey) -> SourceAssessment | None:
        """Await a missing current assessment before opening final review."""

        while not self._closed:
            state = self._state(task)
            if state is None:
                return None
            request = state.source_assessment_request()
            if request is None:
                return None
            current = state.current_source_assessment()
            if current is not None:
                return current
            run = self._runs.get(task)
            if run is None or run.request.key != request.key:
                self.request(task)
            run = self._runs.get(task)
            if run is None:
                return None
            await run.completion.wait()
        return None

    async def _assess(
        self,
        task: TaskKey,
        run: _AssessmentRun,
    ) -> None:
        state = self._state(task)
        if state is None:
            self._finish(task, run)
            return
        try:
            assessment = await asyncio.to_thread(run.assess)
            if self._runs.get(task) is run:
                state.store_source_assessment(run.request, assessment)
        except asyncio.CancelledError:
            run.control.request_cancel()
            raise
        except OperationCancelled:
            pass
        finally:
            self._finish(task, run)

    def _finish(self, task: TaskKey, run: _AssessmentRun) -> None:
        run.completion.set()
        if self._runs.get(task) is run:
            del self._runs[task]
            self._refresh(task)

    def _state(self, task: TaskKey) -> SourceAssessableTaskState | None:
        state = getattr(self._app, f"{task}_state", None)
        return state if isinstance(state, SourceAssessableTaskState) else None
