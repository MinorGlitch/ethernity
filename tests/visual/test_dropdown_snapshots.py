"""Open dropdowns share spacing, width and alignment across the production app."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.geometry import Region
from textual.widgets import Button, ListItem, ListView, OptionList, Select

from ethernity.app.application import EthernityApp
from ethernity.app.widgets.form import FormSelect
from tests.visual.production_states import ProductionVisualApp, SettingsVisualApp, production_case
from tests.visual.snapshot_support import assert_svg_snapshot, capture_svg

SNAPSHOT_DIR = Path(__file__).with_name("snapshots")


@pytest.mark.parametrize(
    "case,selector,size,theme",
    [
        ("restore-empty", "workspace-restore-signature-source", (160, 48), "ethernity-dark"),
        ("restore-empty", "workspace-restore-signature-source", (80, 24), "ethernity-dark"),
        ("restore-empty", "workspace-restore-auth-policy", (120, 32), "ethernity-light"),
        ("backup-print", "workspace-backup-paper-size", (120, 32), "ethernity-dark"),
        (
            "backup-recovery-generated",
            "workspace-backup-passphrase-words",
            (120, 32),
            "ethernity-dark",
        ),
        (
            "backup-recovery-generated",
            "workspace-backup-passphrase-words",
            (80, 24),
            "ethernity-light",
        ),
        ("add-files-empty", "workspace-add-files-signature-source", (120, 32), "ethernity-dark"),
        ("rebuild-empty", "workspace-rebuild-signature-source", (120, 32), "ethernity-light"),
        ("replacement-dense", "workspace-replace-signing-key-select", (120, 32), "ethernity-dark"),
        ("kit-default", "workspace-kit-design", (80, 24), "ethernity-dark"),
        ("settings", "setting-control-render_style", (120, 32), "ethernity-dark"),
        ("settings", "setting-control-page_size", (80, 24), "ethernity-light"),
    ],
    ids=lambda value: f"{value[0]}x{value[1]}" if isinstance(value, tuple) else value,
)
def test_open_dropdown_snapshot(
    case: str,
    selector: str,
    size: tuple[int, int],
    theme: str,
    update_tui_snapshots: bool,
) -> None:
    def make_app() -> EthernityApp:
        app = (
            SettingsVisualApp()
            if case == "settings"
            else ProductionVisualApp(production_case(case))
        )
        app.theme = theme
        return app

    async def open_dropdown(app, pilot) -> None:
        assert all(isinstance(field, FormSelect) for field in app.query(Select))
        app._reveal_focus_target(f"#{selector}")
        await pilot.pause()
        await pilot.wait_for_scheduled_animations()
        field = app.query_one(f"#{selector}", Select)
        field.focus(scroll_visible=False)
        field.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
        if selector == "workspace-restore-signature-source":
            button = app.query_one("#workspace-restore-expected-head", Button)
            assert str(button.label) in button.render_line(button.content_size.height // 2).text
        await pilot.press("enter")
        await pilot.pause()
        overlay = field.query_one(OptionList)
        assert app.screen.focused is overlay
        assert 0 < overlay.region.width == field.region.width <= 48
        assert Region(0, 0, *size).contains_region(overlay.region)
        assert overlay.option_count == len(field._options)
        # Padding belongs to each choice, so all three rows highlight and select it.
        assert overlay.virtual_size.height == overlay.option_count * 3
        assert field.query_one("SelectCurrent #label").region.x == overlay.content_region.x + 1
        if selector == "workspace-backup-passphrase-words" and size == (80, 24):
            await pilot.press("end")
            assert overlay.scroll_y > 0
            assert overlay.highlighted == overlay.option_count - 1

    name = f"dropdown-{selector}-{theme}-{size[0]}x{size[1]}"
    svg = capture_svg(make_app, terminal_size=size, title=name, run_before=open_dropdown)
    assert_svg_snapshot(svg, SNAPSHOT_DIR / f"{name}.svg", update=update_tui_snapshots)


@pytest.mark.parametrize("menu", ["manage", "tools"])
@pytest.mark.parametrize("size", [(120, 32), (80, 24)])
@pytest.mark.parametrize("theme", ["ethernity-dark", "ethernity-light"])
def test_navigation_dropdown_snapshot(
    menu: str,
    size: tuple[int, int],
    theme: str,
    update_tui_snapshots: bool,
) -> None:
    def make_app() -> EthernityApp:
        app = ProductionVisualApp(production_case("backup-empty"))
        app.theme = theme
        return app

    async def open_menu(app, pilot) -> None:
        await pilot.click(f"#nav-{menu}")
        await pilot.press("down")
        nav = app.query_one("#nav-list", ListView)
        assert app.focused is nav
        for item in nav.query(ListItem):
            if item.display:
                assert item.region.height == 3
                assert item.query_one(".nav-row").region.y == item.region.y + 1

    name = f"dropdown-navigation-{menu}-{theme}-{size[0]}x{size[1]}"
    svg = capture_svg(make_app, terminal_size=size, title=name, run_before=open_menu)
    assert_svg_snapshot(svg, SNAPSHOT_DIR / f"{name}.svg", update=update_tui_snapshots)
