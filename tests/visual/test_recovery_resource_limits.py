"""Fixed recovery resource failures use the ordinary error dialog."""

from pathlib import Path

import pytest
from textual.widgets import Static

from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.tasks.models import TaskExecutionResult
from tests.visual.production_states import ProductionVisualApp, production_case
from tests.visual.snapshot_support import assert_svg_snapshot, capture_svg


@pytest.mark.parametrize("size", ((80, 24), (120, 32)))
def test_restore_resource_limit_snapshot(size, update_tui_snapshots: bool) -> None:
    async def open_result(app, pilot) -> None:
        screen = TaskResultScreen(
            task="restore",
            title="Restore files",
            result=TaskExecutionResult(status="failed", message="Restore failed."),
            error="age scrypt logN=22 exceeds the hard limit 21",
        )
        await app.push_screen(screen)
        await pilot.pause()
        status = screen.query_one("#result-status", Static)
        assert screen.region.contains_region(status.region)
        assert status.has_class("failure")
        assert not screen.query("#result-retry-resources")

    width, height = size
    svg = capture_svg(
        lambda: ProductionVisualApp(production_case("restore-ready")),
        terminal_size=size,
        title=f"Ethernity - restore-resource-limit - {width}x{height}",
        run_before=open_result,
    )
    assert_svg_snapshot(
        svg,
        Path(__file__).with_name("snapshots") / f"app-restore-resource-limit-{width}x{height}.svg",
        update=update_tui_snapshots,
    )
