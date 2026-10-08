from __future__ import annotations

import asyncio

from textual.widgets import Select

from ethernity.app.application import EthernityApp
from ethernity.app.widgets.form import FormSection
from ethernity.app.widgets.task_canvas import TaskCanvas
from ethernity.tasks.backup import BackupTaskState
from tests.support.pilot import wait_for_condition


def test_backup_fields_follow_their_steps_and_focus_routes_to_them() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            before = app.backup_state.model_dump()
            for selector, step, section_id in (
                ("#workspace-backup-base-dir", "files", "backup-paths-section"),
                ("#workspace-backup-passphrase", "recovery", "backup-passphrase-section"),
                ("#workspace-backup-signing-key-mode", "recovery", "backup-signing-section"),
                ("#workspace-backup-qr-chunk-size", "print", "backup-qr-section"),
                ("#workspace-backup-output", "print", "backup-output-section"),
            ):
                app._reveal_focus_target(selector)
                await pilot.pause()
                control = app.query_one(selector)
                control.focus(scroll_visible=False)
                control.scroll_visible(animate=False, immediate=True)
                await pilot.pause()
                assert app.query_one(TaskCanvas).active_step == step
                assert app.query_one(f"#{section_id}", FormSection) in control.ancestors
                assert app.query_one("#canvas-task-workspaces").region.contains_region(
                    control.region
                )
                assert app.backup_state.model_dump() == before
            assert not app.query(".workspace-advanced-panel")

    asyncio.run(run())


def test_backup_only_shows_fields_for_the_selected_recovery_options() -> None:
    async def run() -> None:
        app = EthernityApp(backup_state=BackupTaskState(passphrase="never-show-this-secret"))
        async with app.run_test(size=(120, 40)) as pilot:
            await app._select_workbench_step("recovery")
            assert not app.query_one("#backup-words-row").display
            assert not app.query_one("#backup-key-sheets-row").display
            assert "never-show-this-secret" not in app.export_screenshot()

            mode = app.query_one("#workspace-backup-signing-key-mode", Select)
            mode.value = "sharded"
            await wait_for_condition(
                pilot,
                lambda: app.backup_state.signing_key_mode == "sharded",
                "signing key selection to update",
            )
            assert app.backup_state.signing_key_mode == "sharded"
            assert app.query_one("#backup-key-sheets-row").display
            mode.focus()
            await pilot.press("tab")
            assert app.screen.focused is app.query_one("#workspace-backup-signing-key-shards")

            mode.value = "embedded"
            await wait_for_condition(
                pilot,
                lambda: app.backup_state.signing_key_mode == "embedded",
                "signing key selection to update",
            )
            app.backup_state.passphrase = None
            app.refresh_task_view()
            await pilot.pause()
            assert not app.query_one("#backup-key-sheets-row").display
            assert app.query_one("#backup-words-row").display

    asyncio.run(run())
