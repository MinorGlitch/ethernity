"""Grouped settings, persistent notices and contextual help in both palettes."""

from pathlib import Path

import pytest
from textual.geometry import Region
from textual.widgets import Input, Select

from ethernity.app.widgets.settings_form import SettingsForm
from tests.visual.production_states import SettingsVisualApp
from tests.visual.snapshot_support import assert_svg_snapshot, capture_svg


@pytest.mark.parametrize("theme", ["ethernity-dark", "ethernity-light"])
@pytest.mark.parametrize(
    "group,size",
    [
        ("Advanced", (160, 48)),
        ("Advanced", (80, 24)),
        ("Backup defaults", (80, 24)),
        ("Recovery defaults", (120, 32)),
        ("Security defaults", (120, 32)),
        ("Config file", (80, 24)),
    ],
)
def test_grouped_settings_snapshot(group, size, theme, update_tui_snapshots) -> None:
    def create_app():
        app = SettingsVisualApp(theme=theme)
        app.settings_state.set_setting_value("qr_chunk_size", 1024)
        return app

    async def prepare(app, pilot):
        form = app.query_one(SettingsForm)
        form.show_group(group)
        await pilot.pause()
        form.focus_active()
        await pilot.pause()
        pane = form.active_pane
        assert pane.max_scroll_x == 0
        viewport = Region(0, 0, *size)
        assert viewport.contains_region(pane.region)
        assert pane.region.bottom <= form.query_one("#settings-save-row").region.y
        assert len(list(form.query("#settings-reset-section"))) == 1
        for control in pane.query(".settings-control"):
            assert control.region.width > 0
            if isinstance(control, Select):
                assert control.region.width <= 38
            elif isinstance(control, Input):
                assert control.region.width == 12

    name = f"settings-{group.lower().replace(' ', '-')}-{theme}-{size[0]}x{size[1]}"
    svg = capture_svg(create_app, terminal_size=size, title=name, run_before=prepare)
    assert_svg_snapshot(
        svg, Path(__file__).with_name("snapshots") / f"{name}.svg", update=update_tui_snapshots
    )
