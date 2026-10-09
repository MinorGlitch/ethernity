from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Static
from textual.worker import WorkerState

from ethernity.app.application import EthernityApp
from ethernity.app.execution import ReviewedTask, normalize_execution_outcome
from ethernity.crypto.age_policy import RecoveryResourceLimitError
from ethernity.tasks import source_assessment
from ethernity.tasks.restore import RestoreTaskState
from tests.support.app import run_app_test


@pytest.mark.parametrize("size", ((80, 24), (120, 40)))
def test_restore_resource_limit_is_a_failure_without_override(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=size) as pilot:
            state = RestoreTaskState(
                source_paths=[tmp_path / "backup.pdf"],
                passphrase="test passphrase",
                output_path=tmp_path / "output",
            )
            reviewed = ReviewedTask.capture("restore", state)
            error = RecoveryResourceLimitError("age scrypt logN=22 exceeds the hard limit 21")
            app._present_execution_outcome(
                reviewed, normalize_execution_outcome(WorkerState.ERROR, error=error)
            )
            await pilot.pause()
            assert not app.screen.query("#result-retry-resources")
            status = app.screen.query_one("#result-status", Static)
            assert "hard limit 21" in str(status.content)
            assert status.has_class("failure")
            assert app.screen.query_one("#result-return").has_focus
            await pilot.press("escape")
            assert not app.screen.query("#result-close")

    asyncio.run(run())


def test_source_resource_limit_blocks_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def inspect(_request):
        raise RecoveryResourceLimitError("cumulative scrypt work exceeds the recovery KDF budget")

    monkeypatch.setattr(source_assessment, "inspect_recovery", inspect)
    state = RestoreTaskState(
        source_paths=[tmp_path / "backup.pdf"],
        passphrase="test passphrase",
        output_path=tmp_path / "output",
    )
    assessment = state.assess_source()
    assert assessment is not None and assessment.issue is not None
    assert assessment.issue.severity == "error"
    assert "cumulative scrypt work" in assessment.issue.message
    assert not state.validate_task().ready
    assert not (tmp_path / "output").exists()
