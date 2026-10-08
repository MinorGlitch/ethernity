from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, DirectoryTree

from ethernity.app.application import EthernityApp
from ethernity.app.screens.file_picker import FilePickerScreen
from ethernity.app.widgets.workflow.paths import DestinationEditor
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.restore import RestoreTaskState
from tests.support.pilot import wait_for_condition


def test_late_field_commit_keeps_the_task_where_the_field_was_edited() -> None:
    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("root.pdf")],
                passphrase="restore phrase",
                output_path=Path("restore-folder"),
            ),
            add_files_state=AddFilesTaskState(
                source_paths=[Path("update.pdf")],
                passphrase="update phrase",
                output_dir=Path("update-folder"),
            ),
        )
        async with app.run_test(size=(100, 32)) as pilot:
            await app._show_task("restore")
            await pilot.pause()
            destination = app.query_one("#workflow-restore-destination-body", DestinationEditor)
            unlock = app.query_one("#workflow-restore-unlock-body", UnlockEditor)
            await app._show_task("add_files")
            destination.post_message(DestinationEditor.ValueChanged(destination, "edited-restore"))
            unlock.post_message(UnlockEditor.ValueChanged(unlock, "edited restore phrase"))
            await wait_for_condition(
                pilot,
                lambda: (
                    app.restore_state.output_path == Path("edited-restore")
                    and app.restore_state.passphrase == "edited restore phrase"
                ),
                "queued edits to reach the restore draft",
            )

            assert app.active_task == "add_files"
            assert app.restore_state.output_path == Path("edited-restore")
            assert app.restore_state.passphrase == "edited restore phrase"
            assert app.add_files_state.output_dir == Path("update-folder")
            assert app.add_files_state.passphrase == "update phrase"

    asyncio.run(run())


def test_task_shortcuts_cannot_change_the_target_of_an_open_picker() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app._show_task("restore")
            await app.action_edit_primary()
            await pilot.pause()
            picker = app.screen
            assert isinstance(picker, FilePickerScreen)
            picker.query_one("#file-picker-tree", DirectoryTree).focus()

            await pilot.press("3")
            await app.action_show_task("add_files")
            await pilot.pause()
            assert app.screen is picker
            assert app.active_task == "restore"

            picker.query_one("#file-picker-cancel", Button).press()
            await pilot.pause()
            assert app.screen is app.screen_stack[0]
            await app.action_show_task("add_files")
            await pilot.pause()
            assert app.active_task == "add_files"

    asyncio.run(run())
