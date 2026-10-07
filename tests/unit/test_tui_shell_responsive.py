from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Label, ListView

from ethernity.app.application import EthernityApp
from ethernity.tasks.backup import BackupTaskState


def test_shell_breakpoints_drive_navigation_and_header_priority() -> None:
    assert EthernityApp.HORIZONTAL_BREAKPOINTS == [
        (0, "-ethernity-narrow"),
        (110, "-ethernity-standard"),
        (150, "-ethernity-wide"),
    ]
    assert EthernityApp.VERTICAL_BREAKPOINTS == [
        (0, "-ethernity-short"),
        (28, "-ethernity-tall"),
    ]

    async def run() -> None:
        cases = (
            ((160, 48), "-ethernity-wide", "-ethernity-tall"),
            ((120, 32), "-ethernity-standard", "-ethernity-tall"),
            ((80, 24), "-ethernity-narrow", "-ethernity-short"),
            ((160, 24), "-ethernity-wide", "-ethernity-short"),
        )
        for size, width_class, height_class in cases:
            app = EthernityApp()
            async with app.run_test(size=size) as pilot:
                await pilot.pause()

                assert app.screen.has_class(width_class)
                assert app.screen.has_class(height_class)
                nav_button = app.query_one("#nav-tools", Button)
                header_title = app.query_one("#app-header-title", Label)
                header_status = app.query_one("#app-header-status", Label)

                assert not list(app.query("#nav-drawer, #nav-strip"))
                assert nav_button.display
                assert header_title.display
                assert header_status.display
                assert app.query_one("#app-header").region.height == (1 if size[1] < 28 else 3)
                assert nav_button.region.bottom <= app.query_one("#shell").region.y

    asyncio.run(run())


def test_shell_fills_editor_width_and_reserves_the_action_row() -> None:
    async def run() -> None:
        for size in ((240, 48), (160, 48), (120, 32), (80, 24), (60, 20)):
            app = EthernityApp()
            async with app.run_test(size=size) as pilot:
                await pilot.pause()

                workspace = app.query_one("#workspace").region
                frame = app.query_one("#workbench-frame").region
                canvas = app.query_one("#task-canvas").region
                scroll_viewport = app.query_one("#canvas-task-workspaces").region
                action_bar = app.query_one("#task-action-bar").region
                primary = app.query_one("#canvas-primary", Button).region

                assert frame.width <= 140
                assert abs(frame.x - (size[0] - frame.width) / 2) <= 1
                for selector in ("#app-header", "#workbench-navigation", "#shell"):
                    region = app.query_one(selector).region
                    assert (region.x, region.width) == (frame.x, frame.width)
                assert canvas.x == workspace.x
                assert canvas.width == workspace.width
                assert (
                    scroll_viewport.width == app.query_one("#workbench-editor").content_size.width
                )
                assert (action_bar.x, action_bar.width) == (
                    scroll_viewport.x,
                    scroll_viewport.width,
                )
                title = app.query_one("#canvas-title").region
                assert (title.x, title.width) == (action_bar.x, action_bar.width)
                assert scroll_viewport.bottom <= action_bar.y
                assert action_bar.x <= primary.x
                assert primary.right <= action_bar.right
                assert action_bar.y <= primary.y < action_bar.bottom
                assert action_bar.bottom <= app.query_one("#shell").region.bottom

    asyncio.run(run())


def test_navigation_menus_fit_below_their_buttons_and_close_on_resize() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(160, 48)) as pilot:
            for menu, items in (("manage", 3), ("tools", 2)):
                for width, rows in ((160, 48), (120, 32), (80, 24), (60, 20)):
                    await pilot.resize_terminal(width, rows)
                    await pilot.pause()
                    assert not app._nav_menu_open
                    await pilot.click(f"#nav-{menu}")
                    await pilot.pause()
                    dropdown = app.query_one("#nav-menu").region
                    owner = app.query_one(f"#nav-{menu}", Button).region
                    assert dropdown.width == 34
                    assert dropdown.height == items * 3 + 2
                    assert dropdown.y == owner.bottom
                    assert dropdown.x == min(owner.x, width - dropdown.width)
                    assert dropdown.right <= width
                    assert not dropdown.overlaps(owner)
                    choices = [item for item in app.query("#nav-list > ListItem") if item.display]
                    for current, following in zip(choices, choices[1:], strict=False):
                        assert following.region.y == current.region.bottom
                    for choice in choices:
                        number = choice.query_one(".nav-row-number").region
                        label = choice.query_one(".nav-row-label").region
                        assert number.y == label.y == choice.region.y + 1
                        assert number.height == label.height == 1
                        assert choice.region.height == 3
                    for label in app.query_one("#nav-list", ListView).query(".nav-row-label"):
                        if label.region.width:
                            assert len(str(label.content)) <= label.region.width
                await pilot.press("escape")

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

            assert full_label == "Continue >"
            assert primary.region.height == 3
            assert not action_row.has_class("narrow-mode")

            await pilot.resize_terminal(80, 24)
            await pilot.pause()

            assert app.screen.has_class("-ethernity-narrow")
            assert app.screen.has_class("-ethernity-short")
            assert str(primary.label) == full_label
            assert primary.region.right == action_row.region.right
            assert primary.region.width >= 18
            assert primary.region.height == 1
            assert len(str(primary.label)) <= primary.region.width

            await pilot.resize_terminal(120, 32)
            await pilot.pause()

            assert app.screen.has_class("-ethernity-standard")
            assert str(primary.label) == full_label
            assert primary.region.height == 3

    asyncio.run(run())


def test_ethernity_theme_preserves_light_and_no_color_modes(monkeypatch) -> None:
    async def run() -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            assert app.theme == "ethernity-dark"
            assert app.current_theme.primary == "#E0B56D"
            assert app.no_color

            app.theme = "ethernity-light"
            await pilot.pause()

            assert app.current_theme.name == "ethernity-light"
            assert not app.current_theme.dark

            app.theme = "textual-light"
            await pilot.pause()

            assert app.current_theme.name == "textual-light"

    asyncio.run(run())
