"""Settings structure and the shared controls' rendered text alignment."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.app import ComposeResult
from textual.geometry import Region
from textual.widgets import Button, Checkbox, Input, Static, Switch

from ethernity.app.application import EthernityApp
from ethernity.app.styling import StyledApp
from ethernity.app.widgets.form import FormSelect
from ethernity.app.widgets.settings_form import SETTINGS_SECTIONS, SettingField, SettingsForm
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.tasks.models import TaskIssue, TaskValidation
from ethernity.tasks.settings import SETTING_DESCRIPTORS, SettingsTaskState
from tests.support.pilot import wait_for_condition


class ControlsApp(StyledApp):
    VERTICAL_BREAKPOINTS = EthernityApp.VERTICAL_BREAKPOINTS

    def compose(self) -> ComposeResult:
        yield Input("1234")
        yield Input("5678", compact=True)
        yield Button("Choose folder...", classes="setting-path-button")
        yield FormSelect((("Alpha", "a"),), allow_blank=False)
        yield Switch(True, animate=False)
        yield Checkbox("Enabled")
        yield Static("Field label", classes="field-text")


@pytest.mark.parametrize("size", [(120, 32), (80, 24)])
def test_controls_render_text_in_middle_row_and_keep_horizontal_padding(size) -> None:
    async def run() -> None:
        app = ControlsApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            expected_height = 1 if size[1] < 28 else 3
            middle = expected_height // 2
            for widget in app.query("Input, Button, Switch, Checkbox, .field-text"):
                assert widget.region.height == expected_height
                lines = widget.render_lines(Region(0, 0, widget.region.width, expected_height))
                if isinstance(widget, Switch):
                    assert [
                        index
                        for index, line in enumerate(lines)
                        if any(segment.style.reverse for segment in line)
                    ] == [middle]
                else:
                    assert [index for index, line in enumerate(lines) if line.text.strip()] == [
                        middle
                    ]
                if isinstance(widget, Button):
                    assert str(widget.label) in lines[middle].text
                if isinstance(widget, Input):
                    assert lines[middle].text.startswith(" ")
                    assert widget.content_region.y == widget.region.y + middle
            current = app.query_one("SelectCurrent")
            label = current.query_one("#label")
            arrow = current.query_one(".down-arrow")
            assert current.region.height == expected_height
            assert label.region.height == arrow.region.height == 1
            assert label.region.y == arrow.region.y == current.region.y + middle
            assert label.region.x == current.region.x + 2

    asyncio.run(run())


def test_settings_groups_cover_every_descriptor_once_in_its_own_category() -> None:
    groups = {
        key: group
        for group, sections in SETTINGS_SECTIONS.items()
        for _, rows in sections
        for row in rows
        for key in row
    }
    keys = [
        key
        for sections in SETTINGS_SECTIONS.values()
        for _, rows in sections
        for row in rows
        for key in row
    ]
    assert len(keys) == len(set(keys)) == len(SETTING_DESCRIPTORS)
    assert groups == {descriptor.key: descriptor.group for descriptor in SETTING_DESCRIPTORS}


@pytest.mark.parametrize("theme", ["ethernity-dark", "ethernity-light"])
def test_settings_help_is_contextual_and_warnings_keep_their_own_role(
    tmp_path: Path, theme: str
) -> None:
    async def run() -> None:
        config = tmp_path / "settings.toml"
        config.write_text(DEFAULT_CONFIG_PATH.read_text())
        state = SettingsTaskState.from_current(config)
        state.set_setting_value("qr_chunk_size", 1024)
        app = EthernityApp(settings_state=state)
        app.theme = theme
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("7")
            form = app.query_one(SettingsForm)
            form.show_group("Advanced")
            form.focus_active()
            await wait_for_condition(
                pilot,
                lambda: (
                    "Higher correction"
                    in str(form.query_one("#settings-focus-help", Static).content)
                ),
                "help for the first setting",
            )
            field = form.query_one("#setting-row-qr_chunk_size", SettingField)
            warning = field.query_one(InlineNotice)
            marker = field.query_one(".setting-marker", Static)
            assert warning.display and warning.has_class("notice-warning")
            assert str(warning.content).startswith("Warning:")
            assert str(marker.content) == "Custom"
            assert marker.styles.color != warning.styles.color
            assert not form.query_one("#setting-help-qr_error").display
            assert "Higher correction" in str(
                form.query_one("#settings-focus-help", Static).content
            )
            field.query_one(Input).focus()
            await wait_for_condition(
                pilot,
                lambda: "More bytes" in str(form.query_one("#settings-focus-help", Static).content),
                "help for the focused setting",
            )
            assert "More bytes" in str(form.query_one("#settings-focus-help", Static).content)
            assert warning.region.y >= field.query_one(Input).region.bottom + 1
            form.update_statuses(
                TaskValidation(
                    ready=False,
                    issues=(
                        TaskIssue(
                            code="invalid",
                            message="Choose a positive size.",
                            severity="error",
                            section="qr_chunk_size",
                        ),
                    ),
                    sections=(),
                )
            )
            assert warning.has_class("notice-error")
            assert not warning.has_class("notice-warning")
            assert str(warning.content) == "Error: Choose a positive size."

    asyncio.run(run())


def test_positive_switch_labels_preserve_persisted_negative_flags(tmp_path: Path) -> None:
    async def run() -> None:
        config = tmp_path / "settings.toml"
        config.write_text(DEFAULT_CONFIG_PATH.read_text())
        app = EthernityApp(settings_state=SettingsTaskState.from_current(config))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("7")
            app.query_one(SettingsForm).show_group("Advanced")
            await pilot.pause()
            for key in ("ui_no_color", "ui_no_animations"):
                switch = app.query_one(f"#setting-control-{key}", Switch)
                assert switch.value is True
                switch.focus()
                await pilot.press("space")
                await pilot.pause()
                assert app.settings_state.setting_value(key) is True
                assert SettingsTaskState.from_current(config).setting_value(key) is True
                await pilot.press("space")
                await pilot.pause()
                assert SettingsTaskState.from_current(config).setting_value(key) is False

    asyncio.run(run())


@pytest.mark.parametrize("size", [(120, 32), (80, 24)])
def test_long_settings_page_scrolls_focused_controls_above_the_footer(size) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=size) as pilot:
            await pilot.press("7")
            form = app.query_one(SettingsForm)
            form.show_group("Advanced")
            await pilot.pause()
            pane = form.active_pane
            for control in pane.query(".settings-control"):
                control.focus()
                await wait_for_condition(
                    pilot,
                    lambda control=control: (
                        app.focused is control
                        and pane.content_region.contains_region(control.region)
                    ),
                    f"{control.id} to scroll into view",
                )
                assert app.focused is control
                assert pane.content_region.contains_region(control.region), control.id
                assert control.region.bottom <= form.query_one("#settings-save-row").region.y
            assert pane.scroll_offset.y > 0

    asyncio.run(run())
