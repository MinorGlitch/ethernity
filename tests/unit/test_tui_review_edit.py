from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button

from ethernity.app.application import EthernityApp
from ethernity.app.screens.file_picker import FilePickerScreen
from ethernity.app.screens.review_task import ReviewTaskScreen
from ethernity.tasks.backup import BackupTaskState
from tests.support.pilot import wait_for_widget


def test_review_edit_prepares_a_new_snapshot_before_any_write(tmp_path: Path) -> None:
    source = tmp_path / "record.txt"
    source.write_text("Family records\n")
    old_output = tmp_path / "old-documents"
    new_output = tmp_path / "new-documents"
    app = EthernityApp(backup_state=BackupTaskState(input_paths=[source], output_dir=old_output))

    async def run() -> None:
        async with app.run_test(size=(100, 32)) as pilot:
            await app.action_review()
            await wait_for_widget(pilot, "#review-execute")
            original_review = app.screen
            assert isinstance(original_review, ReviewTaskScreen)
            assert original_review._plan.output_paths == (old_output / "backup-<id>",)
            _output_edit_button(original_review).press()
            await wait_for_widget(pilot, "#file-picker-cancel")
            assert isinstance(app.screen, FilePickerScreen)
            app.screen.dismiss((new_output,))
            await wait_for_widget(pilot, "#review-execute")
            assert app.running_task is None
            assert app.backup_state.output_dir == new_output
            assert isinstance(app.screen, ReviewTaskScreen)
            assert app.screen is not original_review
            assert app.screen._plan.output_paths == (new_output / "backup-<id>",)
            assert not new_output.exists()

    asyncio.run(run())


def test_cancelled_review_edit_returns_to_review_without_mutation(tmp_path: Path) -> None:
    source = tmp_path / "record.txt"
    source.write_text("Family records\n")
    app = EthernityApp(
        backup_state=BackupTaskState(input_paths=[source], output_dir=tmp_path / "documents")
    )

    async def run() -> None:
        async with app.run_test(size=(100, 32)) as pilot:
            initial = app.backup_state.model_dump_json()
            await app.action_review()
            await wait_for_widget(pilot, "#review-execute")
            assert isinstance(app.screen, ReviewTaskScreen)
            _output_edit_button(app.screen).press()
            await wait_for_widget(pilot, "#file-picker-cancel")
            assert isinstance(app.screen, FilePickerScreen)
            await pilot.press("escape")
            await wait_for_widget(pilot, "#review-execute")
            assert isinstance(app.screen, ReviewTaskScreen)
            assert app.backup_state.model_dump_json() == initial
            assert app.running_task is None

    asyncio.run(run())


def _output_edit_button(screen: ReviewTaskScreen) -> Button:
    return next(
        button
        for button in screen.query(Button).results(Button)
        if button.id is not None and button.id.startswith("review-edit-output-")
    )
