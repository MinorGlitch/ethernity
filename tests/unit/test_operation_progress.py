from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.widgets import Button, ProgressBar, Static

from ethernity.app.application import EthernityApp
from ethernity.app.execution import ReviewedTask
from ethernity.app.operation_progress import OperationProgress, OperationProgressSink
from ethernity.app.screens.task_progress import TaskProgressScreen
from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.workflows.shared import events, outputs
from ethernity.workflows.shared.execution_control import (
    ExecutionControl,
    OperationCancelled,
    begin_final_write,
    cancellation_point,
    execution_session,
)
from tests.support.app import run_app_test


def test_cancellation_and_commit_are_mutually_exclusive() -> None:
    for _ in range(20):
        control = ExecutionControl()
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def commit(
            control: ExecutionControl, barrier: threading.Barrier, outcomes: list[str]
        ) -> None:
            barrier.wait()
            try:
                control.begin_commit()
                outcomes.append("committed")
            except OperationCancelled:
                outcomes.append("cancelled")

        worker = threading.Thread(target=commit, args=(control, barrier, outcomes))
        worker.start()
        barrier.wait()
        accepted = control.request_cancel()
        worker.join(timeout=2)
        assert outcomes == ["cancelled" if accepted else "committed"]
        assert not control.can_cancel


def test_cancelled_restore_removes_staging_and_preserves_destination(tmp_path: Path) -> None:
    destination = tmp_path / "restore"
    destination.mkdir()
    control = ExecutionControl()

    class CancelAfterFirstFile:
        def emit(self, event_type: str, **payload: object) -> None:
            if event_type == "progress" and payload.get("current") == 1:
                control.request_cancel()

    with execution_session(control), events.event_session(CancelAfterFirstFile()):
        with pytest.raises(OperationCancelled):
            outputs.write_recovered_outputs(
                str(destination),
                [
                    (SimpleNamespace(path="first.txt"), b"first"),
                    (SimpleNamespace(path="second.txt"), b"second"),
                ],
            )
    assert destination.is_dir()
    assert list(destination.iterdir()) == []
    assert list(tmp_path.iterdir()) == [destination]


def test_last_checkpoint_prevents_publication_and_commit_rejects_cancellation(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "payload").write_bytes(b"data")
    final = tmp_path / "final"
    control = ExecutionControl()
    control.request_cancel()
    with execution_session(control), pytest.raises(OperationCancelled):
        outputs.commit_prepared_output_dir(staging, final)
    assert not final.exists()
    assert staging.exists()  # The owning workflow performs cleanup when this unwinds.

    control = ExecutionControl()
    with execution_session(control):
        outputs.commit_prepared_output_dir(staging, final)
        assert not control.request_cancel()
        cancellation_point()
    assert (final / "payload").read_bytes() == b"data"


def test_progress_only_exposes_curated_activity_and_real_counts() -> None:
    published: list[OperationProgress] = []
    sink = OperationProgressSink(ExecutionControl(), published.append)
    secret = "do-not-display-this-secret"
    for event_type in ("started", "result", "error", "warning", "file"):
        sink.emit(event_type, args={"passphrase": secret}, message=secret, path=secret)
    sink.emit("phase", id="encrypt", label=secret)
    sink.emit("progress", phase="encrypt", current=1, total=1, unit="step", label=secret)
    assert sink.snapshot.total is None
    sink.emit(
        "progress",
        phase="render",
        current=2,
        total=4,
        unit="pages",
        details={"document_type": "recovery", "passphrase": secret},
    )
    assert sink.snapshot.count_text == "Recovery text PDF: 2 of 4 pages"
    assert secret not in repr(published)
    assert secret not in repr(sink.snapshot)


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
            await pilot.pause()
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


def test_progress_disables_cancel_at_final_write() -> None:
    published: list[OperationProgress] = []
    control = ExecutionControl()
    sink = OperationProgressSink(control, published.append)
    with execution_session(control), events.event_session(sink):
        events.emit_phase(phase="publish", label="Publishing update")
        assert published[-1].can_cancel
        events.emit_finalizing()
    assert published[-1].stage == "Saving output"
    assert not published[-1].can_cancel
    assert not control.request_cancel()
