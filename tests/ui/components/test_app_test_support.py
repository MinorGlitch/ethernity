"""The UI harness follows delayed event chains and leaves failures visible."""

import asyncio
from time import monotonic

import pytest
from textual import events
from textual.app import App, ComposeResult
from textual.containers import VerticalGroup
from textual.message import Message
from textual.pilot import Pilot
from textual.screen import Screen
from textual.widgets import Button, Input, Static

from tests.support.app import run_app_test

pytestmark = pytest.mark.portability


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


@pytest.mark.parametrize("activation", ["click", "key"])
def test_session_preserves_application_exceptions(activation: str) -> None:
    async def run() -> None:
        app = DeferredApp()
        async with run_app_test(app) as pilot:
            if activation == "click":
                await pilot.click("#done")
            else:
                app.query_one(Button).focus()
                await pilot.press("enter")

    started = monotonic()
    with pytest.raises(ValueError, match="Application handler failed"):
        asyncio.run(run())
    # An exception must interrupt synchronization, not wait out its 30-second cap.
    assert monotonic() - started < 5


def test_keys_match_textual_pilot_characters_and_aliases() -> None:
    class KeyRecorder(Static, can_focus=True):
        def on_key(self, event: events.Key) -> None:
            event.stop()
            event.prevent_default()
            received.append((event.key, event.character, event.aliases))

    class KeyboardApp(App[None]):
        def compose(self) -> ComposeResult:
            yield KeyRecorder()

    received: list[tuple[str, str | None, list[str]]] = []
    keys = (
        "a",
        "Z",
        "7",
        "\u00e9",
        "\u4e2d",
        "?",
        ",",
        " ",
        "+",
        "\t",
        "space",
        "comma",
        "question_mark",
        "plus",
        "enter",
        "tab",
        "escape",
        "backspace",
        "delete",
        "left",
        "home",
        "ctrl+a",
        "shift+tab",
        "ctrl+left",
        "f2",
    )

    async def run() -> None:
        app = KeyboardApp()
        async with run_app_test(app) as pilot:
            native = Pilot(app)
            for key in keys:
                await native.press(key)
                await pilot.pause()
                assert len(received) == 1, key
                expected = received.pop()
                await pilot.press(key)
                assert received == [expected], key
                received.clear()

    asyncio.run(run())


def test_key_sequence_waits_for_async_changes_and_post_render_focus() -> None:
    class SequenceApp(DeferredApp):
        presses = 0

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.prevent_default()
            self.presses += 1

    async def run() -> None:
        app = SequenceApp()
        async with run_app_test(app) as pilot:
            app.query_one(Input).focus()
            await pilot.press("x", "enter")
            assert app.value == "x"
            assert app.focus_callbacks == 0
            assert "x" in app.query_one("#result").render_line(0).text
            assert app.focused is app.query_one(Button)
            assert app.presses == 1

    asyncio.run(run())


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


def test_pause_waits_for_nested_button_subclasses_but_ignores_hidden_feedback() -> None:
    class NestedButton(Button):
        pass

    class ButtonApp(App[None]):
        def compose(self) -> ComposeResult:
            with VerticalGroup():
                yield NestedButton("Press", id="visible")
                yield NestedButton("Hidden", id="hidden")

    async def run() -> None:
        app = ButtonApp()
        async with run_app_test(app) as pilot:
            hidden = app.query_one("#hidden", NestedButton)
            hidden.display = False
            # A hidden button can retain this class indefinitely. It must not
            # keep the visible screen waiting, or hide a visible button's timer.
            hidden.add_class("-active")
            visible = app.query_one("#visible", NestedButton)
            visible.press()
            assert visible.has_class("-active")
            await pilot.pause()
            assert not visible.has_class("-active")
            assert hidden.has_class("-active")

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


@pytest.mark.parametrize("hidden", [False, True])
@pytest.mark.parametrize("idle_callback", [False, True])
def test_pause_waits_for_in_flight_handlers_with_empty_queues(
    hidden: bool, idle_callback: bool
) -> None:
    class BusyWidget(Static):
        class Work(Message):
            pass

        async def on_busy_widget_work(self, event: Work) -> None:
            event.stop()
            await self.finish()

        async def finish(self) -> None:
            started.set()
            await asyncio.sleep(0.1)
            self.app.query_one("#result", Static).update("Finished")

    class BusyApp(App[None]):
        def compose(self) -> ComposeResult:
            yield BusyWidget(id="busy")
            yield Static("Waiting", id="result")

    async def run() -> None:
        app = BusyApp()
        async with run_app_test(app) as pilot:
            widget = app.query_one(BusyWidget)
            widget.display = not hidden
            await pilot.pause()
            if idle_callback:
                widget.call_next(widget.finish)
            else:
                widget.post_message(BusyWidget.Work())
            async with asyncio.timeout(5):
                await started.wait()
            assert widget.message_queue_size == 0
            await pilot.pause()
            assert "Finished" in app.query_one("#result").render_line(0).text

    started = asyncio.Event()
    asyncio.run(run())


def test_idle_widgets_do_not_receive_synchronization_callbacks() -> None:
    class IdleWidget(Static):
        callbacks = 0

        def on_callback(self, _event: events.Callback) -> None:
            self.callbacks += 1

    class IdleApp(App[None]):
        def compose(self) -> ComposeResult:
            for index in range(200):
                yield IdleWidget(str(index))

    async def run() -> None:
        app = IdleApp()
        async with run_app_test(app) as pilot:
            widgets = app.query(IdleWidget)
            for widget in widgets:
                widget.callbacks = 0
            await pilot.pause()
            await pilot.pause()
            assert sum(widget.callbacks for widget in widgets) == 0

    asyncio.run(run())
