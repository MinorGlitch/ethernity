"""The UI harness follows delayed event chains and leaves failures visible."""

import asyncio
from time import monotonic

import pytest
from textual import events
from textual.app import App, ComposeResult
from textual.containers import VerticalGroup
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Input, Static

from tests.support.app import run_app_test


class DeferredEditor(VerticalGroup):
    class Changed(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def compose(self) -> ComposeResult:
        yield Input(id="value")

    async def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        await asyncio.sleep(0.01)
        self.post_message(self.Changed(event.value))


class DeferredApp(App[None]):
    value = ""
    focus_callbacks = 0

    def compose(self) -> ComposeResult:
        yield DeferredEditor()
        yield Static("Waiting", id="result")
        yield Button("Done", id="done")

    def on_mount(self) -> None:
        # Repainting in the background must not prevent interaction.
        self.set_interval(0.01, self.query_one("#result").refresh)

    async def on_deferred_editor_changed(self, event: DeferredEditor.Changed) -> None:
        await asyncio.sleep(0.01)
        self.value = event.value
        self.query_one("#result", Static).update(event.value)
        self.focus_callbacks = 4
        self.call_after_refresh(self.finish_focus)

    def finish_focus(self) -> None:
        self.focus_callbacks -= 1
        if self.focus_callbacks:
            self.call_after_refresh(self.finish_focus)
        else:
            self.query_one(Button).focus()

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        raise ValueError("Application handler failed")


def test_pause_finishes_nested_messages_rendering_and_deferred_focus() -> None:
    async def run() -> None:
        app = DeferredApp()
        async with run_app_test(app) as pilot:
            app.query_one(Input).value = "Updated"
            await pilot.pause()
            assert app.value == "Updated"
            assert app.focus_callbacks == 0
            assert "Updated" in app.query_one("#result").render_line(0).text
            assert app.focused is app.query_one(Button)

    asyncio.run(run())


def test_session_preserves_application_exceptions() -> None:
    async def run() -> None:
        app = DeferredApp()
        async with run_app_test(app) as pilot:
            await pilot.click("#done")

    started = monotonic()
    with pytest.raises(ValueError, match="Application handler failed"):
        asyncio.run(run())
    # An exception must interrupt synchronization, not wait out its 30-second cap.
    assert monotonic() - started < 5


@pytest.mark.parametrize("quiet_style", [False, True])
def test_button_feedback_waits_without_continuously_draining_widgets(
    monkeypatch, quiet_style: bool
) -> None:
    class ButtonApp(App[None]):
        CSS = (
            "Button, Button.-active { background: black; border: none; tint: transparent; }"
            if quiet_style
            else ""
        )
        presses = 0

        def compose(self) -> ComposeResult:
            yield Button("Press")

        def on_button_pressed(self, _event: Button.Pressed) -> None:
            self.presses += 1

    async def run() -> None:
        app = ButtonApp()
        async with run_app_test(app) as pilot:
            drains = 0
            drain_messages = pilot._drain_messages

            async def count_drains() -> None:
                nonlocal drains
                drains += 1
                await drain_messages()

            monkeypatch.setattr(pilot, "_drain_messages", count_drains)
            button = app.query_one(Button)
            for _ in range(2):
                button.press()
                await pilot.pause()
                assert not button.has_class("-active")
            assert app.presses == 2
            # Bound queue work, not elapsed time: loaded runners may take longer.
            # Busy polling used hundreds of complete drains per button press.
            assert drains < 40

    asyncio.run(run())


@pytest.mark.parametrize("handler_delay", [0, 0.01, 0.05])
def test_resize_finishes_child_handlers_rendering_and_deferred_focus(handler_delay: float) -> None:
    class ResizingEditor(DeferredEditor):
        async def on_resize(self, event: events.Resize) -> None:
            await asyncio.sleep(handler_delay)
            self.query_one(Input).value = str(event.size.width)

    class ResizingApp(DeferredApp):
        def compose(self) -> ComposeResult:
            yield ResizingEditor()
            yield Static("Waiting", id="result")
            yield Button("Done", id="done")

    async def run() -> None:
        app = ResizingApp()
        async with run_app_test(app) as pilot:
            for width in (100, 40, 120, 60, 60):
                await pilot.resize_terminal(width, 30)
                assert app.value == str(width)
                assert app.focus_callbacks == 0
                assert str(width) in app.query_one("#result").render_line(0).text
                assert app.focused is app.query_one(Button)

    asyncio.run(run())


def test_pause_follows_callbacks_in_a_screen_mounted_by_the_test() -> None:
    async def run() -> None:
        app = DeferredApp()
        async with run_app_test(app) as pilot:
            screen = Screen()
            await app.push_screen(screen)
            await screen.mount(Static("Waiting", id="message"))
            remaining = 5

            def finish() -> None:
                nonlocal remaining
                remaining -= 1
                if remaining:
                    screen.call_after_refresh(finish)
                else:
                    screen.query_one(Static).update("Finished")

            screen.call_after_refresh(finish)
            await pilot.pause()
            assert remaining == 0
            assert "Finished" in screen.query_one(Static).render_line(0).text

    asyncio.run(run())
