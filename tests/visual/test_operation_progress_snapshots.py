"""Keep the progress screen readable in both normal and short terminals."""

from pathlib import Path

import pytest

from ethernity.app.application import EthernityApp
from ethernity.app.operation_progress import OperationProgress
from ethernity.app.screens.task_progress import TaskProgressScreen
from tests.visual.snapshot_support import assert_svg_snapshot, capture_svg


@pytest.mark.parametrize("size,theme", [((100, 36), "dark"), ((80, 24), "light")])
def test_operation_progress_snapshot(size, theme, monkeypatch, update_tui_snapshots) -> None:
    monkeypatch.setattr("ethernity.app.screens.task_progress.monotonic", lambda: 10.0)

    def make_app():
        app = EthernityApp()
        app.theme = f"ethernity-{theme}"
        return app

    async def show_progress(app, pilot):
        screen = TaskProgressScreen(
            title="Backup in progress", destination="~/backup-6f18083cd7220911", cancel=lambda: True
        )
        app.push_screen(screen)
        await pilot.pause()
        screen.update_progress(
            OperationProgress(
                phase="render",
                stage="Creating PDFs",
                current=3,
                total=8,
                unit="pages",
                document="Recovery text PDF",
                documents_done=1,
                documents_total=5,
                activity=("Reading files", "Encrypting files", "Creating PDFs"),
            )
        )

    svg = capture_svg(make_app, terminal_size=size, title="Ethernity", run_before=show_progress)
    path = (
        Path(__file__).with_name("snapshots")
        / f"operation-progress-{theme}-{size[0]}x{size[1]}.svg"
    )
    assert_svg_snapshot(svg, path, update=update_tui_snapshots)
