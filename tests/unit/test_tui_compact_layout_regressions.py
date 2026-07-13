from __future__ import annotations

import asyncio
from pathlib import Path

from textual.containers import VerticalScroll
from textual.widgets import Button, Select, Static

from ethernity.app.application import EthernityApp
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.restore import RestoreTaskState


def test_narrow_kit_prioritizes_output_and_custom_qr_warning(tmp_path: Path) -> None:
    async def run() -> None:
        app = EthernityApp(
            kit_state=PrintKitTaskState(
                output_path=tmp_path / "recovery-kit.pdf",
                chunk_size=384,
            )
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("6")
            await pilot.pause()

            workspace = app.query_one("#kit-workspace")
            scroll = workspace.query_one(".task-workspace", VerticalScroll)
            output = app.query_one("#kit-output-value", Static)
            choose_output = app.query_one("#workspace-kit-output", Button)
            warning = app.query_one("#kit-qr-warning", InlineNotice)
            advanced_title = app.query_one("#kit-advanced-panel CollapsibleTitle")
            document_setup = app.query_one("#workspace-kit-variant-select", Select)
            primary = app.query_one("#canvas-primary", Button)

            assert scroll.scroll_offset.y == 0
            assert str(primary.label) == "Review PDF"
            assert not primary.disabled
            assert output.render_line(0).text.rstrip().endswith("recovery-kit.pdf")
            assert "Choose PDF file..." in choose_output.render_line(0).text
            assert "QR sizing - 384 bytes per code" in advanced_title.render_line(0).text
            warning_text = " ".join(
                warning.render_line(line).text.strip() for line in range(warning.region.height)
            )
            assert "page count and make codes harder to scan" in warning_text

            viewport = scroll.content_region
            for critical in (output, choose_output, warning, advanced_title):
                assert viewport.y <= critical.region.y
                assert critical.region.bottom <= viewport.bottom
            assert output.region.y < warning.region.y < advanced_title.region.y
            assert advanced_title.region.y < document_setup.region.y

            assert document_setup.display
            document_setup.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            assert viewport.y <= document_setup.region.y
            assert document_setup.region.bottom <= viewport.bottom

    asyncio.run(run())


def test_restore_destination_path_stays_on_one_line_at_wide_and_narrow_sizes(
    tmp_path: Path,
) -> None:
    destination = (
        tmp_path
        / "very-long-project-folder"
        / "nested-backup-material"
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
        async with app.run_test(size=(96, 40)) as pilot:
            await pilot.press("2")
            await pilot.pause()
            for _step in range(3):
                await pilot.click("#canvas-primary")
                await pilot.pause()

            value = app.query_one(
                "#workflow-restore-destination-body .guided-field-value",
                Static,
            )
            for size in ((96, 40), (80, 24)):
                if app.size != size:
                    await pilot.resize_terminal(*size)
                    await pilot.pause()

                rendered = value.render_line(0).text.rstrip()
                assert value.region.height == 1
                assert value.content_region.height == 1
                assert len(rendered) <= value.content_region.width
                assert rendered.endswith(destination.name)
                assert "..." in rendered
                assert str(value.tooltip) == str(value.content)
                assert value.region.bottom <= app.query_one("#task-action-bar").region.y

    asyncio.run(run())
