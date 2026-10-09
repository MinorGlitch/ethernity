"""Test waits observe UI progress without swallowing failures or repeating actions."""

import asyncio

import pytest
from textual.app import App, ComposeResult
from textual.css.scalar import ScalarOffset
from textual.widgets import Button

from tests.support.app import run_app_test
from tests.support.pilot import click_when_ready, wait_for_condition, wait_for_focus

pytestmark = pytest.mark.portability


class WaitApp(App[None]):
    clicks = 0

    def compose(self) -> ComposeResult:
        yield Button("Continue", id="continue", disabled=True)

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.clicks += 1


def test_click_waits_for_ready_control_and_sends_one_action() -> None:
    async def run() -> None:
        app = WaitApp()
        async with run_app_test(app) as pilot:
            button = app.query_one(Button)
            button.display = False

            async def reveal() -> None:
                await asyncio.sleep(0.1)
                assert app.clicks == 0
                button.display = True
                await asyncio.sleep(0.1)
                assert app.clicks == 0
                button.disabled = False
                button.focus()

            update = asyncio.create_task(reveal())
            try:
                await click_when_ready(pilot, "#continue")
                await wait_for_condition(pilot, lambda: app.clicks == 1, "button action")
                await wait_for_focus(pilot, button)
                assert app.clicks == 1
            finally:
                await update

    asyncio.run(run())


def test_wait_timeout_reports_expected_change_and_current_screen() -> None:
    async def run() -> None:
        app = WaitApp()
        async with run_app_test(app) as pilot:
            with pytest.raises(AssertionError, match="missing update.*Screen=.*focus="):
                await wait_for_condition(pilot, lambda: False, "missing update", timeout=0.01)

    asyncio.run(run())


def test_click_waits_for_animation_to_finish() -> None:
    async def run() -> None:
        app = WaitApp()
        async with run_app_test(app) as pilot:
            button = app.query_one(Button)
            button.disabled = False
            button.styles.animate("offset", ScalarOffset.from_offset((0, 8)), duration=0.5)

            await click_when_ready(pilot, "#continue")
            await wait_for_condition(pilot, lambda: app.clicks == 1, "moving button action")
            assert button.region.y == 8
            assert app.clicks == 1

    asyncio.run(run())


def test_wait_does_not_swallow_assertion_errors() -> None:
    def check() -> bool:
        raise AssertionError("application failure")

    async def run() -> None:
        app = WaitApp()
        async with run_app_test(app) as pilot:
            with pytest.raises(AssertionError, match="^application failure$"):
                await wait_for_condition(pilot, check, "update", timeout=1)

    asyncio.run(run())
