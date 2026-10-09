"""Keep expensive backup print planning off the Textual event loop."""

from __future__ import annotations

import asyncio
from typing import Protocol, cast

from textual.app import App

from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.backup_estimate import estimate_backup
from ethernity.tasks.task_types import TaskKey
from ethernity.workflows.shared.requests import BackupRequest


class _BackupEstimateHost(Protocol):
    active_task: TaskKey
    backup_state: BackupTaskState

    @property
    def is_running(self) -> bool: ...

    def refresh_task_view(self) -> None: ...


class BackupEstimateController:
    """Coalesce edits into one background planner and ignore stale completions."""

    def __init__(self, app: _BackupEstimateHost) -> None:
        self._app = app
        self._desired: BackupRequest | None = None
        self._completed: BackupRequest | None = None
        self._running = False
        self._closed = False
        self._generation = 0

    def refresh(self) -> None:
        """Request the current backup estimate without blocking a view refresh."""

        if self._closed or not self._app.is_running:
            return
        request = self._app.backup_state.estimate_request()
        self._desired = request
        current = self._app.backup_state.current_estimate()
        error = self._app.backup_state.estimate_error()
        if request is not None and (current is not None or error is not None):
            self._completed = request
        elif request == self._completed:
            self._completed = None
        if request is None or request == self._completed or self._running:
            return
        self._running = True
        cast(App[object], self._app).run_worker(
            self._plan_pending(),
            name="estimate-backup-print",
            group="estimate-backup-print",
        )

    def invalidate(self) -> None:
        """Re-read selected files after an explicit reselection of the same paths."""

        self._completed = None
        self._generation += 1
        self._app.backup_state.clear_estimate()

    def close(self) -> None:
        self._closed = True
        self._desired = None

    async def _plan_pending(self) -> None:
        try:
            while not self._closed:
                request = self._desired
                if request is None or request == self._completed:
                    return
                estimate = None
                error = None
                generation = self._generation
                try:
                    estimate = await asyncio.to_thread(estimate_backup, request)
                except (OSError, RuntimeError, ValueError) as exc:
                    error = str(exc)
                if self._closed or not self._app.is_running:
                    return
                if generation != self._generation:
                    continue
                self._completed = request
                if request == self._desired:
                    self._app.backup_state.store_estimate(request, estimate, error=error)
                    if self._app.active_task == "backup":
                        self._app.refresh_task_view()
        finally:
            self._running = False


__all__ = ["BackupEstimateController"]
