"""Run disposable recovery tests without blocking or retaining secrets in the UI."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from textual.app import App

from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.task_result import ResultContextAction, TaskResultScreen
from ethernity.tasks import recovery_check


class RecoveryCheckController:
    """Serialize checks and bind their feedback to the result screen that requested them."""

    def __init__(self, app: App[None]) -> None:
        self._app = app
        self._running = False
        self._closed = False
        self._generation = 0

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
        self._generation += 1
        generation = self._generation
        screen.set_context_action_running(action)
        check = self._check(request, screen, action, generation)
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
            if self._screen_is_live(screen):
                screen.show_context_action_result(
                    action, "The recovery test could not start. Try again.", success=False
                )
            return False
        return True

    def close(self) -> None:
        """Ignore outstanding work when the app is closing."""

        self._closed = True
        self._generation += 1

    async def _check(
        self,
        request: recovery_check.GeneratedRecoveryCheckRequest,
        screen: TaskResultScreen,
        action: ResultContextAction,
        generation: int,
    ) -> None:
        try:
            while self._is_current(screen, generation):
                try:
                    result = await asyncio.to_thread(
                        recovery_check.check_generated_recovery, request
                    )
                except recovery_check.GeneratedRecoveryPassphraseRequired:
                    if not self._is_current(screen, generation):
                        return
                    passphrase = await self._app.push_screen_wait(
                        EditFieldScreen(
                            title="Recovery test passphrase",
                            prompt="Enter the phrase from the recovery document.",
                            password=True,
                        )
                    )
                    if not self._is_current(screen, generation):
                        return
                    if passphrase is None or passphrase == "":
                        screen.show_context_action_result(
                            action,
                            "Recovery test cancelled. No recovery check completed.",
                            success=False,
                        )
                        return
                    request = replace(request, passphrase=passphrase)
                    continue
                except Exception as error:
                    if self._is_current(screen, generation):
                        message = (
                            str(error).strip() or "The supplied documents could not be recovered."
                        )
                        screen.show_context_action_result(
                            action, f"Recovery test failed: {message}", success=False
                        )
                    return

                if self._is_current(screen, generation):
                    screen.show_context_action_result(
                        action, _success_message(result), success=True
                    )
                return
        finally:
            self._running = False

    def _screen_is_live(self, screen: TaskResultScreen) -> bool:
        return screen.is_mounted and screen in self._app.screen_stack

    def _is_current(self, screen: TaskResultScreen, generation: int) -> bool:
        return not self._closed and generation == self._generation and self._screen_is_live(screen)


def _success_message(result: recovery_check.GeneratedRecoveryCheckResult) -> str:
    files = f"{result.file_count} {'file' if result.file_count == 1 else 'files'}"
    sheets = (
        f" using {result.recovery_sheet_count} recovery "
        f"{'sheet' if result.recovery_sheet_count == 1 else 'sheets'}"
        if result.recovery_sheet_count
        else " using the supplied phrase"
    )
    return (
        f"Generated PDF recovery passed: {files} recovered{sheets} into temporary storage. "
        "Printed pages are untested."
    )


__all__ = ["RecoveryCheckController"]
