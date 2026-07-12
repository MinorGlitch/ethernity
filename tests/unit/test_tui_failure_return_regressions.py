from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

from textual.widgets import Button, Collapsible, Static

from ethernity.app.app_types import ActiveTask, TaskState
from ethernity.app.application import EthernityApp
from ethernity.app.execution import (
    ExecutionContext,
    ExecutionOutcome,
    ReviewedConfig,
)
from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState


def _execution_context(
    task: ActiveTask,
    state: TaskState,
    tmp_path: Path,
) -> ExecutionContext:
    validation = state.validate_task()
    assert validation.ready
    assert state.recoverable_errors() == ()
    return ExecutionContext(
        task=task,
        state_snapshot=state,
        validation=validation,
        preview=state.preview(),
        plan=state.execution_plan(),
        decision_facts=(),
        reviewed_config=ReviewedConfig(
            source_path=tmp_path / "unused-config.toml",
            contents=b"",
        ),
    )


async def _click_result_return(app: EthernityApp, pilot: Any) -> None:
    for _ in range(20):
        await pilot.pause(0.05)
        buttons = list(app.screen.query("#result-return"))
        if buttons and buttons[0].region.width > 0:
            assert await pilot.click("#result-return")
            break
    else:
        raise AssertionError("Result return action was not laid out")
    for _ in range(10):
        await pilot.pause(0.05)


def test_restore_runtime_output_failure_returns_to_reviewed_destination(tmp_path: Path) -> None:
    destination = tmp_path / "reviewed-restore-destination"
    state = RestoreTaskState(
        payloads_file=tmp_path / "reviewed-backup.payloads",
        passphrase="correct horse battery staple",
        output_path=destination,
    )
    context = _execution_context("restore", state, tmp_path)
    outcome = ExecutionOutcome(
        result=TaskExecutionResult(
            ok=False,
            message="Restored files could not be written.",
        ),
        error_message=f"Permission denied writing destination {destination}.",
        error_detail=f"PermissionError: {destination}",
    )

    async def run() -> None:
        app = EthernityApp(restore_state=state)
        async with app.run_test(size=(120, 32)) as pilot:
            app._present_execution_outcome(context, outcome)
            await pilot.pause()

            result_screen = cast(TaskResultScreen, app.screen)
            assert str(result_screen.query_one("#result-return", Button).label) == (
                "Edit destination"
            )
            assert str(
                result_screen.query_one("#result-reviewed-destination", Static).content
            ).endswith("/reviewed-restore-destination")

            await _click_result_return(app, pilot)

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
        mint_signing_key_recovery=True,
    )
    context = _execution_context("replace_recovery_docs", state, tmp_path)
    outcome = ExecutionOutcome(
        result=TaskExecutionResult(
            ok=False,
            message="Replacement sheets could not be created.",
        ),
        error_message="Signing key authentication failed while creating replacement sheets.",
        error_detail="AuthenticationError: signing key material was rejected.",
    )

    async def run() -> None:
        app = EthernityApp(replace_recovery_docs_state=state)
        async with app.run_test(size=(120, 32)) as pilot:
            app.workflow_ui_states["replace_recovery_docs"].activate("output")
            app._present_execution_outcome(context, outcome)
            await pilot.pause()

            result_screen = cast(TaskResultScreen, app.screen)
            assert str(result_screen.query_one("#result-return", Button).label) == (
                "Edit signing-key recovery"
            )

            await _click_result_return(app, pilot)

            assert app.active_task == "replace_recovery_docs"
            assert app.workflow_ui_states["replace_recovery_docs"].active_step == "recovery"
            assert not app.query_one("#replace-signature-panel", Collapsible).collapsed
            assert app.screen.focused is not None
            assert app.screen.focused.id == "workspace-replace-signing-key-select"

    asyncio.run(run())
