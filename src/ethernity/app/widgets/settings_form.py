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
from typing import cast

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, Vertical
from textual.widget import Widget
from textual.widgets import (
    Button,
    Input,
    Label,
    MaskedInput,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.widgets.actions import ActionButton, inline_action_group
from ethernity.app.widgets.static_text import update_static_text
from ethernity.page_sizes import paper_size_display_name
from ethernity.render.designs import supported_paper_size_names
from ethernity.tasks.models import TaskIssue, TaskValidation
from ethernity.tasks.presentation.common import middle_truncate_path
from ethernity.tasks.settings import SETTING_DESCRIPTORS, SettingDescriptor, SettingsTaskState

ADVANCED_SETTINGS_GROUP = "Advanced"
SETTINGS_GROUP_ORDER = (
    "Printing",
    "Backup defaults",
    "Recovery defaults",
    "Security defaults",
    ADVANCED_SETTINGS_GROUP,
)
SETTINGS_CONFIG_PANE_ID = "settings-pane-config"
SETTINGS_TAB_LABELS = {
    "Printing": "Print",
    "Backup defaults": "Backup",
    "Recovery defaults": "Recovery",
    "Security defaults": "Security",
}
DEFAULT_RECOVERY_THRESHOLD = 2
DEFAULT_RECOVERY_COUNT = 3


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
        self._config_full_path = ""
        self._select_options_by_key: dict[str, tuple[tuple[str, str], ...]] = {}

    def compose(self) -> ComposeResult:
        with HorizontalGroup(id="settings-save-row"):
            yield Static("", id="settings-save-status", markup=False)
            yield inline_action_group(
                ActionButton(
                    "Retry save",
                    "settings-retry-save",
                    classes="settings-control settings-retry-button",
                )
            )
        with Vertical(id="settings-form"):
            with TabbedContent(
                id="settings-tabs",
                initial=_settings_pane_id(SETTINGS_GROUP_ORDER[0]),
            ):
                for group, descriptors in _settings_descriptor_groups():
                    with TabPane(_settings_tab_title(group), id=_settings_pane_id(group)):
                        yield _settings_reset_row(group)
                        if group == "Recovery defaults":
                            with HorizontalGroup(
                                id="settings-recovery-summary-row",
                                classes="settings-row settings-summary-row",
                            ):
                                yield Label("Backup recovery method", classes="setting-label")
                                yield Static(
                                    "",
                                    id="settings-recovery-summary",
                                    classes="setting-value",
                                    markup=False,
                                )
                                yield Static("", classes="setting-marker")
                            yield Static(
                                "Applies to new backups only. Existing backup files and recovery "
                                "sheets are not changed.",
                                id="settings-recovery-summary-help",
                                classes="setting-help",
                            )
                        for descriptor in descriptors:
                            yield from _setting_descriptor_widgets(descriptor)
                with TabPane("File", id=SETTINGS_CONFIG_PANE_ID):
                    with HorizontalGroup(
                        id="settings-reset-all-row",
                        classes="settings-row settings-reset-row",
                    ):
                        yield Static("", classes="setting-reset-spacer")
                        yield inline_action_group(
                            ActionButton(
                                "Reset all settings",
                                "settings-reset-all",
                                classes=(
                                    "settings-control setting-path-button settings-reset-button"
                                ),
                            )
                        )
                    with HorizontalGroup(
                        id="setting-row-config",
                        classes="settings-row settings-config-row",
                    ):
                        yield Label("Settings file", classes="setting-label")
                        yield Static(
                            "",
                            id="setting-value-config",
                            classes="setting-value",
                            markup=False,
                        )
                        yield inline_action_group(
                            ActionButton(
                                "Copy path",
                                "settings-copy-config",
                                classes="settings-control setting-path-button",
                            ),
                            ActionButton(
                                "Open folder",
                                "settings-open-config",
                                classes="settings-control setting-path-button",
                            ),
                        )

    def update_statuses(self, validation: TaskValidation) -> None:
        issues_by_section: dict[str, TaskIssue] = {}
        for issue in validation.issues:
            if issue.section is None:
                continue
            current = issues_by_section.get(issue.section)
            if current is None or issue.severity == "error":
                issues_by_section[issue.section] = issue
        for section in validation.sections:
            row = self.query_one(f"#setting-row-{section.key}", HorizontalGroup)
            issue = issues_by_section.get(section.key)
            error = issue if issue is not None and issue.severity == "error" else None
            warning = issue if issue is not None and issue.severity == "warning" else None
            row.set_class(error is None and section.status == "warning", "settings-row-warning")
            row.set_class(error is not None or section.status == "blocked", "settings-row-blocked")
            if section.key == "config":
                update_static_text(
                    self.query_one("#setting-value-config", Static),
                    middle_truncate_path(section.summary),
                )
                continue
            descriptor = next(
                (item for item in SETTING_DESCRIPTORS if item.key == section.key),
                None,
            )
            if descriptor is None:
                continue
            help_text = descriptor.prompt
            if error is not None:
                help_text = f"Fix: {error.message}"
            elif warning is not None:
                help_text = warning.message
            help_widget = self.query_one(f"#setting-help-{section.key}", Static)
            update_static_text(help_widget, help_text)
            help_widget.set_class(error is not None, "setting-help-error")
            help_widget.set_class(warning is not None, "setting-help-warning")

    def update_values(
        self,
        settings: SettingsTaskState,
        *,
        write_locked: bool = False,
    ) -> None:
        for descriptor in SETTING_DESCRIPTORS:
            control_id = f"#setting-control-{descriptor.key}"
            if descriptor.kind == "enum":
                select = self.query_one(control_id, Select)
                options = _select_options(settings, descriptor)
                with select.prevent(Select.Changed):
                    self._set_select_options(select, descriptor.key, options)
                    select.value = _select_value(settings, descriptor, options)
                    select.disabled = not bool(options)
            elif descriptor.kind == "bool":
                switch = self.query_one(control_id, Switch)
                with switch.prevent(Switch.Changed):
                    switch.value = bool(settings.setting_value(descriptor.key))
            elif descriptor.kind in {"path", "save_path"}:
                self.query_one(control_id, Button).label = descriptor.action_label
                update_static_text(
                    self.query_one(f"#setting-value-{descriptor.key}", Static),
                    settings.display_value(descriptor.key),
                )
            else:
                field = self.query_one(control_id, Input)
                field.value = settings.edit_value(descriptor.key)
            marker = self.query_one(f"#setting-marker-{descriptor.key}", Static)
            if settings.setting_is_default(descriptor.key):
                marker_text = ""
            elif settings.setting_is_risky_custom(descriptor.key):
                marker_text = "Warning"
            else:
                marker_text = "Custom"
            update_static_text(marker, marker_text)
            marker.set_class(
                not settings.setting_is_default(descriptor.key),
                "setting-marker-changed",
            )
        self._config_full_path = str(settings.execution_plan().output_paths[0])
        update_static_text(
            self.query_one("#setting-value-config", Static),
            middle_truncate_path(self._config_full_path),
        )
        save_status = "Locked while task runs" if write_locked else settings.save_status
        status = self.query_one("#settings-save-status", Static)
        update_static_text(status, save_status)
        status.set_class(settings.save_pending or write_locked, "settings-status-pending")
        status.set_class(
            save_status
            in {
                "Not saved",
                "Save failed",
            },
            "settings-status-error",
        )
        retry = self.query_one("#settings-retry-save", Button)
        retry.display = settings.save_pending and not write_locked
        retry.disabled = write_locked
        update_static_text(
            self.query_one("#settings-recovery-summary", Static),
            _recovery_summary(settings),
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "settings-retry-save":
            event.stop()
            self._settings_app().settings_controller.retry_save()
            return
        if button_id == "settings-reset-all":
            event.stop()
            await self._settings_app().settings_controller.request_reset_all()
            return
        if button_id is not None and button_id.startswith("settings-reset-group-"):
            event.stop()
            group = _group_for_reset_id(button_id.removeprefix("settings-reset-group-"))
            if group is None:
                self.app.notify("Settings section not found.", severity="warning")
                return
            self._settings_app().settings_controller.reset_group(group)
            return
        if button_id == "settings-copy-config":
            event.stop()
            self.app.copy_to_clipboard(self._config_full_path)
            self.app.notify("Settings file path copied.")
            return
        if button_id == "settings-open-config":
            event.stop()
            self._open_config_folder()

    def _set_select_options(
        self,
        select: Select[str],
        key: str,
        options: list[tuple[str, str]],
    ) -> None:
        option_key = tuple(options)
        if self._select_options_by_key.get(key) == option_key:
            return
        select.set_options(options)
        self._select_options_by_key[key] = option_key

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
        self.app.notify("Opening settings folder.")

    def _config_folder(self) -> str:
        if not self._config_full_path:
            return "."
        return str(Path(self._config_full_path).parent)

    def _settings_app(self) -> EthernityAppContext:
        return cast(EthernityAppContext, self.app)


def _settings_descriptor_groups() -> tuple[tuple[str, list[SettingDescriptor]], ...]:
    groups: dict[str, list[SettingDescriptor]] = {}
    for descriptor in SETTING_DESCRIPTORS:
        groups.setdefault(descriptor.group, []).append(descriptor)
    ordered = [(group, groups.pop(group)) for group in SETTINGS_GROUP_ORDER if group in groups]
    ordered.extend(groups.items())
    return tuple(ordered)


def _settings_pane_id(group: str) -> str:
    return f"settings-pane-{_group_reset_id(group)}"


def _settings_tab_title(group: str) -> str:
    return SETTINGS_TAB_LABELS.get(group, group)


def _group_reset_id(group: str) -> str:
    characters = [character.lower() if character.isalnum() else "-" for character in group]
    return "".join(characters).strip("-")


def _group_for_reset_id(group_id: str) -> str | None:
    for group, _descriptors in _settings_descriptor_groups():
        if _group_reset_id(group) == group_id:
            return group
    return None


def _settings_reset_row(group: str) -> Widget:
    group_id = _group_reset_id(group)
    return HorizontalGroup(
        Static("", classes="setting-reset-spacer"),
        inline_action_group(
            ActionButton(
                "Reset tab",
                f"settings-reset-group-{group_id}",
                classes="settings-control setting-path-button settings-reset-button",
            )
        ),
        id=f"settings-reset-row-{group_id}",
        classes="settings-row settings-reset-row",
    )


def _setting_descriptor_widgets(descriptor: SettingDescriptor) -> tuple[Widget, Widget]:
    row_classes = "settings-row"
    if descriptor.kind == "bool":
        row_classes = "settings-row settings-row-bool"
    return (
        HorizontalGroup(
            Label(descriptor.title, classes="setting-label"),
            _setting_control(descriptor),
            Static(
                "",
                id=f"setting-marker-{descriptor.key}",
                classes="setting-marker",
                markup=False,
            ),
            id=f"setting-row-{descriptor.key}",
            classes=row_classes,
        ),
        Static(
            descriptor.prompt,
            id=f"setting-help-{descriptor.key}",
            classes="setting-help",
            markup=False,
        ),
    )


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
            Static(
                "",
                id=f"setting-value-{descriptor.key}",
                classes="setting-value",
                markup=False,
            ),
            inline_action_group(
                ActionButton(
                    descriptor.action_label,
                    control_id,
                    classes="settings-control setting-path-button",
                ),
            ),
            classes="setting-path-control",
        )
    if descriptor.kind in {"int", "optional_int"}:
        return MaskedInput(
            "0000000000",
            value="",
            placeholder=descriptor.placeholder,
            valid_empty=descriptor.kind == "optional_int",
            compact=True,
            id=control_id,
            classes="settings-control setting-input",
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
    configured_options = settings.options.get(descriptor.option_key or "", ())
    if descriptor.option_key == "page_sizes":
        supported = frozenset(supported_paper_size_names(settings.design))
        configured_options = tuple(option for option in configured_options if option in supported)
    options = [(_setting_option_label(descriptor, option), option) for option in configured_options]
    if descriptor.default is None:
        options.insert(0, (descriptor.empty_label, "__none__"))
    current = settings.setting_value(descriptor.key)
    if current is not None and str(current) not in {value for _, value in options}:
        options.append((f"{current} (unsupported)", str(current)))
    return options or [("Unavailable", "__none__")]


def _setting_option_label(descriptor: SettingDescriptor, option: str) -> str:
    labels = {
        "payload_codecs": {
            "auto": "Automatic (recommended)",
            "raw": "No compression",
            "gzip": "gzip",
        },
        "qr_payload_codecs": {
            "raw": "Raw (recommended)",
            "base64": "Base64",
        },
        "signing_key_modes": {
            "embedded": "Embedded",
            "sharded": "Separate recovery sheets",
        },
        "extension_unlock_policies": {
            "self-contained": "New recovery sheets",
            "reuse-root": "Use original recovery set",
        },
        "extension_signing_key_modes": {
            "not-stored": "Do not store",
            "sharded": "Separate recovery sheets",
        },
    }
    if descriptor.option_key == "page_sizes":
        return paper_size_display_name(option)
    return labels.get(descriptor.option_key or "", {}).get(option, _enum_option_label(option))


def _enum_option_label(option: str) -> str:
    if option in {"L", "M", "Q", "H"}:
        return option
    return option.replace("_", " ").replace("-", " ").title()


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


def _recovery_summary(settings: SettingsTaskState) -> str:
    threshold = _positive_int_or_default(
        settings.setting_value("backup_shard_threshold"),
        DEFAULT_RECOVERY_THRESHOLD,
    )
    count = _positive_int_or_default(
        settings.setting_value("backup_shard_count"),
        DEFAULT_RECOVERY_COUNT,
    )
    return f"{count} recovery sheets; any {threshold} required"


def _positive_int_or_default(value: object, default: int) -> int:
    return value if isinstance(value, int) and value > 0 else default
