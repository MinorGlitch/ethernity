from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Label, ListView

from ethernity.app.application import EthernityApp
from ethernity.tasks.backup import BackupTaskState


def test_shell_breakpoints_drive_navigation_and_header_priority() -> None:
    assert EthernityApp.HORIZONTAL_BREAKPOINTS == [
        (0, "-ethernity-narrow"),
        (88, "-ethernity-standard"),
        (132, "-ethernity-wide"),
    ]
    assert EthernityApp.VERTICAL_BREAKPOINTS == [
        (0, "-ethernity-short"),
        (28, "-ethernity-tall"),
    ]

    async def run() -> None:
        cases = (
            ((160, 48), "-ethernity-wide", "-ethernity-tall", False),
            ((120, 32), "-ethernity-standard", "-ethernity-tall", True),
            ((80, 24), "-ethernity-narrow", "-ethernity-short", True),
            ((160, 24), "-ethernity-wide", "-ethernity-short", True),
        )
        for size, width_class, height_class, collapsed in cases:
            app = EthernityApp()
            async with app.run_test(size=size) as pilot:
                await pilot.pause()

                assert app.screen.has_class(width_class)
                assert app.screen.has_class(height_class)
                nav = app.query_one("#nav")
                nav_button = app.query_one("#nav-strip", Button)
                header_title = app.query_one("#app-header-title", Label)
                header_status = app.query_one("#app-header-status", Label)

                assert nav.region.width == (4 if collapsed else 34)
                assert nav_button.display is collapsed
                show_secondary_header = size[0] >= 88 and size[1] >= 28
                assert header_title.display is show_secondary_header
                assert header_status.display is show_secondary_header
                if collapsed:
                    assert nav_button.region.y == app.query_one("#shell").region.y
                    assert nav_button.region.height < nav.region.height

    asyncio.run(run())


def test_shell_constrains_reading_width_and_reserves_the_action_row() -> None:
    async def run() -> None:
        for size in ((160, 48), (120, 32), (80, 24), (60, 20)):
            app = EthernityApp()
            async with app.run_test(size=size) as pilot:
                await pilot.pause()

                workspace = app.query_one("#workspace").region
                canvas = app.query_one("#task-canvas").region
                scroll_viewport = app.query_one("#canvas-task-workspaces").region
                action_bar = app.query_one("#task-action-bar").region
                primary = app.query_one("#canvas-primary", Button).region

                assert canvas.x == workspace.x
                assert canvas.width == min(workspace.width, 112)
                assert scroll_viewport.bottom <= action_bar.y
                assert action_bar.x <= primary.x
                assert primary.right <= action_bar.right
                assert action_bar.y <= primary.y < action_bar.bottom
                assert action_bar.bottom <= app.query_one("#shell").region.bottom

    asyncio.run(run())


def test_navigation_drawer_is_top_aligned_and_labels_fit() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.click("#nav-strip")
            await pilot.pause()

            drawer = app.query_one("#nav-drawer").region
            shell = app.query_one("#shell").region
            workspace = app.query_one("#workspace").region
            nav_button = app.query_one("#nav-strip", Button).region

            assert drawer.width == 34
            assert drawer.y == shell.y
            assert drawer.overlaps(workspace)
            assert not drawer.overlaps(nav_button)
            for label in app.query_one("#nav-list", ListView).query(".nav-row-label"):
                assert len(str(label.content)) <= label.region.width

    asyncio.run(run())


def test_action_bar_keeps_its_label_and_uses_screen_breakpoints() -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            action_row = app.query_one("#canvas-action-row")
            primary = app.query_one("#canvas-primary", Button)
            full_label = str(primary.label)

            assert full_label.startswith("Review")
            assert not action_row.has_class("narrow-mode")

            await pilot.resize_terminal(80, 24)
            await pilot.pause()

            assert app.screen.has_class("-ethernity-narrow")
            assert app.screen.has_class("-ethernity-short")
            assert str(primary.label) == full_label
            assert primary.region.right == action_row.region.right
            assert primary.region.width >= action_row.region.width - 19

            await pilot.resize_terminal(120, 32)
            await pilot.pause()

            assert app.screen.has_class("-ethernity-standard")
            assert str(primary.label) == full_label

    asyncio.run(run())


def test_ethernity_theme_preserves_light_and_no_color_modes(monkeypatch) -> None:
    async def run() -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            assert app.theme == "ethernity-dark"
            assert app.current_theme.primary == "#55AFA5"
            assert app.no_color

            app.theme = "ethernity-light"
            await pilot.pause()

            assert app.current_theme.name == "ethernity-light"
            assert not app.current_theme.dark

            app.theme = "textual-light"
            await pilot.pause()

            assert app.current_theme.name == "textual-light"

    asyncio.run(run())
