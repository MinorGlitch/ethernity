"""The on-demand recovery retry fits the existing result dialog at both densities."""

from pathlib import Path

import pytest
from textual.widgets import Button, Static

from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.recovery_resources import RecoveryResourceRetry
from tests.visual.production_states import ProductionVisualApp, production_case
from tests.visual.snapshot_support import assert_svg_snapshot, capture_svg


@pytest.mark.parametrize("size", ((80, 24), (120, 32)))
def test_restore_resource_retry_snapshot(size, update_tui_snapshots: bool) -> None:
    async def open_result(app, pilot) -> None:
        screen = TaskResultScreen(
            task="restore",
            title="Restore files",
            result=TaskExecutionResult(status="failed", message="Restore paused."),
            error="This backup exceeds the normal recovery work limit.",
            resource_retry=RecoveryResourceRetry(memory_bytes=2 * 1024**3),
            retry_callback=lambda: None,
        )
        await app.push_screen(screen)
        await pilot.pause()
        estimate = screen.query_one("#result-resource-estimate", Static)
        retry = screen.query_one("#result-retry-resources", Button)
        assert screen.region.contains_region(estimate.region)
        assert screen.region.contains_region(retry.region)
        assert not retry.has_focus

    width, height = size
    svg = capture_svg(
        lambda: ProductionVisualApp(production_case("restore-ready")),
        terminal_size=size,
        title=f"Ethernity - restore-resource-retry - {width}x{height}",
        run_before=open_result,
    )
    assert_svg_snapshot(
        svg,
        Path(__file__).with_name("snapshots") / f"app-restore-resource-retry-{width}x{height}.svg",
        update=update_tui_snapshots,
    )
