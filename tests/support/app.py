"""Headless UI sessions with explicit message and render synchronization."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from functools import partial
from typing import TypeVar
from weakref import WeakKeyDictionary, WeakSet, ref

from textual import events, messages
from textual.app import App
from textual.message import Message
from textual.message_pump import MessagePump
from textual.pilot import Pilot
from textual.screen import Screen

Result = TypeVar("Result")


@dataclass
class _Barrier:
    done: asyncio.Event = field(default_factory=asyncio.Event)
    remaining: int = 1

    def __call__(self) -> None:
        self.remaining -= 1
        if not self.remaining:
            self.done.set()


@dataclass
class _Activity:
    generation: int = 0
    last_message: str = ""
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    handling: WeakSet[asyncio.Task] = field(default_factory=WeakSet)
    completed: WeakSet[asyncio.Task] = field(default_factory=WeakSet)
    resized_screens: WeakKeyDictionary[Screen, tuple[int, int]] = field(
        default_factory=WeakKeyDictionary
    )

    def dispatch(self, message: Message) -> None:
        # run_test's hook runs in the receiving pump's task, before its handler.
        # An empty queue alone does not mean an async handler has finished.
        task = asyncio.current_task()
        if task is not None:
            self.handling.add(task)

    def observe_resize(self, screen_ref: ref[Screen], message: Message) -> None:
        screen = screen_ref()
        if screen is not None and isinstance(message, events.Resize):
            self.resized_screens[screen] = message.size

    def observe(self, message: Message) -> None:
        task = asyncio.current_task()
        if task is not None:
            self.handling.discard(task)
        if isinstance(message, (events.Callback, messages.InvokeLater)):
            callback = message.callback
            while isinstance(callback, partial):
                callback = callback.func
            if isinstance(callback, _Barrier):
                return
        if task is not None:
            self.completed.add(task)
        # A queue wakeup can start async idle callbacks after publication. Fence
        # that pump too, without treating wakeups or repaints as new input work.
        if message.no_dispatch:
            return
        self.changed.set()
        if isinstance(message, (events.Timer, messages.Update)):
            return
        self.generation += 1
        self.last_message = type(message).__qualname__


class AppPilot(Pilot[Result]):
    """Finish each interaction before sending the next one.

    Textual's default pause observes CPU idleness, which is not a guarantee that
    messages bubbled through nested editors or post-layout focus work has finished.
    Workers and future timers still require an explicit wait_for_condition().
    """

    def __init__(self, app: App[Result], activity: _Activity) -> None:
        super().__init__(app)
        self._activity = activity
        self._observed: WeakSet[MessagePump] = WeakSet()
        self._requested_size: tuple[int, int] | None = None

    async def pause(self, delay: float | None = None) -> None:
        if delay is not None:
            await asyncio.sleep(delay)
        # Use the same failure signal as Textual's Pilot. A failed message handler
        # can leave an unfinished queue; run_test will re-raise the original error.
        if self.app._exception_event.is_set():
            return
        settled = asyncio.create_task(self._settle())
        failed = asyncio.create_task(self.app._exception_event.wait())
        try:
            done, _ = await asyncio.wait(
                (settled, failed), timeout=30, return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                raise TimeoutError
            if settled in done:
                settled.result()
        except TimeoutError as error:
            raise AssertionError(
                "UI did not settle. "
                f"Screen={type(self.app.screen).__name__}, focus={self.app.focused!r}, "
                f"last message={self._activity.last_message}."
            ) from error
        finally:
            for task in (settled, failed):
                task.cancel()
            await asyncio.gather(settled, failed, return_exceptions=True)

    async def _settle(self) -> None:
        while True:
            generation = self._activity.generation
            await self._drain_messages()
            await self._wait_for_refresh()
            await self.app.animator.wait_until_complete()
            await self._drain_messages()
            if generation != self._activity.generation:
                continue
            if self._timers_finished():
                return
            # Resize delivery and button feedback use timers, not Animator.
            # Wait for their messages instead of continuously posting barriers to
            # every widget. Each wake must pass through the same drain/render
            # cycle, including the child work produced by a screen resize.
            await self._wait_for_timer_activity()

    async def _wait_for_refresh(self) -> None:
        screen = self.app.screen
        rendered = _Barrier()
        self.app.call_after_refresh(rendered)
        refreshed = asyncio.create_task(rendered.done.wait())
        try:
            while not rendered.done.is_set():
                self._activity.changed.clear()
                # A suspended screen may retain its refresh callback until it
                # resumes. Settle the new screen instead of waiting on that one.
                if self.app.screen is not screen:
                    return
                changed = asyncio.create_task(self._activity.changed.wait())
                try:
                    await asyncio.wait((refreshed, changed), return_when=asyncio.FIRST_COMPLETED)
                finally:
                    changed.cancel()
                    await asyncio.gather(changed, return_exceptions=True)
        finally:
            refreshed.cancel()
            await asyncio.gather(refreshed, return_exceptions=True)

    async def _wait_for_timer_activity(self) -> None:
        self._activity.changed.clear()
        while not self._activity.changed.is_set() and not self._timers_finished():
            # A timer may change state without a redraw (for example, when
            # a button's active style is identical). Recheck readiness, but
            # do not post another round of widget callbacks until it changes.
            with suppress(TimeoutError):
                async with asyncio.timeout(0.05):
                    await self._activity.changed.wait()

    def _timers_finished(self) -> bool:
        resized = self._requested_size is None or (
            self._activity.resized_screens.get(self.app.screen) == self._requested_size
        )
        active_buttons = any(
            button.is_on_screen and button.visible
            for button in self.app.screen.query("Button.-active")
        )
        return resized and not active_buttons

    async def _drain_messages(self) -> None:
        barrier = _Barrier(remaining=0)
        new_nodes: set[MessagePump] = set()
        for node in (self.app, *self.app.screen.walk_children(with_self=True)):
            if node not in self._observed:
                node.message_signal.subscribe(self.app, self._activity.observe, immediate=True)
                if isinstance(node, Screen):
                    node.message_signal.subscribe(
                        self.app, partial(self._activity.observe_resize, ref(node)), immediate=True
                    )
                self._observed.add(node)
                new_nodes.add(node)
        # Include previously observed screens and hidden widgets: their handlers
        # can still update application state. New pumps need an initial fence,
        # since their first messages may predate the completion subscription.
        for node in self._observed:
            if not node.is_running:
                continue
            task = node.task
            if (
                node not in new_nodes
                and not node.message_queue_size
                and task not in self._activity.handling
                and task not in self._activity.completed
            ):
                continue
            self._activity.completed.discard(task)
            if node.call_later(barrier):
                barrier.remaining += 1
        # Completed handlers also need a fence: Textual may already have removed
        # the next message from its queue, or still be running idle callbacks.
        # Idle pumps receive no callbacks and cannot amplify synchronization work.
        if barrier.remaining:
            await barrier.done.wait()

    async def press(self, *keys: str) -> None:
        await self.pause()
        for key in keys:
            await super().press(key)
            await self.pause()

    async def resize_terminal(self, width: int, height: int) -> None:
        # Pilot updates the driver, posts Resize, and calls our pause(). The
        # driver's size changes before the screen and child handlers run.
        self._requested_size = (width, height)
        try:
            await super().resize_terminal(width, height)
        finally:
            self._requested_size = None


@asynccontextmanager
async def run_app_test(
    app: App[Result],
    *,
    size: tuple[int, int] = (80, 24),
    tooltips: bool = False,
    notifications: bool = False,
) -> AsyncIterator[AppPilot[Result]]:
    """Observe completed messages in Textual's test session without monkeypatching it."""
    activity = _Activity()
    async with app.run_test(
        size=size,
        tooltips=tooltips,
        notifications=notifications,
        message_hook=activity.dispatch,
    ):
        pilot = AppPilot(app, activity)
        await pilot.pause()
        yield pilot
