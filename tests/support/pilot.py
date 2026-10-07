"""Wait for asynchronous UI state without depending on runner speed."""

from collections.abc import Callable
from time import monotonic

from textual.pilot import Pilot


async def wait_for_condition(
    pilot: Pilot,
    condition: Callable[[], bool],
    description: str,
    *,
    timeout: float = 5.0,
) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        # Process queued changes even when previously rendered content is present.
        await pilot.pause(0.05)
        if condition():
            return
    raise AssertionError(f"Timed out waiting for {description}.")
