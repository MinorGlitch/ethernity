"""Headless UI sessions with explicit message and render synchronization."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from typing import TypeVar
from weakref import WeakSet

from textual import events, messages
from textual.app import App
from textual.message import Message
from textual.message_pump import MessagePump
from textual.pilot import Pilot

from tests.support.pilot import wait_for_condition

Result = TypeVar("Result")


@dataclass
class _Barrier:
    done: asyncio.Event = field(default_factory=asyncio.Event)

    def __call__(self) -> None:
        self.done.set()


@dataclass
class _Activity:
    generation: int = 0
    last_message: str = ""

    def observe(self, message: Message) -> None:
        # Queue wakeups and cursor/progress repaints are not input work.
        # Await rendering separately so they cannot keep a session busy forever.
        if message.no_dispatch or isinstance(message, (events.Timer, messages.Update)):
            return
        if isinstance(message, (events.Callback, messages.InvokeLater)):
            callback = message.callback
            while isinstance(callback, partial):
                callback = callback.func
            if isinstance(callback, _Barrier):
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

    async def pause(self, delay: float | None = None) -> None:
        if delay is not None:
            await asyncio.sleep(delay)
        try:
            # Match Pilot's queue-drain timeout; large layouts on shared CI
            # runners can take longer than the five-second condition polling cap.
            async with asyncio.timeout(30):
                while True:
                    generation = self._activity.generation
                    await self._drain_messages()
                    rendered = _Barrier()
                    self.app.call_after_refresh(rendered)
                    await rendered.done.wait()
                    await self.app.animator.wait_until_complete()
                    await self._drain_messages()
                    # Button press feedback uses a timer and suppresses another
                    # press until it clears; it is not an Animator animation.
                    if generation == self._activity.generation and not self.app.screen.query(
                        "Button.-active"
                    ):
                        return
        except TimeoutError as error:
            raise AssertionError(
                "UI did not settle. "
                f"Screen={type(self.app.screen).__name__}, focus={self.app.focused!r}, "
                f"last message={self._activity.last_message}."
            ) from error

    async def _drain_messages(self) -> None:
        barriers = []
        for node in (self.app, *self.app.screen.walk_children(with_self=True)):
            if node not in self._observed:
                node.message_signal.subscribe(self.app, self._activity.observe, immediate=True)
                self._observed.add(node)
            barrier = _Barrier()
            if node.call_later(barrier):
                barriers.append(barrier.done.wait())
        await asyncio.gather(*barriers)

    async def press(self, *keys: str) -> None:
        await self.pause()
        for key in keys:
            await super().press(key)
            await self.pause()

    async def resize_terminal(self, width: int, height: int) -> None:
        await super().resize_terminal(width, height)
        # Textual delays terminal resize delivery with a timer.
        await wait_for_condition(
            self,
            lambda: self.app.screen.size == (width, height),
            f"terminal resize to {width}x{height}",
        )


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
    ):
        pilot = AppPilot(app, activity)
        await pilot.pause()
        yield pilot
