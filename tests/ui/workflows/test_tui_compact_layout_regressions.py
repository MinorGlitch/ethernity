from __future__ import annotations

import asyncio
from pathlib import Path

from textual.containers import VerticalScroll
from textual.widgets import Button, Input, Select, Static

from ethernity.app.application import EthernityApp
from ethernity.app.widgets.workbench import WorkbenchSteps
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.restore import RestoreTaskState
from tests.support.app import run_app_test


def test_narrow_kit_keeps_fields_and_their_warning_reachable(tmp_path: Path) -> None:
    async def run() -> None:
        app = EthernityApp(
            kit_state=PrintKitTaskState(
                output_path=tmp_path / "recovery-kit.pdf",
                chunk_size=384,
            )
        )
        async with run_app_test(app, size=(80, 24)) as pilot:
            await pilot.press("6")

            workspace = app.query_one("#kit-workspace")
            scroll = workspace.query_one(".task-workspace", VerticalScroll)
            output = app.query_one("#kit-output-value", Static)
            choose_output = app.query_one("#workspace-kit-output", Button)
            warning = app.query_one("#kit-qr-warning", InlineNotice)
            qr_value = app.query_one("#kit-chunk-size-value", Static)
            document_setup = app.query_one("#workspace-kit-variant-select", Select)
            primary = app.query_one("#canvas-primary", Button)

            assert scroll.scroll_offset.y == 0
            assert str(primary.label) == "Review PDF"
            assert not primary.disabled
            assert output.render_line(0).text.rstrip().endswith("recovery-kit.pdf")
            assert "Change..." in choose_output.render_line(0).text
            assert len(str(choose_output.label)) <= choose_output.content_region.width
            assert "384 bytes per code" in str(qr_value.content)
            warning_text = " ".join(
                warning.render_line(line).text.strip() for line in range(warning.region.height)
            )
            assert "Warning: Custom QR sizing may make codes harder to scan." in warning_text

            viewport = scroll.content_region
            assert output.region.y < document_setup.region.y < qr_value.region.y < warning.region.y
            for critical in (output, choose_output, document_setup, qr_value, warning):
                critical.scroll_visible(animate=False, immediate=True)
                await pilot.pause()
                assert viewport.contains_region(critical.region)

    asyncio.run(run())


def test_restore_destination_path_stays_on_one_line_at_wide_and_narrow_sizes(
    tmp_path: Path,
) -> None:
    destination = (
        tmp_path
        / "very-long-project-folder"
        / "nested-backup-documents"
        / "paper-recovery-session"
        / "final-destination"
        / "restored-files-folder"
    )

    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
                output_path=destination,
            )
        )
        async with run_app_test(app, size=(96, 40)) as pilot:
            await pilot.press("2")
            await pilot.click(app.query_one(WorkbenchSteps).button_for("destination"))
            await pilot.pause()
            value = app.query_one(
                "#workflow-restore-destination-body-value",
                Input,
            )
            for size in ((96, 40), (80, 24)):
                if app.size != size:
                    await pilot.resize_terminal(*size)
                    await pilot.pause()

                value.focus(scroll_visible=True)
                await pilot.pause()
                assert value.value == str(destination)
                assert value.region.width <= app.query_one("#task-canvas").region.width
                assert value.content_region.height == 1
                rendered_value = [
                    value.render_line(line).text.strip() for line in range(value.region.height)
                ]
                assert sum(bool(line) for line in rendered_value) == 1
                assert value.region.bottom <= app.query_one("#task-action-bar").region.y

    asyncio.run(run())
