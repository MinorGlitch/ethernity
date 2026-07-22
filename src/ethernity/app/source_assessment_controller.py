from __future__ import annotations

import asyncio
from typing import Protocol, cast

from textual.app import App

from ethernity.app.app_types import ActiveTask
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.security.resource_worker import terminate_active_workers
from ethernity.tasks import source_assessment as source_assessment_module
from ethernity.tasks.source_assessment import (
    SourceAssessableTaskState,
    SourceAssessment,
    SourceAssessmentRequest,
)


class _SourceAssessmentHost(Protocol):
    active_task: ActiveTask
    workflow_ui_states: dict[ActiveTask, WorkflowUiState]

    def refresh_task_view(self) -> None: ...


class SourceAssessmentController:
    """Own the asynchronous lifecycle for read-only guided-source inspection."""

    def __init__(self, app: _SourceAssessmentHost) -> None:
        self._app = app
        self._generation: dict[ActiveTask, int] = {}
        self._completion: dict[ActiveTask, asyncio.Event] = {}

    def request(self, task: ActiveTask) -> None:
        """Schedule an assessment after a source mutation without blocking the UI."""

        state = self._state(task)
        ui_state = self._app.workflow_ui_states.get(task)
        if state is None or ui_state is None:
            self._app.refresh_task_view()
            return

        request = state.source_assessment_request()
        if request is None:
            self._next_generation(task)
            ui_state.source_assessment_loading = False
            self._app.refresh_task_view()
            return

        generation = self._next_generation(task)
        self._completion[task] = asyncio.Event()
        ui_state.source_assessment_loading = True
        self._app.refresh_task_view()
        app = cast(App[object], self._app)
        app.run_worker(
            self._assess(task, generation, request),
            name=f"assess-{task}-source",
            group=f"assess-{task}-source",
            exclusive=True,
        )

    async def ensure_current(self, task: ActiveTask) -> SourceAssessment | None:
        """Await a missing current assessment before opening final review."""

        state = self._state(task)
        ui_state = self._app.workflow_ui_states.get(task)
        if state is None or ui_state is None:
            return None
        request = state.source_assessment_request()
        if request is None:
            return None
        current = state.current_source_assessment()
        if current is not None:
            return current

        while ui_state.source_assessment_loading:
            completion = self._completion.get(task)
            if completion is None:
                break
            await completion.wait()
            current = state.current_source_assessment()
            if current is not None:
                return current

        request = state.source_assessment_request()
        if request is None:
            return None
        generation = self._next_generation(task)
        self._completion[task] = asyncio.Event()
        ui_state.source_assessment_loading = True
        self._app.refresh_task_view()
        try:
            assessment = await asyncio.to_thread(
                source_assessment_module.assess_source_request,
                request,
            )
            if self._generation.get(task) == generation:
                state.store_source_assessment(request, assessment)
            return assessment
        finally:
            self._finish(task, generation)

    async def _assess(
        self,
        task: ActiveTask,
        generation: int,
        request: SourceAssessmentRequest,
    ) -> None:
        state = self._state(task)
        if state is None:
            self._finish(task, generation)
            return
        try:
            assessment = await asyncio.to_thread(
                source_assessment_module.assess_source_request,
                request,
            )
            if self._generation.get(task) == generation:
                state.store_source_assessment(request, assessment)
        finally:
            self._finish(task, generation)

    def _finish(self, task: ActiveTask, generation: int) -> None:
        if self._generation.get(task) != generation:
            return
        ui_state = self._app.workflow_ui_states.get(task)
        if ui_state is not None:
            ui_state.source_assessment_loading = False
        completion = self._completion.get(task)
        if completion is not None:
            completion.set()
        self._app.refresh_task_view()

    def _next_generation(self, task: ActiveTask) -> int:
        if task in self._generation:
            terminate_active_workers()
        completion = self._completion.get(task)
        if completion is not None:
            completion.set()
        generation = self._generation.get(task, 0) + 1
        self._generation[task] = generation
        return generation

    def _state(self, task: ActiveTask) -> SourceAssessableTaskState | None:
        state = getattr(self._app, f"{task}_state", None)
        return state if isinstance(state, SourceAssessableTaskState) else None
