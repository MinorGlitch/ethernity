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

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalGroup, Vertical, VerticalGroup
from textual.widget import Widget
from textual.widgets import (
    Button,
    ContentSwitcher,
    Input,
    Label,
    MaskedInput,
    Select,
    Static,
    Switch,
)

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.widgets.actions import ActionButton, inline_action_group
from ethernity.app.widgets.form import FormScroll, FormSelect
from ethernity.app.widgets.static_text import update_static_text
from ethernity.app.widgets.workbench import WorkbenchStep, WorkbenchSteps
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.page_sizes import paper_size_display_name
from ethernity.render.designs import supported_paper_size_names
from ethernity.tasks.models import TaskIssue, TaskValidation
from ethernity.tasks.presentation.models import InlineNoticePresentation
from ethernity.tasks.presentation.presentation_values import middle_truncate_path
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
SETTINGS_LABELS = {
    "Printing": "Print",
    "Backup defaults": "Backup",
    "Recovery defaults": "Recovery",
    "Security defaults": "Security",
}
DEFAULT_RECOVERY_THRESHOLD = 2
DEFAULT_RECOVERY_COUNT = 3
INVERTED_SWITCHES = frozenset({"ui_no_color", "ui_no_animations"})


DESCRIPTORS = {descriptor.key: descriptor for descriptor in SETTING_DESCRIPTORS}
SETTING_LABELS = {
    "qr_error": "Error correction",
    "ui_no_color": "Color output",
    "ui_no_animations": "Animations",
    "qr_chunk_size": "Payload size (bytes)",
    "extension_chunk_min": "Minimum",
    "extension_chunk_target": "Target",
    "extension_chunk_max": "Maximum",
    "backup_payload_codec": "Compression",
    "backup_qr_payload_codec": "Backup QR codes",
    "add_files_qr_payload_codec": "Update QR codes",
    "backup_shard_threshold": "Sheets required",
    "backup_shard_count": "Sheets created",
    "backup_signing_key_shard_threshold": "Sheets required",
    "backup_signing_key_shard_count": "Sheets created",
}
# Each row uses the same field component; the groups only decide what belongs together.
SETTINGS_SECTIONS = {
    "Printing": (("PDF defaults", (("render_style", "page_size"),)),),
    "Backup defaults": (
        ("Folders", (("backup_base_dir",), ("backup_output_dir",), ("add_files_base_dir",))),
    ),
    "Recovery defaults": (
        ("Recovery sheets", (("backup_shard_threshold", "backup_shard_count"),)),
        ("Restored files", (("recover_output",),)),
    ),
    "Security defaults": (
        ("Signing key", (("backup_signing_key_mode",),)),
        (
            "Separate recovery sheets",
            (("backup_signing_key_shard_threshold", "backup_signing_key_shard_count"),),
        ),
    ),
    "Advanced": (
        ("QR codes", (("qr_error", "qr_chunk_size"),)),
        (
            "Update chunks / bytes",
            (("extension_chunk_min", "extension_chunk_target", "extension_chunk_max"),),
        ),
        (
            "Encoding",
            (("backup_payload_codec",), ("backup_qr_payload_codec", "add_files_qr_payload_codec")),
        ),
        ("Command output", (("ui_quiet", "ui_no_color"),)),
        ("Application", (("ui_no_animations", "ui_show_internals"), ("debug_max_bytes",))),
    ),
}


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
            yield Static("", id="settings-focus-help", markup=False)
            yield Static("", id="settings-save-status", classes="field-text", markup=False)
            yield Button("Retry save", id="settings-retry-save", classes="settings-control")
        with Horizontal(id="settings-body"):
            yield WorkbenchSteps(id="settings-categories", title="SETTINGS", numbered=False)
            with Vertical(id="settings-form"):
                with HorizontalGroup(id="settings-heading"):
                    yield Static("Print", id="settings-title", classes="field-text")
                    yield Button("Reset section", id="settings-reset-section")
                with ContentSwitcher(
                    initial=_settings_pane_id(SETTINGS_GROUP_ORDER[0]), id="settings-pages"
                ):
                    for group, sections in SETTINGS_SECTIONS.items():
                        with FormScroll(id=_settings_pane_id(group), classes="settings-page"):
                            if group == "Recovery defaults":
                                yield Static("", id="settings-recovery-summary", markup=False)
                            for title, rows in sections:
                                with VerticalGroup(classes="settings-section"):
                                    yield Static(title, classes="settings-section-title")
                                    for keys in rows:
                                        with HorizontalGroup(classes="settings-fields"):
                                            for key in keys:
                                                yield SettingField(DESCRIPTORS[key])
                    with FormScroll(id=SETTINGS_CONFIG_PANE_ID, classes="settings-page"):
                        with VerticalGroup(id="setting-row-config", classes="settings-section"):
                            yield Static("Settings file", classes="settings-section-title")
                            yield Static("", id="setting-value-config", markup=False)
                            yield inline_action_group(
                                ActionButton(
                                    "Copy path", "settings-copy-config", classes="settings-control"
                                ),
                                ActionButton(
                                    "Open folder",
                                    "settings-open-config",
                                    classes="settings-control",
                                ),
                            )
                        yield Button(
                            "Reset all settings",
                            id="settings-reset-all",
                            classes="settings-control",
                        )

    def on_mount(self) -> None:
        self.show_group(SETTINGS_GROUP_ORDER[0])

    @property
    def active_group(self) -> str:
        current = self.query_one(ContentSwitcher).current
        return next(
            (group for group in SETTINGS_GROUP_ORDER if _settings_pane_id(group) == current),
            "Config file",
        )

    @property
    def active_pane(self) -> FormScroll:
        return self.query_one(f"#{self.query_one(ContentSwitcher).current}", FormScroll)

    def show_group(self, group: str) -> None:
        if group not in (*SETTINGS_GROUP_ORDER, "Config file"):
            raise ValueError(f"Unknown settings group: {group}")
        self.query_one(ContentSwitcher).current = (
            SETTINGS_CONFIG_PANE_ID if group == "Config file" else _settings_pane_id(group)
        )
        update_static_text(
            self.query_one("#settings-title", Static), SETTINGS_LABELS.get(group, group)
        )
        self.query_one("#settings-reset-section").display = group != "Config file"
        self.query_one(WorkbenchSteps).sync(
            tuple(
                WorkbenchStep(key, SETTINGS_LABELS.get(key, key))
                for key in (*SETTINGS_GROUP_ORDER, "Config file")
            ),
            group,
            locked=False,
        )
        update_static_text(self.query_one("#settings-focus-help", Static), "")

    def on_workbench_steps_selected(self, event: WorkbenchSteps.Selected) -> None:
        event.stop()
        self.show_group(event.key)
        self.call_after_refresh(self.focus_active)

    def focus_active(self) -> None:
        """Return to the first editable control in the current category."""
        controls = list(self.active_pane.query(".settings-control"))
        if controls:
            controls[0].focus()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        field = next(
            (parent for parent in event.widget.ancestors if isinstance(parent, SettingField)), None
        )
        update_static_text(
            self.query_one("#settings-focus-help", Static),
            _field_help(field.descriptor) if field is not None else "",
        )

    def update_statuses(self, validation: TaskValidation) -> None:
        issues_by_section: dict[str, TaskIssue] = {}
        for issue in validation.issues:
            if issue.section is None:
                continue
            current = issues_by_section.get(issue.section)
            if current is None or issue.severity == "error":
                issues_by_section[issue.section] = issue
        for field in self.query(SettingField):
            field.show_issue(issues_by_section.get(field.descriptor.key))
        config = next((section for section in validation.sections if section.key == "config"), None)
        if config is not None:
            update_static_text(
                self.query_one("#setting-value-config", Static),
                middle_truncate_path(config.summary),
            )

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
                    value = bool(settings.setting_value(descriptor.key))
                    switch.value = not value if descriptor.key in INVERTED_SWITCHES else value
            elif descriptor.kind in {"path", "save_path"}:
                self.query_one(control_id, Button).label = descriptor.action_label
                update_static_text(
                    self.query_one(f"#setting-value-{descriptor.key}", Static),
                    settings.display_value(descriptor.key),
                )
            else:
                field = self.query_one(control_id, Input)
                if not field.has_focus or write_locked:
                    with field.prevent(Input.Changed):
                        field.value = settings.edit_value(descriptor.key)
            marker = self.query_one(f"#setting-marker-{descriptor.key}", Static)
            if settings.setting_is_default(descriptor.key):
                marker_text = ""
            else:
                marker_text = "Custom"
            update_static_text(marker, marker_text)
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

    def on_switch_changed(self, event: Switch.Changed) -> None:
        # Present positive labels while preserving the stored no_color/no_animations flags.
        key = (event.switch.id or "").removeprefix("setting-control-")
        if key in INVERTED_SWITCHES:
            event.stop()
            self._settings_app().settings_controller.apply_switch(key, not event.value)

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
        if button_id == "settings-reset-section":
            event.stop()
            self._settings_app().settings_controller.reset_group(self.active_group)
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


