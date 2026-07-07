#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, Static, Switch

from ethernity.tasks.models import TaskValidation
from ethernity.tasks.settings import SETTING_DESCRIPTORS, SettingDescriptor, SettingsTaskState


class SettingsForm(Widget):
    """Direct controls for user-facing settings."""

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="settings-form"):
            for group, descriptors in _settings_descriptor_groups():
                yield Label(group, classes="settings-section-title")
                for descriptor in descriptors:
                    row_classes = "settings-row"
                    if descriptor.kind == "bool":
                        row_classes = "settings-row settings-row-bool"
                    with HorizontalGroup(
                        id=f"setting-row-{descriptor.key}",
                        classes=row_classes,
                    ):
                        yield Label(descriptor.title, classes="setting-label")
                        yield _setting_control(descriptor)
            yield Label("Storage", classes="settings-section-title")
            with HorizontalGroup(id="setting-row-config", classes="settings-row"):
                yield Label("Config file", classes="setting-label")
                yield Static("", id="setting-value-config", classes="setting-value")

    def update_statuses(self, validation: TaskValidation) -> None:
        for section in validation.sections:
            row = self.query_one(f"#setting-row-{section.key}", HorizontalGroup)
            row.set_class(section.status == "warning", "settings-row-warning")
            row.set_class(section.status == "blocked", "settings-row-blocked")
            if section.key == "config":
                self.query_one("#setting-value-config", Static).update(section.summary)

    def update_values(self, settings: SettingsTaskState) -> None:
        for descriptor in SETTING_DESCRIPTORS:
            control_id = f"#setting-control-{descriptor.key}"
            if descriptor.kind == "enum":
                select = self.query_one(control_id, Select)
                options = _select_options(settings, descriptor)
                with select.prevent(Select.Changed):
                    select.set_options(options)
                    select.value = _select_value(settings, descriptor, options)
                    select.disabled = not bool(options)
            elif descriptor.kind == "bool":
                switch = self.query_one(control_id, Switch)
                with switch.prevent(Switch.Changed):
                    switch.value = bool(settings.setting_value(descriptor.key))
            elif descriptor.kind in {"path", "save_path"}:
                self.query_one(control_id, Button).label = descriptor.action_label
                self.query_one(f"#setting-value-{descriptor.key}", Static).update(
                    settings.display_value(descriptor.key)
                )
            else:
                field = self.query_one(control_id, Input)
                field.value = settings.edit_value(descriptor.key)


def _settings_descriptor_groups() -> tuple[tuple[str, list[SettingDescriptor]], ...]:
    groups: dict[str, list[SettingDescriptor]] = {}
    for descriptor in SETTING_DESCRIPTORS:
        groups.setdefault(descriptor.group, []).append(descriptor)
    return tuple(groups.items())


def _setting_control(descriptor: SettingDescriptor) -> Widget:
    control_id = f"setting-control-{descriptor.key}"
    if descriptor.kind == "enum":
        return Select(
            (("Loading", "__loading__"),),
            allow_blank=False,
            value="__loading__",
            compact=True,
            id=control_id,
            classes="settings-control setting-select",
        )
    if descriptor.kind == "bool":
        return Switch(
            False,
            animate=False,
            id=control_id,
            classes="settings-control setting-switch",
        )
    if descriptor.kind in {"path", "save_path"}:
        return HorizontalGroup(
            Static("", id=f"setting-value-{descriptor.key}", classes="setting-value"),
            Button(
                descriptor.action_label,
                id=control_id,
                compact=True,
                classes="settings-control setting-path-button",
            ),
            classes="setting-path-control",
        )
    return Input(
        "",
        placeholder=descriptor.placeholder,
        compact=True,
        id=control_id,
        classes="settings-control setting-input",
    )


def _select_options(
    settings: SettingsTaskState,
    descriptor: SettingDescriptor,
) -> list[tuple[str, str]]:
    options = [(option, option) for option in settings.options.get(descriptor.option_key or "", ())]
    if descriptor.default is None:
        options.insert(0, ("Ask each time", "__none__"))
    current = settings.setting_value(descriptor.key)
    if current is not None and str(current) not in {value for _, value in options}:
        options.append((f"{current} (unsupported)", str(current)))
    return options or [("Unavailable", "__none__")]


def _select_value(
    settings: SettingsTaskState,
    descriptor: SettingDescriptor,
    options: list[tuple[str, str]],
) -> str:
    current = settings.setting_value(descriptor.key)
    value = "__none__" if current is None else str(current)
    if value not in {option_value for _, option_value in options}:
        return options[0][1]
    return value
