"""Desktop quit drains owned work without presenting a new screen."""

import asyncio
import threading

import pytest

from ethernity.app.application import EthernityApp
from ethernity.app.desktop_session import DesktopShutdownRequested
from ethernity.app.execution import ExecutionOutcome, ReviewedTask
from ethernity.core.execution_control import begin_final_write
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.models import TaskExecutionResult
from tests.support.app import run_app_test

pytestmark = pytest.mark.portability


class ObservedApp(EthernityApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.late_screens = []

    def push_screen(self, screen, *args, **kwargs):
        if self._desktop_shutdown_requested:
            self.late_screens.append(screen)
        return super().push_screen(screen, *args, **kwargs)

    def switch_screen(self, screen):
        if self._desktop_shutdown_requested:
            self.late_screens.append(screen)
        return super().switch_screen(screen)


@pytest.mark.parametrize("phase", ["review", "execution"])
@pytest.mark.parametrize("fails", [False, True], ids=["success", "failure"])
def test_desktop_quit_drains_work_without_opening_review_or_results(tmp_path, phase, fails):
    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    source = tmp_path / "input.txt"
    source.write_text("test input")
    saved = tmp_path / "saved.txt"

    def work():
        started.set()
        assert release.wait(10), "Test did not release pending work"
        completed.set()
        if fails:
            raise RuntimeError("Controlled failure")

    class ControlledBackup(BackupTaskState):
        def prepare_review(self, *, force=False):
            if phase == "review":
                work()

        def execute(self):
            begin_final_write()
            work()
            saved.write_text("complete")
            return TaskExecutionResult(status="succeeded", message="Backup complete.")

    async def check():
        app = ObservedApp(backup_state=ControlledBackup(input_paths=[source], output_dir=tmp_path))
        async with run_app_test(app), asyncio.TaskGroup() as pending:
            try:
                if phase == "review":
                    pending.create_task(app.action_review())
                else:
                    app.execution_controller.start(ReviewedTask.capture("backup", app.backup_state))
                assert await asyncio.to_thread(started.wait, 5)
                app.on_desktop_shutdown_requested(DesktopShutdownRequested())
                app.on_desktop_shutdown_requested(DesktopShutdownRequested())
                assert app.screen.disabled
                assert app.is_running
                assert not app._exit
                assert not saved.exists()
                release.set()
                assert app._task is not None
                await asyncio.wait_for(asyncio.shield(app._task), 5)
            finally:
                release.set()
        assert completed.is_set()
        assert not app.late_screens
        assert app.running_task is None
        assert app._preparing_review_task is None
        if phase == "execution":
            assert app._last_execution_result is not None
            assert app._last_execution_result.ok == (not fails)
            assert saved.exists() == (not fails)

    asyncio.run(check())


def test_desktop_quit_during_result_mount_finishes_without_ui_errors(tmp_path):
    async def check():
        app = EthernityApp(backup_state=BackupTaskState(output_dir=tmp_path))
        async with run_app_test(app):
            reviewed = ReviewedTask.capture("backup", app.backup_state)
            app._present_execution_outcome(
                reviewed,
                ExecutionOutcome(TaskExecutionResult(status="succeeded", message="Complete")),
            )
            # Quit can arrive after the operation finishes but before its screen mounts.
            app.on_desktop_shutdown_requested(DesktopShutdownRequested())
            assert app._task is not None
            await asyncio.wait_for(asyncio.shield(app._task), 5)

    asyncio.run(check())
