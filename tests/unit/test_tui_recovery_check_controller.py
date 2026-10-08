from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from textual.app import ComposeResult
from textual.widgets import Button, Footer, Input, Static

from ethernity.app.recovery_check_controller import RecoveryCheckController
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.app.styling import StyledApp
from ethernity.tasks import recovery_check
from ethernity.tasks.models import TaskExecutionResult
from tests.support.app import run_app_test
from tests.support.pilot import wait_for_condition


class RecoveryCheckApp(StyledApp):
    def compose(self) -> ComposeResult:
        yield Footer()


def _result_screen(path: Path) -> TaskResultScreen:
    return TaskResultScreen(
        task="backup",
        title="Backup created",
        result=TaskExecutionResult(
            status="succeeded",
            message="Created.",
            output_paths=(path,),
            recovery_check_paths=(path,),
        ),
        context_actions_enabled=True,
    )


def test_check_runs_in_background_serializes_and_discards_closed_screen(
    monkeypatch, tmp_path: Path
) -> None:
    started = threading.Event()
    release = threading.Event()
    caller_thread = threading.get_ident()
    service_threads: list[int] = []

    def check(request: recovery_check.GeneratedRecoveryCheckRequest):
        service_threads.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        return recovery_check.GeneratedRecoveryCheckResult(1, 10, 2)

    monkeypatch.setattr(recovery_check, "check_generated_recovery", check)

    async def run() -> None:
        app = RecoveryCheckApp()
        screen = _result_screen(tmp_path / "backup.pdf")
        controller = RecoveryCheckController(app)
        request = recovery_check.GeneratedRecoveryCheckRequest((tmp_path / "backup.pdf",))
        async with run_app_test(app, size=(100, 30)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()
            try:
                assert controller.start(request, screen, "test_recovery")
                assert not controller.start(request, screen, "test_recovery")
                await wait_for_condition(pilot, started.is_set, "recovery check to start")
                assert started.is_set()
                assert controller.running
                assert screen.query_one("#result-test-recovery", Button).disabled
                checks = screen.query_one("#result-document-checks", Static)
                await pilot.press("escape")
                await pilot.pause()
                assert screen not in app.screen_stack
            finally:
                release.set()
            await wait_for_condition(
                pilot, lambda: not controller.running, "recovery check to finish"
            )
            assert not controller.running
            assert "passed" not in str(checks.content)
            controller.close()
            assert not controller.start(request, screen, "test_recovery")

    asyncio.run(run())
    assert service_threads and service_threads[0] != caller_thread


def test_worker_start_failure_restores_actions(monkeypatch, tmp_path: Path) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("worker unavailable")

    async def run() -> None:
        app = RecoveryCheckApp()
        controller = RecoveryCheckController(app)
        screen = _result_screen(tmp_path / "backup.pdf")
        async with run_app_test(app, size=(100, 30)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()
            monkeypatch.setattr(app, "run_worker", fail)
            assert not controller.start(
                recovery_check.GeneratedRecoveryCheckRequest((tmp_path / "backup.pdf",)),
                screen,
                "test_recovery",
            )
            assert not controller.running
            assert not screen.query_one("#result-test-recovery", Button).disabled
            assert "could not start" in str(
                screen.query_one("#result-document-checks", Static).content
            )

    asyncio.run(run())


def test_missing_quorum_stays_a_failed_recovery_check(monkeypatch, tmp_path: Path) -> None:
    def check(request: recovery_check.GeneratedRecoveryCheckRequest):
        raise ValueError("Need at least 2 recovery sheets bound to the root backup.")

    monkeypatch.setattr(recovery_check, "check_generated_recovery", check)

    async def run() -> None:
        app = RecoveryCheckApp()
        controller = RecoveryCheckController(app)
        screen = _result_screen(tmp_path / "backup.pdf")
        async with run_app_test(app, size=(100, 30)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()
            assert controller.start(
                recovery_check.GeneratedRecoveryCheckRequest((tmp_path / "backup.pdf",)),
                screen,
                "test_recovery",
            )
            await wait_for_condition(
                pilot, lambda: not controller.running, "recovery check to finish"
            )
            checks = screen.query_one("#result-document-checks", Static)
            assert checks.has_class("failure")
            assert "Need at least 2" in str(checks.content)
            assert "passed" not in str(checks.content)
            assert not screen.query_one("#result-test-recovery", Button).disabled

    asyncio.run(run())


def test_required_phrase_is_masked_and_explicit_input_retries(monkeypatch, tmp_path: Path) -> None:
    phrases: list[str | None] = []

    def check(request: recovery_check.GeneratedRecoveryCheckRequest):
        phrases.append(request.passphrase)
        if request.passphrase is None:
            raise recovery_check.GeneratedRecoveryPassphraseRequired()
        return recovery_check.GeneratedRecoveryCheckResult(2, 20, 0)

    monkeypatch.setattr(recovery_check, "check_generated_recovery", check)

    async def run() -> None:
        app = RecoveryCheckApp()
        controller = RecoveryCheckController(app)
        screen = _result_screen(tmp_path / "backup.pdf")
        async with run_app_test(app, size=(100, 30)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()
            assert controller.start(
                recovery_check.GeneratedRecoveryCheckRequest((tmp_path / "backup.pdf",)),
                screen,
                "test_recovery",
            )
            await wait_for_condition(
                pilot,
                lambda: (
                    isinstance(app.screen, EditFieldScreen)
                    and bool(app.screen.query("#edit-field-input"))
                ),
                "passphrase editor to mount",
            )
            assert isinstance(app.screen, EditFieldScreen)
            field = app.screen.query_one("#edit-field-input", Input)
            assert field.password
            assert "recovery document" in str(app.screen.query_one("#edit-field-prompt").render())
            field.value = "explicit phrase"
            await pilot.press("enter")
            await wait_for_condition(
                pilot, lambda: not controller.running, "recovery check to finish"
            )
            assert not controller.running
            message = str(screen.query_one("#result-document-checks", Static).content)
            assert "Generated PDF recovery passed" in message
            assert "Printed pages are untested" in message
            assert not screen.query_one("#result-test-recovery", Button).disabled

    asyncio.run(run())
    assert phrases == [None, "explicit phrase"]


def test_cancelled_phrase_restores_actions_and_reports_no_completed_check(
    monkeypatch, tmp_path: Path
) -> None:
    def check(request: recovery_check.GeneratedRecoveryCheckRequest):
        raise recovery_check.GeneratedRecoveryPassphraseRequired()

    monkeypatch.setattr(recovery_check, "check_generated_recovery", check)

    async def run() -> None:
        app = RecoveryCheckApp()
        controller = RecoveryCheckController(app)
        screen = _result_screen(tmp_path / "backup.pdf")
        async with run_app_test(app, size=(100, 30)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()
            assert controller.start(
                recovery_check.GeneratedRecoveryCheckRequest((tmp_path / "backup.pdf",)),
                screen,
                "test_recovery",
            )
            await wait_for_condition(
                pilot,
                lambda: (
                    isinstance(app.screen, EditFieldScreen)
                    and bool(app.screen.query("#edit-field-input"))
                ),
                "passphrase editor to mount",
            )
            await pilot.press("escape")
            await wait_for_condition(
                pilot, lambda: not controller.running, "recovery check to finish"
            )
            assert not controller.running
            assert "No recovery check completed" in str(
                screen.query_one("#result-document-checks", Static).content
            )
            assert not screen.query_one("#result-test-recovery", Button).disabled

    asyncio.run(run())
