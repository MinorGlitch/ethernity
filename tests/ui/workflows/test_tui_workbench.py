from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Button, Collapsible, Input, ListItem, ListView, Static

from ethernity.app.application import EthernityApp
from ethernity.app.screens.review_task import ReviewTaskScreen
from ethernity.app.widgets.task_canvas import TaskCanvas
from ethernity.app.widgets.workbench import WorkbenchSteps, WorkbenchSummary
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.restore import RestoreTaskState
from tests.support.app import run_app_test
from tests.support.pilot import wait_for_condition, wait_for_focus


def test_backup_steps_review_current_values_without_writing(tmp_path: Path) -> None:
    source = tmp_path / "records.txt"
    source.write_text("family records")
    output = tmp_path / "backup"

    async def run() -> None:
        app = EthernityApp(backup_state=BackupTaskState(input_paths=[source], output_dir=output))
        async with run_app_test(app, size=(120, 32)) as pilot:
            canvas = app.query_one(TaskCanvas)
            rail = app.query_one(WorkbenchSteps)
            assert canvas.active_step == "files"
            summary = app.query_one(WorkbenchSummary)
            assert not summary.display
            assert app.query_one("#backup-files-section").display
            assert not app.query_one("#backup-recovery-section").display
            await pilot.click("#canvas-primary")
            await wait_for_condition(
                pilot,
                lambda: app.screen.focused is app.query_one("#workspace-backup-recovery-method"),
                "recovery controls to receive focus",
            )
            assert canvas.active_step == "recovery"
            assert summary.display
            assert [
                str(row.query_one(".workbench-summary-label", Static).content)
                for row in summary.query(".workbench-summary-row")
                if row.display
            ] == ["Files"]
            assert app.screen.focused is app.query_one("#workspace-backup-recovery-method")
            await pilot.click("#canvas-primary")
            await wait_for_condition(pilot, lambda: canvas.active_step == "print", "print step")
            assert canvas.active_step == "print"
            await pilot.click(rail.button_for("files"))
            await wait_for_condition(pilot, lambda: canvas.active_step == "files", "files step")
            assert canvas.active_step == "files"
            await pilot.click(rail.button_for("review"))
            await wait_for_condition(
                pilot, lambda: isinstance(app.screen, ReviewTaskScreen), "backup review to open"
            )
            assert isinstance(app.screen, ReviewTaskScreen)
            assert app.screen._plan.output_paths == (output / "backup-<id>",)
            assert not output.exists()
            await pilot.press("escape")
            assert canvas.active_step == "files"

    asyncio.run(run())


def test_restore_has_one_page_heading_and_named_open_sections() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(150, 40)) as pilot:
            await pilot.press("2")
            assert str(app.query_one("#canvas-title", Static).content) == "Restore files"
            assert not app.query(".workflow-step-heading, #canvas-instruction")
            assert not app.query_one(WorkbenchSummary).display
            section = app.query_one("#restore-verification-section")
            assert str(section.query_one(".form-section-title", Static).content) == "Verification"
            assert not section.query(Collapsible)
            assert not app.query("#restore-authentication-help, #restore-authentication-status")

    asyncio.run(run())


def test_continue_keeps_missing_input_visible() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            await pilot.click("#canvas-primary")
            await wait_for_condition(
                pilot,
                lambda: app.screen.focused is app.query_one("#workspace-backup-files"),
                "missing input control to receive focus",
            )
            assert app.query_one(TaskCanvas).active_step == "files"
            assert app.query_one("#canvas-step-issue").display
            assert app.screen.focused is app.query_one("#workspace-backup-files")
            assert app.query_one("#canvas-task-workspaces").region.contains_region(
                app.screen.focused.region
            )

    asyncio.run(run())


