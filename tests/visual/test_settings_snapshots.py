"""Grouped settings, persistent notices and contextual help in both palettes."""

from pathlib import Path

import pytest
from textual.geometry import Region
from textual.widgets import Input, Select

from ethernity.app.widgets.form import FormRow
from ethernity.app.widgets.settings_form import SettingsForm
from tests.visual.layout_assertions import assert_scrollbar_gaps
from tests.visual.production_states import SettingsVisualApp
from tests.visual.snapshot_support import assert_svg_snapshot, capture_svg


@pytest.mark.parametrize("theme", ["ethernity-dark", "ethernity-light"])
@pytest.mark.parametrize(
    "group,size",
    [
        ("Advanced", (220, 48)),
        ("Advanced", (160, 48)),
        ("Advanced", (100, 40)),
        ("Advanced", (60, 24)),
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
        assert_scrollbar_gaps(app.screen)
        assert pane.max_scroll_x == 0
        viewport = Region(0, 0, *size)
        assert viewport.contains_region(pane.region)
        assert pane.region.bottom <= form.query_one("#settings-save-row").region.y
        assert len(list(form.query("#settings-reset-section"))) == 1
        body = form.query_one("#settings-form")
        assert body.region.right == form.content_region.right
        assert form.query_one("#settings-heading").region.width == body.content_size.width
        assert form.query_one("#settings-save-row").region.width == body.content_size.width
        _assert_fields_aligned(pane)
        _assert_control_widths(pane)

    name = f"settings-{group.lower().replace(' ', '-')}-{theme}-{size[0]}x{size[1]}"
    svg = capture_svg(create_app, terminal_size=size, title=name, run_before=prepare)
    assert_svg_snapshot(
        svg, Path(__file__).with_name("snapshots") / f"{name}.svg", update=update_tui_snapshots
    )


def _assert_fields_aligned(pane) -> None:
    for row in pane.query(FormRow):
        assert row.region.x == pane.content_region.x
        controls = row.query_one(".form-controls")
        assert controls.region.right <= pane.content_region.right
        label = row.query_one(".form-label")
        if row.has_class("stacked"):
            assert controls.region.y >= label.region.bottom
        else:
            assert controls.region.x == label.region.right + 2
        for marker in row.query(".setting-marker"):
            if marker.display:
                assert controls.region.contains_region(marker.region)
        for notice in row.query(".setting-help"):
            if notice.display:
                assert notice.region.x == controls.region.x
                assert notice.region.y >= controls.region.bottom + 1


def _assert_control_widths(pane) -> None:
    for control in pane.query(".settings-control"):
        assert control.region.width > 0
        if isinstance(control, Select):
            controls = control.parent
            assert controls is not None
            marker_width = sum(
                child.region.width + child.styles.margin.width
                for child in controls.children
                if child.has_class("setting-marker") and child.display
            )
            assert control.region.width == controls.content_size.width - marker_width
        elif isinstance(control, Input):
            assert control.region.width == 12
