from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from textual.widgets import Button, ProgressBar, Static

from ethernity.app.application import EthernityApp
from ethernity.app.execution import ReviewedTask
from ethernity.app.operation_progress import OperationProgress
from ethernity.app.screens.task_progress import TaskProgressScreen
from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.workflows.shared import events
from ethernity.workflows.shared.execution_control import (
    begin_final_write,
    cancellation_point,
)
from tests.support.app import run_app_test


@pytest.mark.parametrize("size", [(120, 40), (80, 24), (60, 20)])
def test_progress_geometry_and_stopping_state(size: tuple[int, int]) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=size) as pilot:
            screen = TaskProgressScreen(
                title="Create backup", destination="~/backup-1234", cancel=lambda: True
            )
            app.push_screen(screen)
            await pilot.pause()
            update = OperationProgress(
                stage="Creating PDFs",
                current=2,
                total=8,
                unit="pages",
                activity=("Reading files", "Encrypting files", "Creating PDFs"),
            )
            screen.update_progress(update)
            await pilot.pause()
            button = screen.query_one("#progress-cancel", Button)
            assert button.region.height >= 1
            assert button.region.bottom <= size[1]
            assert screen.query_one("#progress-body").region.bottom <= button.region.y
            assert screen.query_one("#operation-bar", ProgressBar).total == 8
            await pilot.press("escape")
            assert screen.progress.stopping
            assert button.disabled
            assert "Stopping safely" in str(screen.query_one("#progress-stage", Static).content)
            screen.update_progress(update)  # A previously queued update cannot enable Cancel.
            assert button.disabled
            assert screen.query_one("#operation-bar", ProgressBar).total is None
            assert isinstance(app.screen, TaskProgressScreen)

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_worker_progress_finishes_cleanup_before_returning_to_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    started = threading.Event()
    release = threading.Event()
    cleaned = threading.Event()

    def execute(_state: BackupTaskState) -> TaskExecutionResult:
        try:
            events.emit_phase(phase="encrypt", label="Encrypting")
            started.set()
            assert release.wait(timeout=10)
            cancellation_point()
            begin_final_write()
            return TaskExecutionResult(status="succeeded", message="Backup complete.")
        finally:
            cleaned.set()

    monkeypatch.setattr(BackupTaskState, "execute", execute)

    async def run() -> None:
        state = BackupTaskState(input_paths=[tmp_path / "input.txt"], output_dir=tmp_path)
        app = EthernityApp(backup_state=state)
        async with run_app_test(app, size=(80, 24)) as pilot:
            try:
                reviewed = ReviewedTask.capture("backup", state)
                app.execution_controller.start(reviewed)
                for _ in range(50):
                    await pilot.pause(0.02)
                    if started.is_set():
                        break
                assert started.is_set()
                assert isinstance(app.screen, TaskProgressScreen)
                assert app.screen.progress.stage == "Encrypting files"
                if cancel:
                    await pilot.press("escape")
                    assert app.running_task == "backup"
                    assert not cleaned.is_set()
                release.set()
                for _ in range(50):
                    await pilot.pause(0.02)
                    if isinstance(app.screen, TaskResultScreen):
                        break
                assert cleaned.is_set()
                assert isinstance(app.screen, TaskResultScreen)
                assert not any(
                    isinstance(screen, TaskProgressScreen) for screen in app.screen_stack
                )
                assert app.running_task is None
                assert app._last_execution_result.status == ("cancelled" if cancel else "succeeded")
                if cancel:
                    await pilot.pause()
                    await pilot.click("#result-return")
                    await pilot.pause()
                    assert app.screen is app.screen_stack[0]
                    assert app.backup_state.input_paths == state.input_paths
            finally:
                release.set()

    asyncio.run(run())
