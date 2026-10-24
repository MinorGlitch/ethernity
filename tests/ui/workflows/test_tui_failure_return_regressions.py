from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest
from textual.widgets import Button, Static

from ethernity.app.application import EthernityApp
from ethernity.app.execution import (
    ExecutionOutcome,
    ReviewedConfig,
    ReviewedTask,
)
from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.app.widgets.task_canvas import TaskCanvas
from ethernity.core.failures import FailureInfo, FailureStage
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState
from ethernity.tasks.task_types import TaskKey, TaskState
from tests.support.app import run_app_test
from tests.support.pilot import click_when_ready, wait_for_focus, wait_for_widget


@pytest.mark.parametrize("close_method", ["button", "escape"])
def test_closing_successful_backup_resets_flow(close_method: str, tmp_path: Path) -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[tmp_path / "secret.txt"],
                output_dir=tmp_path / "backup-out",
                passphrase="saved recovery phrase",
                design="archive",
                paper_size="A4",
            ),
            settings_state=SettingsTaskState(
                config_path=tmp_path / "settings.toml",
                values={"render": {"style": "forge"}, "page": {"size": "LETTER"}},
            ),
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            restore_before = app.restore_state.model_dump()
            await app._select_workbench_step("print")
            reviewed = _reviewed_task("backup", app.backup_state, tmp_path)
            result = TaskExecutionResult(status="succeeded", message="Backup created.")
            app._present_execution_outcome(reviewed, ExecutionOutcome(result=result))
            await wait_for_widget(pilot, "#result-close")
            assert app.backup_state.input_paths == [tmp_path / "secret.txt"]
            assert app._last_reviewed_task is reviewed

            if close_method == "button":
                await click_when_ready(pilot, "#result-close")
            else:
                await pilot.press("escape")
            await wait_for_focus(pilot, app.query_one("#workspace-backup-files", Button))

            assert app.active_task == "backup"
            assert not app.backup_state.input_paths
            assert app.backup_state.passphrase is None
            assert app.backup_state.output_dir == app.settings_state.path_value("backup_output_dir")
            assert app.backup_state.design == "forge"
            assert app.backup_state.paper_size == "LETTER"
            assert app._last_execution_result is None
            assert app._last_reviewed_task is None
            assert app.query_one(TaskCanvas).active_step == "files"
            assert app._navigation_task_states()["backup"] == ""
            assert app.restore_state.model_dump() == restore_before
            assert not app.backup_state.validate_task().ready

    asyncio.run(run())


@pytest.mark.parametrize("status", ["failed", "cancelled", "partially_succeeded"])
def test_closing_incomplete_backup_keeps_inputs_and_step(status: str, tmp_path: Path) -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[tmp_path / "secret.txt"],
                output_dir=tmp_path / "backup-out",
                passphrase="saved recovery phrase",
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            await app._select_workbench_step("print")
            before = app.backup_state.model_dump()
            reviewed = _reviewed_task("backup", app.backup_state, tmp_path)
            result = TaskExecutionResult.model_validate({"status": status, "message": "Stopped."})
            app._present_execution_outcome(reviewed, ExecutionOutcome(result=result))
            await wait_for_widget(pilot, "#result-close")
            await pilot.press("escape")

            assert app.backup_state.model_dump() == before
            assert app._last_execution_result is result
            assert app._last_reviewed_task is reviewed
            assert app.query_one(TaskCanvas).active_step == "print"

    asyncio.run(run())


def _reviewed_task(
    task: TaskKey,
    state: TaskState,
    tmp_path: Path,
) -> ReviewedTask:
    validation = state.validate_task()
    assert validation.ready
    assert state.recoverable_errors() == ()
    return ReviewedTask(
        task=task,
        state_snapshot=state,
        validation=validation,
        preview=state.preview(),
        plan=state.execution_plan(),
        review_details=(),
        reviewed_config=ReviewedConfig(
            source_path=tmp_path / "unused-config.toml",
            contents=b"",
        ),
    )


def test_restore_runtime_output_failure_returns_to_reviewed_destination(tmp_path: Path) -> None:
    destination = tmp_path / "reviewed-restore-destination"
    state = RestoreTaskState(
        payloads_file=tmp_path / "reviewed-backup.payloads",
        passphrase="correct horse battery staple",
        output_path=destination,
    )
    reviewed_task = _reviewed_task("restore", state, tmp_path)
    outcome = ExecutionOutcome(
        result=TaskExecutionResult(
            status="failed",
            message="Restored files could not be written.",
            failure=FailureInfo("OUTPUT_IO_ERROR", FailureStage.OUTPUT),
        ),
        error_message=f"Permission denied writing destination {destination}.",
        error_detail=f"PermissionError: {destination}",
    )

    async def run() -> None:
        app = EthernityApp(restore_state=state)
        async with run_app_test(app, size=(120, 32)) as pilot:
            app._present_execution_outcome(reviewed_task, outcome)
            await pilot.pause()

            result_screen = cast(TaskResultScreen, app.screen)
            assert str(result_screen.query_one("#result-return", Button).label) == (
                "Edit destination"
            )
            assert str(
                result_screen.query_one("#result-reviewed-destination", Static).content
            ).endswith(str(Path("/") / "reviewed-restore-destination"))

            await click_when_ready(pilot, "#result-return")
            control = await wait_for_widget(pilot, "#workflow-restore-destination-body-action")
            await wait_for_focus(pilot, control)

            assert app.active_task == "restore"
            assert app.workflow_ui_states["restore"].active_step == "destination"
            assert app.screen.focused is not None
            assert app.screen.focused.id == "workflow-restore-destination-body-action"

    asyncio.run(run())


def test_replacement_signing_failure_returns_to_signing_key_recovery(tmp_path: Path) -> None:
    state = ReplaceRecoveryDocsTaskState(
        payloads_file=tmp_path / "reviewed-backup.payloads",
        passphrase="correct horse battery staple",
        output_dir=tmp_path / "replacement-sheets",
        create_signing_key_recovery=True,
    )
    reviewed_task = _reviewed_task("replace_recovery_docs", state, tmp_path)
    outcome = ExecutionOutcome(
        result=TaskExecutionResult(
            status="failed",
            message="Replacement sheets could not be created.",
            failure=FailureInfo("ROOT_SIGNING_KEY_MISMATCH", FailureStage.AUTHENTICATION),
        ),
        error_message="Signing key authentication failed while creating replacement sheets.",
        error_detail="AuthenticationError: signing key was rejected.",
    )

    async def run() -> None:
        app = EthernityApp(replace_recovery_docs_state=state)
        async with run_app_test(app, size=(120, 32)) as pilot:
            app.workflow_ui_states["replace_recovery_docs"].activate("output")
            app._present_execution_outcome(reviewed_task, outcome)
            await pilot.pause()

            result_screen = cast(TaskResultScreen, app.screen)
            assert str(result_screen.query_one("#result-return", Button).label) == (
                "Edit signing-key recovery"
            )

            await click_when_ready(pilot, "#result-return")
            control = await wait_for_widget(pilot, "#workspace-replace-signing-key-select")
            await wait_for_focus(pilot, control)

            assert app.active_task == "replace_recovery_docs"
            assert app.workflow_ui_states["replace_recovery_docs"].active_step == "recovery"
            assert app.query_one("#replace-signing-section").display
            assert app.screen.focused is not None
            assert app.screen.focused.id == "workspace-replace-signing-key-select"

    asyncio.run(run())
