"""Reviewed visual contract for the non-functional Restore prototype."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Button

from tests.visual.presentation_states import (
    RESTORE_PRESENTATION_STATE_KEYS,
    RESTORE_PRESENTATION_STATES,
)
from tests.visual.restore_prototype import RestorePrototypeApp
from tests.visual.snapshot_support import assert_svg_snapshot, capture_svg

SNAPSHOT_DIR = Path(__file__).with_name("snapshots")
STANDARD_SIZE = (120, 32)
RESPONSIVE_CASES = (
    ("partial", (160, 48)),
    ("partial", (80, 24)),
)
TARGET_SIZES = ((160, 48), (120, 32), (80, 24))


def test_restore_presentation_fixture_catalog_is_complete() -> None:
    assert tuple(RESTORE_PRESENTATION_STATES) == RESTORE_PRESENTATION_STATE_KEYS
    assert all(fixture.key == key for key, fixture in RESTORE_PRESENTATION_STATES.items())
    assert all(len(fixture.steps) == 4 for fixture in RESTORE_PRESENTATION_STATES.values())


@pytest.mark.parametrize("state_key", RESTORE_PRESENTATION_STATE_KEYS)
def test_restore_prototype_state_snapshot(
    state_key: str,
    update_tui_snapshots: bool,
) -> None:
    _assert_case(state_key, STANDARD_SIZE, update=update_tui_snapshots)


@pytest.mark.parametrize(("state_key", "terminal_size"), RESPONSIVE_CASES)
def test_restore_prototype_responsive_snapshot(
    state_key: str,
    terminal_size: tuple[int, int],
    update_tui_snapshots: bool,
) -> None:
    _assert_case(state_key, terminal_size, update=update_tui_snapshots)


@pytest.mark.parametrize("state_key", RESTORE_PRESENTATION_STATE_KEYS)
@pytest.mark.parametrize("terminal_size", TARGET_SIZES)
def test_restore_prototype_controls_fit_target_size(
    state_key: str,
    terminal_size: tuple[int, int],
) -> None:
    async def assert_geometry() -> None:
        fixture = RESTORE_PRESENTATION_STATES[state_key]
        app = RestorePrototypeApp(fixture)
        app.animation_level = "none"
        async with app.run_test(size=terminal_size) as pilot:
            await pilot.pause()
            width, height = terminal_size
            action_bar = app.query_one("#action-bar")
            footer = app.query_one("#shortcut-footer")

            assert action_bar.region.y + action_bar.region.height <= footer.region.y
            for button in app.query(Button):
                if not button.display:
                    continue
                region = button.region
                assert region.width > 0 and region.height > 0, button.id
                assert region.x >= 0 and region.y >= 0, button.id
                assert region.x + region.width <= width, button.id
                assert region.y + region.height <= height, button.id
                assert len(str(button.label)) <= region.width, button.id
                if button.id != "primary-action":
                    assert region.y + region.height <= action_bar.region.y, button.id

            for scroll_view in app.query(VerticalScroll):
                assert scroll_view.max_scroll_x == 0, scroll_view.id

            if width < 96:
                source_actions = list(app.query(".choice-actions Button"))
                if source_actions:
                    assert len({button.region.y for button in source_actions}) == len(
                        source_actions
                    )

    asyncio.run(assert_geometry())


def _assert_case(state_key: str, terminal_size: tuple[int, int], *, update: bool) -> None:
    width, height = terminal_size
    fixture = RESTORE_PRESENTATION_STATES[state_key]
    svg = capture_svg(
        lambda: RestorePrototypeApp(fixture),
        terminal_size=terminal_size,
        title=f"Restore prototype - {state_key} - {width}x{height}",
    )
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"restore-{state_key}-{width}x{height}.svg",
        update=update,
    )
