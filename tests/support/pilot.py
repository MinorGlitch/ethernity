"""Wait for asynchronous UI state without depending on runner speed."""

from collections.abc import Callable
from time import monotonic

from textual.pilot import Pilot
from textual.widget import Widget


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
    screen = pilot.app.screen
    focused = screen.focused
    raise AssertionError(
        f"Timed out waiting for {description}. Screen={type(screen).__name__}, focus={focused!r}."
    )


async def wait_for_widget(pilot: Pilot, selector: str) -> Widget:
    """Wait for a widget in the current screen to mount and receive a layout."""
    await wait_for_condition(
        pilot,
        lambda: any(
            widget.is_on_screen and widget.region for widget in pilot.app.screen.query(selector)
        ),
        f"{selector} to mount and lay out",
    )
    return pilot.app.screen.query_one(selector)


async def wait_for_visible(pilot: Pilot, widget: Widget, *, within: Widget | None = None) -> None:
    """Wait for the entire control to be visible, including after scrolling."""
    await wait_for_condition(
        pilot,
        lambda: (
            _fully_visible(widget)
            and (within is None or within.region.contains_region(widget.region))
        ),
        f"{widget.id or type(widget).__name__} to be fully visible",
    )


async def wait_for_focus(pilot: Pilot, widget: Widget) -> None:
    await wait_for_condition(
        pilot,
        lambda: pilot.app.focused is widget and _fully_visible(widget),
        f"{widget.id or type(widget).__name__} to receive focus and scroll into view",
    )


async def click_when_ready(pilot: Pilot, selector: str) -> None:
    """Click once the control is visible; never retry an action."""
    widget = await wait_for_widget(pilot, selector)
    await wait_for_condition(
        pilot,
        lambda: not widget.disabled and _fully_visible(widget),
        f"{selector} to be visible and enabled",
    )
    assert await pilot.click(widget), f"Click did not reach {selector}."


def _fully_visible(widget: Widget) -> bool:
    return (
        widget.is_on_screen
        and widget.visible
        and bool(widget.region)
        and widget.screen.find_widget(widget).clip.contains_region(widget.region)
    )