@pytest.mark.parametrize("theme", ["ethernity-dark", "ethernity-light"])
def test_warnings_and_errors_are_distinct_from_actions_and_appear_once(theme: str) -> None:
    async def run() -> None:
        app = EthernityApp(kit_state=PrintKitTaskState(chunk_size=384))
        async with run_app_test(app, size=(120, 40)) as pilot:
            app.theme = theme
            await pilot.press("6")
            warning = app.query_one("#kit-qr-warning", InlineNotice)
            assert warning.display
            assert str(warning.content).startswith("Warning:")
            warning_color = warning.styles.color
            action_color = app.query_one("#canvas-primary").styles.background
            assert warning_color != action_color
            assert warning.styles.border_left[0] == "solid"
            assert warning.styles.background.a > 0

            await pilot.press("2")
            await pilot.click("#canvas-primary")
            await pilot.pause()
            errors = [notice for notice in app.query("InlineNotice.notice-error") if notice.region]
            assert len(errors) == 1
            error = errors[0]
            assert str(error.content) == "Error: Choose backup documents."
            assert error.styles.color not in {warning_color, action_color}
            assert error.styles.border_left[0] == "solid"
            assert error.styles.background.a > 0

    asyncio.run(run())


def test_workbench_summary_is_redacted_and_collapses_at_80_columns() -> None:
    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="never-display-this-secret",
                output_path=Path("recovered"),
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            assert await pilot.click("#nav-restore")
            await wait_for_condition(
                pilot, lambda: app.active_task == "restore", "restore workspace to open"
            )
            await wait_for_focus(pilot, app.query_one("#workflow-restore-source-body-load"))
            assert await pilot.click(app.query_one(WorkbenchSteps).button_for("unlock"))
            await wait_for_condition(
                pilot,
                lambda: app.query_one(TaskCanvas).active_step == "unlock",
                "unlock step to open",
            )
            summary = app.query_one(WorkbenchSummary)
            assert summary.display
            assert "never-display-this-secret" not in "\n".join(
                str(item.content) for item in summary.query(Static)
            )
            assert app.query_one("#workflow-restore-unlock-body").region.width > 0
            assert not app.query_one("#workflow-restore-source").display
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            assert not summary.display
            rail = app.query_one(WorkbenchSteps)
            assert rail.region.height == 2
            assert app.query_one("#canvas-primary").region.bottom <= app.size.height - 1
            await pilot.resize_terminal(160, 48)
            await pilot.pause()
            assert summary.display
            assert app.query_one(TaskCanvas).active_step == "unlock"

    asyncio.run(run())


@pytest.mark.portability
def test_step_navigation_commits_destination_draft_before_hiding_editor() -> None:
    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")], passphrase="secret", output_path=Path("old")
            )
        )
        async with run_app_test(app, size=(100, 32)) as pilot:
            await pilot.click("#nav-restore")
            await wait_for_condition(
                pilot, lambda: app.active_task == "restore", "restore workspace to open"
            )
            rail = app.query_one(WorkbenchSteps)
            await pilot.click(rail.button_for("destination"))
            field = app.query_one("#workflow-restore-destination-body-value", Input)
            field.focus()
            await wait_for_focus(pilot, field)
            field.value = "new-destination"
            await app._select_workbench_step("unlock")
            await pilot.pause()
            assert app.restore_state.output_path == Path("new-destination")
            assert app.query_one(TaskCanvas).active_step == "unlock"

    asyncio.run(run())


def test_manage_and_tools_menus_expose_their_tasks_without_loaded_backup() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            await pilot.click("#nav-manage")
            assert app._nav_menu_open
            assert app.query_one("#add_files", ListItem).display
            assert not list(app.query("#backup"))
            assert await pilot.click("#add_files")
            await wait_for_condition(
                pilot,
                lambda: app.active_task == "add_files" and not app._nav_menu_open,
                "Add files workflow to open",
            )
            assert app.active_task == "add_files"
            assert not app._nav_menu_open
            await pilot.click("#nav-tools")
            assert app.query_one("#settings", ListItem).display
            assert not app.query_one("#add_files", ListItem).display
            await pilot.press("down")
            app.refresh_task_view()
            await pilot.pause()
            assert app.query_one("#nav-list", ListView).highlighted_child is app.query_one(
                "#settings", ListItem
            )
            await pilot.press("escape")
            assert not app._nav_menu_open
            assert app.screen.focused is app.query_one("#nav-tools", Button)

    asyncio.run(run())
