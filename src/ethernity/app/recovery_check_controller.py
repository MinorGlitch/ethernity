"""Run disposable recovery tests without blocking or retaining secrets in the UI."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from functools import partial

from textual.app import App

from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.task_result import ResultContextAction, TaskResultScreen
from ethernity.core.execution_control import (
    ExecutionControl,
    OperationCancelled,
)
from ethernity.tasks import recovery_check
from ethernity.workflows.recovery.session import RecoverySession


class RecoveryCheckController:
    """Serialize checks and bind their feedback to the result screen that requested them."""

    def __init__(self, app: App[None]) -> None:
        self._app = app
        self._running = False
        self._closed = False
        self._control: ExecutionControl | None = None
        self._screen: TaskResultScreen | None = None

    @property
    def running(self) -> bool:
        return self._running

    def start(
        self,
        request: recovery_check.GeneratedRecoveryCheckRequest,
        screen: TaskResultScreen,
        action: ResultContextAction,
    ) -> bool:
        """Start one background test; reject duplicate or stale requests."""

        if self._closed or self._running or not self._screen_is_live(screen):
            return False
        self._running = True
        control = ExecutionControl()
        self._control = control
        self._screen = screen
        screen.set_context_action_running(action)
        check = self._check(request, screen, action, control)
        try:
            self._app.run_worker(
                check,
                name="check-document-recovery",
                group="check-document-recovery",
                exit_on_error=False,
            )
        except Exception:
            check.close()
            self._running = False
            self._control = None
            self._screen = None
            if self._screen_is_live(screen):
                screen.show_context_action_result(
                    action, "The recovery test could not start. Try again.", success=False
                )
            return False
        return True

    def close(self) -> None:
        """Cancel outstanding work when the app is closing."""

        self._closed = True
        if self._control is not None:
            self._control.request_cancel()

    def cancel(self, screen: TaskResultScreen) -> None:
        """Stop a check when its result screen is dismissed."""
        if self._screen is screen and self._control is not None:
            self._control.request_cancel()

    async def _check(
        self,
        request: recovery_check.GeneratedRecoveryCheckRequest,
        screen: TaskResultScreen,
        action: ResultContextAction,
        control: ExecutionControl,
    ) -> None:
        session = RecoverySession()
        try:
            while self._is_current(screen, control):
                try:
                    result = await control.run_in_thread(
                        partial(recovery_check.check_generated_recovery, request, session=session)
                    )
                except recovery_check.GeneratedRecoveryPassphraseRequired:
                    if not self._is_current(screen, control):
                        return
                    passphrase = await self._request_passphrase(screen, action, control)
                    if passphrase is None:
                        return
                    request = replace(request, passphrase=passphrase)
                    continue
                except Exception as error:
                    if self._is_current(screen, control):
                        message = (
                            str(error).strip() or "The supplied documents could not be recovered."
                        )
                        screen.show_context_action_result(
                            action, f"Recovery test failed: {message}", success=False
                        )
                    return

                if self._is_current(screen, control):
                    screen.show_context_action_result(
                        action, _success_message(result), success=True
                    )
                return
        except asyncio.CancelledError:
            control.request_cancel()
            raise
        except OperationCancelled:
            pass
        finally:
            self._running = False
            self._control = None
            self._screen = None

    async def _request_passphrase(
        self, screen: TaskResultScreen, action: ResultContextAction, control: ExecutionControl
    ) -> str | None:
        passphrase = await self._app.push_screen_wait(
            EditFieldScreen(
                title="Recovery test passphrase",
                prompt="Enter the phrase from the recovery document.",
                password=True,
            )
        )
        if not self._is_current(screen, control):
            return None
        if not passphrase:
            screen.show_context_action_result(
                action, "Recovery test cancelled. No recovery check completed.", success=False
            )
            return None
        return passphrase

    def _screen_is_live(self, screen: TaskResultScreen) -> bool:
        return screen.is_mounted and screen in self._app.screen_stack

    def _is_current(self, screen: TaskResultScreen, control: ExecutionControl) -> bool:
        return not self._closed and not control.cancel_requested and self._screen_is_live(screen)


def _success_message(result: recovery_check.GeneratedRecoveryCheckResult) -> str:
    files = f"{result.file_count} {'file' if result.file_count == 1 else 'files'}"
    sheets = (
        f" using {result.recovery_sheet_count} recovery "
        f"{'sheet' if result.recovery_sheet_count == 1 else 'sheets'}"
        if result.recovery_sheet_count
        else " using the supplied phrase"
    )
    return f"PDF check passed\n{files} recovered{sheets}."


__all__ = ["RecoveryCheckController"]
