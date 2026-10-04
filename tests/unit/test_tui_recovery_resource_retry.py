from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Button, Static
from textual.worker import WorkerState

from ethernity.app.application import EthernityApp
from ethernity.app.execution import ReviewedTask, normalize_execution_outcome
from ethernity.crypto.age_policy import RecoveryWorkLimitExceeded
from ethernity.tasks import restore, source_assessment
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.recovery_resources import recovery_resource_retry
from ethernity.tasks.restore import RestoreTaskState


def _limit_error() -> RecoveryWorkLimitExceeded:
    return RecoveryWorkLimitExceeded("normal work limit exceeded", memory_bytes=2 * 1024**3)


def test_resource_retry_requires_a_typed_failure() -> None:
    error = _limit_error()
    wrapper = ValueError("Failed to prepare recovery")
    wrapper.__cause__ = error
    outcome = normalize_execution_outcome(WorkerState.ERROR, error=wrapper)
    assert outcome.resource_retry is not None
    assert "2,048 MiB" in outcome.resource_retry.message
    assert recovery_resource_retry(ValueError(str(error))) is None
    assert recovery_resource_retry(ValueError("age scrypt logN=22 exceeds the hard limit")) is None
    wrapper.__cause__ = wrapper
    assert recovery_resource_retry(wrapper) is None


@pytest.mark.parametrize("accept", (False, True))
@pytest.mark.parametrize("size", ((80, 24), (120, 40)))
def test_restore_retry_is_explicit_and_keeps_the_reviewed_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, accept: bool, size: tuple[int, int]
) -> None:
    attempts: list[bool] = []
    destinations: list[Path | None] = []

    def execute(self: RestoreTaskState) -> TaskExecutionResult:
        attempts.append(self.resource_intensive_compatibility_recovery)
        destinations.append(self.output_path)
        if not self.resource_intensive_compatibility_recovery:
            raise _limit_error()
        return TaskExecutionResult(status="succeeded", message="Files restored.")

    monkeypatch.setattr(RestoreTaskState, "execute", execute)

    async def wait_for_result(app, pilot) -> None:
        for _ in range(80):
            await pilot.pause(0.05)
            if app.running_task is None and app.screen.query("#result-close"):
                return
        raise AssertionError("restore did not return a result")

    async def run() -> None:
        app = EthernityApp()
        app.restore_state = RestoreTaskState(
            source_paths=[tmp_path / "backup.pdf"],
            passphrase="test passphrase",
            output_path=tmp_path / "reviewed-output",
        )
        async with app.run_test(size=size) as pilot:
            app._show_task("restore")
            await pilot.pause()
            assert not app.query("#workspace-restore-resource-policy")
            assert not app.query("#restore-compatibility-section")
            reviewed = ReviewedTask.capture("restore", app.restore_state)
            app.execution_controller.start(reviewed)
            await wait_for_result(app, pilot)
            estimate = app.screen.query_one("#result-resource-estimate", Static)
            assert "2,048 MiB" in str(estimate.content)
            retry = app.screen.query_one("#result-retry-resources", Button)
            assert str(retry.label) == "Retry with higher limits"
            assert not retry.has_focus
            assert (
                retry.region.height == app.screen.query_one("#result-return", Button).region.height
            )
            assert app.screen.region.contains_region(retry.region)

            app.restore_state.output_path = tmp_path / "edited-output"
            if accept:
                assert await pilot.click("#result-retry-resources")
                await wait_for_result(app, pilot)
                assert not app.screen.query("#result-retry-resources")
                assert attempts == [False, True]
                assert destinations == [tmp_path / "reviewed-output"] * 2
            else:
                await pilot.press("escape")
                await pilot.pause()
                assert attempts == [False]

            assert not app.restore_state.resource_intensive_compatibility_recovery
            assert not reviewed.state_snapshot.resource_intensive_compatibility_recovery
            fresh = ReviewedTask.capture("restore", app.restore_state)
            assert not fresh.state_snapshot.resource_intensive_compatibility_recovery
            assert fresh.plan.output_paths == (tmp_path / "edited-output",)

    asyncio.run(run())


def test_hard_limit_failure_has_no_higher_limit_action(tmp_path: Path) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            state = RestoreTaskState(
                source_paths=[tmp_path / "backup.pdf"],
                passphrase="test passphrase",
                output_path=tmp_path / "output",
            )
            reviewed = ReviewedTask.capture("restore", state)
            for error in (ValueError("age scrypt logN=22 exceeds the hard limit"), _limit_error()):
                attempt = (
                    reviewed.retry_with_higher_limits()
                    if isinstance(error, RecoveryWorkLimitExceeded)
                    else reviewed
                )
                app._present_execution_outcome(
                    attempt, normalize_execution_outcome(WorkerState.ERROR, error=error)
                )
                await pilot.pause()
                assert not app.screen.query("#result-retry-resources")
                await pilot.press("escape")
                await pilot.pause()

    asyncio.run(run())


def test_source_work_limit_does_not_block_the_restore_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def inspect(_request):
        raise _limit_error()

    monkeypatch.setattr(source_assessment, "inspect_recovery", inspect)
    state = RestoreTaskState(
        source_paths=[tmp_path / "backup.pdf"],
        passphrase="test passphrase",
        output_path=tmp_path / "output",
    )
    assessment = state.assess_source()
    assert assessment is not None and assessment.issue is not None
    assert assessment.issue.severity == "warning"
    assert state.validate_task().ready
    monkeypatch.setattr(restore, "execute_recovery", inspect)
    with pytest.raises(RecoveryWorkLimitExceeded):
        state.execute()
