from __future__ import annotations

from typing import TypeVar

from textual import events
from textual.screen import ModalScreen
from textual.widgets import Footer

ScreenResult = TypeVar("ScreenResult")


class EthernityModalScreen(ModalScreen[ScreenResult]):
    """Modal screen that keeps the app footer aligned with the active screen stack."""

    def on_screen_resume(self, _event: events.ScreenResume) -> None:
        self._sync_app_footer()

    def on_screen_suspend(self, _event: events.ScreenSuspend) -> None:
        self._sync_app_footer()

    def _sync_app_footer(self) -> None:
        modal_is_active = any(
            isinstance(screen, EthernityModalScreen) for screen in self.app.screen_stack
        )
        self.app.query_one(Footer).display = not modal_is_active