def _settings_pane_id(group: str) -> str:
    return "settings-pane-" + group.lower().replace(" ", "-")


class SettingField(VerticalGroup):
    """Own the label, editor, custom marker and actionable issue as one field."""

    def __init__(self, descriptor: SettingDescriptor) -> None:
        super().__init__(id=f"setting-row-{descriptor.key}", classes="settings-row")
        self.descriptor = descriptor

    def compose(self) -> ComposeResult:
        descriptor = self.descriptor
        with HorizontalGroup(classes="setting-label-row"):
            yield Label(
                SETTING_LABELS.get(descriptor.key, descriptor.title), classes="setting-label"
            )
            yield Static(
                "", id=f"setting-marker-{descriptor.key}", classes="setting-marker", markup=False
            )
        yield _setting_control(descriptor)
        yield InlineNotice(id=f"setting-help-{descriptor.key}", classes="setting-help")

    def show_issue(self, issue: TaskIssue | None) -> None:
        self.query_one(InlineNotice).sync_presentation(
            InlineNoticePresentation(issue.message, tone=issue.severity) if issue else None
        )


def _field_help(descriptor: SettingDescriptor) -> str:
    return {
        "ui_no_color": "Use color in scriptable command output.",
        "ui_no_animations": "Animate terminal transitions.",
    }.get(descriptor.key, descriptor.prompt)


def _setting_control(descriptor: SettingDescriptor) -> Widget:
    control_id = f"setting-control-{descriptor.key}"
    if descriptor.kind == "enum":
        return FormSelect(
            (("Loading", "__loading__"),),
            allow_blank=False,
            value="__loading__",
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
                classes="field-text setting-value",
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
