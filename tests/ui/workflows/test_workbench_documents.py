"""The workbench owns view transitions, including in-flight mounts."""

import asyncio

from ethernity.app.application import EthernityApp
from ethernity.app.widgets.task_canvas import TaskCanvas
from ethernity.app.widgets.task_result import TaskResult
from ethernity.tasks.models import TaskExecutionResult
from tests.support.app import run_app_test


def test_navigation_waits_for_document_mount_before_removing_it() -> None:
    async def run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class MountingResult(TaskResult):
            async def on_mount(self) -> None:
                super().on_mount()
                started.set()
                await release.wait()

        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            canvas = app.query_one(TaskCanvas)
            view = MountingResult(
                task="backup",
                title="Backup",
                result=TaskExecutionResult(status="succeeded", message="Created"),
            )
            canvas.present_document(view)
            await asyncio.wait_for(started.wait(), 5)
            navigating = asyncio.create_task(app._show_task("restore"))
            try:
                # close_document publishes the new desired view before waiting for
                # the existing mount to drain on the canvas's own message queue.
                await asyncio.sleep(0)
                assert canvas.document is None
                assert not navigating.done()
            finally:
                release.set()
            await asyncio.wait_for(navigating, 5)
            await pilot.pause()
            assert app.active_task == "restore"
            assert canvas.document is None
            assert not view.is_attached
            assert len(app.screen_stack) == 1
            assert app.query_one("#canvas-task-workspaces").display

    asyncio.run(run())
