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

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, Static, Switch

from ethernity.tasks.models import TaskValidation
from ethernity.tasks.presentation.common import middle_truncate_path
from ethernity.tasks.settings import SETTING_DESCRIPTORS, SettingDescriptor, SettingsTaskState

if TYPE_CHECKING:
    from ethernity.app.application import EthernityApp

ADVANCED_SETTINGS_GROUP = "Advanced QR and payload settings"
SETTINGS_GROUP_ORDER = (
    "Printing",
    "Backup defaults",
    "Recovery defaults",
    "Security defaults",
    ADVANCED_SETTINGS_GROUP,
)


class SettingsForm(Widget):
    """Direct controls for user-facing settings."""

    def __init__(
        self,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
        markup: bool = True,
    ) -> None:
        super().__init__(
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
            markup=markup,
        )
        self._advanced_expanded = False
        self._config_full_path = ""

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="settings-form"):
            for group, descriptors in _settings_descriptor_groups():
                yield Label(group, classes="settings-section-title")
                group_id = _group_reset_id(group)
                with HorizontalGroup(
                    id=f"settings-reset-row-{group_id}",
                    classes="settings-row settings-reset-row",
                ):
                    yield Label("Section defaults", classes="setting-label")
                    yield Static("", classes="setting-value")
                    yield Button(
                        "Restore defaults",
                        id=f"settings-reset-group-{group_id}",
                        compact=True,
                        classes="settings-control setting-path-button settings-reset-button",
                    )
                if group == ADVANCED_SETTINGS_GROUP:
                    with HorizontalGroup(
                        id="settings-advanced-row",
                        classes="settings-row settings-summary-row",
                    ):
                        yield Static(
                            "Advanced: using saved defaults",
                            id="settings-advanced-summary",
                            classes="setting-value",
                        )
                        yield Button(
                            "Show advanced",
                            id="settings-advanced-toggle",
                            compact=True,
                            classes="settings-control setting-path-button",
                        )
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
                        yield Static(
                            "",
                            id=f"setting-marker-{descriptor.key}",
                            classes="setting-marker",
                        )
                    yield Static(
                        descriptor.prompt,
                        id=f"setting-help-{descriptor.key}",
                        classes="setting-help",
                    )
            yield Label("All settings", classes="settings-section-title")
            with HorizontalGroup(
                id="settings-reset-all-row",
                classes="settings-row settings-reset-row",
            ):
                yield Label("All defaults", classes="setting-label")
                yield Static("", classes="setting-value")
                yield Button(
                    "Restore all defaults",
                    id="settings-reset-all",
                    compact=True,
                    classes="settings-control setting-path-button settings-reset-button",
                )
            yield Label("Config file", classes="settings-section-title")
            with HorizontalGroup(
                id="setting-row-config",
                classes="settings-row settings-config-row",
            ):
                yield Label("Config file", classes="setting-label")
                yield Static("", id="setting-value-config", classes="setting-value")
                yield Button(
                    "Copy path",
                    id="settings-copy-config",
                    compact=True,
                    classes="settings-control setting-path-button",
                )
                yield Button(
                    "Open folder",
                    id="settings-open-config",
                    compact=True,
                    classes="settings-control setting-path-button",
                )
            yield Static("", id="settings-save-status", classes="setting-help")

    def update_statuses(self, validation: TaskValidation) -> None:
        for section in validation.sections:
            row = self.query_one(f"#setting-row-{section.key}", HorizontalGroup)
            row.set_class(section.status == "warning", "settings-row-warning")
            row.set_class(section.status == "blocked", "settings-row-blocked")
            if section.key == "config":
                self.query_one("#setting-value-config", Static).update(
                    middle_truncate_path(section.summary)
                )

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
            marker = self.query_one(f"#setting-marker-{descriptor.key}", Static)
            marker.update("" if settings.setting_is_default(descriptor.key) else "Changed")
            marker.set_class(
                not settings.setting_is_default(descriptor.key),
                "setting-marker-changed",
            )
        self._config_full_path = str(settings.execution_plan().output_paths[0])
        self.query_one("#setting-value-config", Static).update(
            middle_truncate_path(self._config_full_path)
        )
        self.query_one("#settings-save-status", Static).update(settings.save_status)
        self.query_one("#settings-advanced-summary", Static).update(_advanced_summary())
        self._update_advanced_visibility()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "settings-advanced-toggle":
            event.stop()
            self._advanced_expanded = not self._advanced_expanded
            self._update_advanced_visibility()
            return
        if button_id == "settings-reset-all":
            event.stop()
            self._owner_app().settings_controller.reset_all()
            return
        if button_id is not None and button_id.startswith("settings-reset-group-"):
            event.stop()
            group = _group_for_reset_id(button_id.removeprefix("settings-reset-group-"))
            if group is None:
                self.app.notify("That settings section was not found.", severity="warning")
                return
            self._owner_app().settings_controller.reset_group(group)
            return
        if button_id == "settings-copy-config":
            event.stop()
            self.app.copy_to_clipboard(self._config_full_path)
            self.app.notify("Config path copied.")
            return
        if button_id == "settings-open-config":
            event.stop()
            self._open_config_folder()

    def _update_advanced_visibility(self) -> None:
        for descriptor in SETTING_DESCRIPTORS:
            if descriptor.group != ADVANCED_SETTINGS_GROUP:
                continue
            self.query_one(
                f"#setting-row-{descriptor.key}", HorizontalGroup
            ).display = self._advanced_expanded
            self.query_one(
                f"#setting-help-{descriptor.key}", Static
            ).display = self._advanced_expanded
        self.query_one("#settings-advanced-toggle", Button).label = (
            "Hide advanced" if self._advanced_expanded else "Show advanced"
        )

    def _open_config_folder(self) -> None:
        folder = str(self._config_folder())
        command = ["open", folder]
        if sys.platform.startswith("win"):
            command = ["explorer", folder]
        elif sys.platform != "darwin":
            command = ["xdg-open", folder]
        try:
            subprocess.Popen(command)  # noqa: S603
        except OSError as exc:
            self.app.notify(f"Could not open folder: {exc}", severity="error")
            return
        self.app.notify("Opening config folder.")

    def _config_folder(self) -> str:
        if not self._config_full_path:
            return "."
        return str(Path(self._config_full_path).parent)

    def _owner_app(self) -> EthernityApp:
        return cast("EthernityApp", self.app)


def _settings_descriptor_groups() -> tuple[tuple[str, list[SettingDescriptor]], ...]:
    groups: dict[str, list[SettingDescriptor]] = {}
    for descriptor in SETTING_DESCRIPTORS:
        groups.setdefault(descriptor.group, []).append(descriptor)
    ordered = [(group, groups.pop(group)) for group in SETTINGS_GROUP_ORDER if group in groups]
    ordered.extend(groups.items())
    return tuple(ordered)


def _group_reset_id(group: str) -> str:
    characters = [character.lower() if character.isalnum() else "-" for character in group]
    return "".join(characters).strip("-")


def _group_for_reset_id(group_id: str) -> str | None:
    for group, _descriptors in _settings_descriptor_groups():
        if _group_reset_id(group) == group_id:
            return group
    return None


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


def _advanced_summary() -> str:
    return "Advanced: using saved defaults"
