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

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from ethernity.config import apply_api_config_patch, get_api_config_snapshot
from ethernity.core.app_paths import DEFAULT_CONFIG_FILENAME, user_config_file_path
from ethernity.page_sizes import DEFAULT_PAPER_SIZE_NAME, PaperSizeName, resolve_paper_size
from ethernity.tasks.models import (
    PreviewItem,
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskIssue,
    TaskPreview,
    TaskSection,
    TaskValidation,
)

SettingKind = Literal["enum", "int", "optional_int", "path", "save_path", "bool", "render_jobs"]


@dataclass(frozen=True)
class SettingDescriptor:
    key: str
    path: tuple[str, ...]
    group: str
    title: str
    kind: SettingKind
    action_label: str
    prompt: str
    default: object
    option_key: str | None = None
    placeholder: str = ""
    empty_label: str = "Automatic"


SETTING_DESCRIPTORS: tuple[SettingDescriptor, ...] = (
    SettingDescriptor(
        "render_style",
        ("render", "style"),
        "Printing",
        "Print design",
        "enum",
        "Change",
        "Visual style for new backup and recovery PDFs.",
        "sentinel",
        "render_styles",
        "sentinel",
    ),
    SettingDescriptor(
        "page_size",
        ("page", "size"),
        "Printing",
        "Paper size",
        "enum",
        "Change",
        "Page size for new backup and recovery PDFs.",
        DEFAULT_PAPER_SIZE_NAME,
        "page_sizes",
        DEFAULT_PAPER_SIZE_NAME,
    ),
    SettingDescriptor(
        "qr_error",
        ("qr", "error"),
        "Advanced",
        "QR correction",
        "enum",
        "Change",
        "Higher correction tolerates more damage but may add QR codes.",
        "M",
        "qr_error_correction",
        "M",
    ),
    SettingDescriptor(
        "qr_chunk_size",
        ("qr", "chunk_size"),
        "Advanced",
        "QR density",
        "int",
        "Change",
        "More bytes can reduce page count but make QR codes harder to scan.",
        512,
        placeholder="512",
    ),
    SettingDescriptor(
        "extension_chunk_target",
        ("extension", "chunking", "target_size"),
        "Advanced",
        "Update chunk target",
        "int",
        "Change",
        "Typical chunk size in bytes. Keep all three values matched to the backup chain.",
        16384,
        placeholder="16384",
    ),
    SettingDescriptor(
        "extension_chunk_min",
        ("extension", "chunking", "min_size"),
        "Advanced",
        "Update chunk minimum",
        "int",
        "Change",
        "Smallest chunk the update may create, in bytes.",
        4096,
        placeholder="4096",
    ),
    SettingDescriptor(
        "extension_chunk_max",
        ("extension", "chunking", "max_size"),
        "Advanced",
        "Update chunk maximum",
        "int",
        "Change",
        "Largest chunk the update may create, in bytes.",
        65536,
        placeholder="65536",
    ),
    SettingDescriptor(
        "backup_base_dir",
        ("defaults", "backup", "base_dir"),
        "Backup defaults",
        "Input base folder",
        "path",
        "Choose folder...",
        "Automatic uses the common parent of the selected files.",
        None,
        empty_label="Automatic",
    ),
    SettingDescriptor(
        "backup_output_dir",
        ("defaults", "backup", "output_dir"),
        "Backup defaults",
        "Backup output folder",
        "save_path",
        "Choose folder...",
        "Automatic creates a folder named for the backup ID in the current folder.",
        None,
        placeholder="custom-folder",
        empty_label="Automatic: named for backup ID",
    ),
    SettingDescriptor(
        "backup_shard_threshold",
        ("defaults", "backup", "shard_threshold"),
        "Recovery defaults",
        "Backup: sheets required",
        "optional_int",
        "Change",
        "Sheets needed to restore a new backup.",
        None,
        placeholder="2",
    ),
    SettingDescriptor(
        "backup_shard_count",
        ("defaults", "backup", "shard_count"),
        "Recovery defaults",
        "Backup: sheets created",
        "optional_int",
        "Change",
        "Recovery sheets created for a new backup.",
        None,
        placeholder="3",
    ),
    SettingDescriptor(
        "backup_signing_key_mode",
        ("defaults", "backup", "signing_key_mode"),
        "Security defaults",
        "Backup signing key",
        "enum",
        "Change",
        "Encrypt the key in the backup, or protect it with separate recovery sheets.",
        None,
        "signing_key_modes",
        "embedded",
        empty_label="Use built-in default (Embedded)",
    ),
    SettingDescriptor(
        "backup_signing_key_shard_threshold",
        ("defaults", "backup", "signing_key_shard_threshold"),
        "Security defaults",
        "Backup key sheets required",
        "optional_int",
        "Change",
        "Sheets needed to recover the backup signing key.",
        None,
        placeholder="2",
    ),
    SettingDescriptor(
        "backup_signing_key_shard_count",
        ("defaults", "backup", "signing_key_shard_count"),
        "Security defaults",
        "Backup key sheets created",
        "optional_int",
        "Change",
        "Sheets created for the backup signing key.",
        None,
        placeholder="3",
    ),
    SettingDescriptor(
        "backup_payload_codec",
        ("defaults", "backup", "payload_codec"),
        "Advanced",
        "Backup compression",
        "enum",
        "Change",
        "Automatic selects the smaller safe format.",
        "auto",
        "payload_codecs",
        "auto",
    ),
    SettingDescriptor(
        "backup_qr_payload_codec",
        ("defaults", "backup", "qr_payload_codec"),
        "Advanced",
        "Backup QR encoding",
        "enum",
        "Change",
        "Raw works with most scanners. Use Base64 only when required.",
        "raw",
        "qr_payload_codecs",
        "raw",
    ),
    SettingDescriptor(
        "recover_output",
        ("defaults", "recover", "output"),
        "Recovery defaults",
        "Restore output folder",
        "save_path",
        "Choose folder...",
        "When no folder is saved, each restore asks.",
        None,
        placeholder="recovered",
        empty_label="Ask every time",
    ),
    SettingDescriptor(
        "extend_base_dir",
        ("defaults", "extend", "base_dir"),
        "Backup defaults",
        "Update base folder",
        "path",
        "Choose folder...",
        "Automatic uses the common parent of the files being added.",
        None,
        empty_label="Automatic",
    ),
    SettingDescriptor(
        "extend_unlock_policy",
        ("defaults", "extend", "unlock_policy"),
        "Recovery defaults",
        "Update recovery",
        "enum",
        "Change",
        "Create recovery sheets for each update, or use the original recovery set.",
        None,
        "extension_unlock_policies",
        "self-contained",
        empty_label="Use built-in default (New recovery sheets)",
    ),
    SettingDescriptor(
        "extend_shard_threshold",
        ("defaults", "extend", "shard_threshold"),
        "Recovery defaults",
        "Update: sheets required",
        "optional_int",
        "Change",
        "Sheets needed to recover a self-contained update.",
        None,
        placeholder="2",
    ),
    SettingDescriptor(
        "extend_shard_count",
        ("defaults", "extend", "shard_count"),
        "Recovery defaults",
        "Update: sheets created",
        "optional_int",
        "Change",
        "Recovery sheets created for a self-contained update.",
        None,
        placeholder="3",
    ),
    SettingDescriptor(
        "extend_signing_key_mode",
        ("defaults", "extend", "signing_key_mode"),
        "Security defaults",
        "Update signing key",
        "enum",
        "Change",
        "Do not store the key, or protect it with separate recovery sheets.",
        None,
        "extension_signing_key_modes",
        "not-stored",
        empty_label="Use built-in default (Do not store)",
    ),
    SettingDescriptor(
        "extend_signing_key_shard_threshold",
        ("defaults", "extend", "signing_key_shard_threshold"),
        "Security defaults",
        "Update key sheets required",
        "optional_int",
        "Change",
        "Sheets needed to recover the update signing key.",
        None,
        placeholder="2",
    ),
    SettingDescriptor(
        "extend_signing_key_shard_count",
        ("defaults", "extend", "signing_key_shard_count"),
        "Security defaults",
        "Update key sheets created",
        "optional_int",
        "Change",
        "Sheets created for the update signing key.",
        None,
        placeholder="3",
    ),
    SettingDescriptor(
        "extend_qr_payload_codec",
        ("defaults", "extend", "qr_payload_codec"),
        "Advanced",
        "Update QR encoding",
        "enum",
        "Change",
        "Raw works with most scanners. Use Base64 only when required.",
        "raw",
        "qr_payload_codecs",
        "raw",
    ),
    SettingDescriptor(
        "ui_quiet",
        ("ui", "quiet"),
        "Advanced",
        "Quiet output",
        "bool",
        "Toggle",
        "Suppress routine output from scriptable commands.",
        False,
    ),
    SettingDescriptor(
        "ui_no_color",
        ("ui", "no_color"),
        "Advanced",
        "Disable color",
        "bool",
        "Toggle",
        "Turn off color in scriptable command output.",
        False,
    ),
    SettingDescriptor(
        "ui_no_animations",
        ("ui", "no_animations"),
        "Advanced",
        "Disable animations",
        "bool",
        "Toggle",
        "Turn off terminal animations.",
        False,
    ),
    SettingDescriptor(
        "ui_show_internals",
        ("ui", "show_internals"),
        "Advanced",
        "Show backup diagnostics",
        "bool",
        "Toggle",
        "Show a Diagnostics action while creating a backup.",
        False,
    ),
    SettingDescriptor(
        "debug_max_bytes",
        ("debug", "max_bytes"),
        "Advanced",
        "Payload preview limit",
        "optional_int",
        "Change",
        "Maximum bytes shown in internal payload previews.",
        1024,
        placeholder="1024",
    ),
    SettingDescriptor(
        "runtime_render_jobs",
        ("runtime", "render_jobs"),
        "Advanced",
        "Render jobs",
        "render_jobs",
        "Change",
        "Parallel PDF and QR render jobs. Automatic uses available CPU.",
        "auto",
        placeholder="auto",
    ),
)

RISKY_CUSTOM_SETTING_MESSAGES: dict[str, str] = {
    "qr_chunk_size": (
        "A custom QR size changes page count and scan reliability. Test a printed code first."
    ),
    "extension_chunk_target": (
        "Target size must match the backup chain, or Ethernity may be unable to apply the update."
    ),
    "extension_chunk_min": (
        "Minimum size must match the chain, or Ethernity may be unable to apply the update."
    ),
    "extension_chunk_max": (
        "Maximum size must match the chain, or Ethernity may be unable to apply the update."
    ),
}


class SettingsTaskState(BaseModel):
    """User-facing settings state backed by the config API."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    config_path: Path | None = None
    values: dict[str, object] = Field(default_factory=dict)
    options: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    save_status: str = "Saved"
    save_pending: bool = False

    @classmethod
    def from_current(cls, config_path: Path | None = None) -> SettingsTaskState:
        snapshot = get_api_config_snapshot(config_path)
        return cls(
            config_path=config_path,
            values=copy.deepcopy(snapshot.values),
            options=_snapshot_options(snapshot.options),
        )

    @property
    def design(self) -> str:
        return str(self.setting_value("render_style") or "sentinel")

    @property
    def paper_size(self) -> PaperSizeName:
        return resolve_paper_size(
            str(self.setting_value("page_size") or DEFAULT_PAPER_SIZE_NAME)
        ).name

    @property
    def backup_output_dir(self) -> Path | None:
        return _path_or_none(self.setting_value("backup_output_dir"))

    @backup_output_dir.setter
    def backup_output_dir(self, value: Path | None) -> None:
        self.set_setting_value("backup_output_dir", str(value) if value is not None else None)

    @property
    def available_designs(self) -> tuple[str, ...]:
        return self.options.get("render_styles", ())

    def descriptors(self) -> tuple[SettingDescriptor, ...]:
        return SETTING_DESCRIPTORS

    def descriptor(self, key: str) -> SettingDescriptor | None:
        return next(
            (descriptor for descriptor in SETTING_DESCRIPTORS if descriptor.key == key), None
        )

    def setting_value(self, key: str) -> object:
        descriptor = self.descriptor(key)
        if descriptor is None:
            return None
        return _nested_value(self.values, descriptor.path)

    def set_setting_value(self, key: str, value: object) -> None:
        descriptor = self.descriptor(key)
        if descriptor is None:
            return
        _set_nested_value(self.values, descriptor.path, value)

    def clear_setting(self, key: str) -> None:
        descriptor = self.descriptor(key)
        if descriptor is not None:
            self.set_setting_value(key, descriptor.default)

    def setting_is_default(self, key: str) -> bool:
        descriptor = self.descriptor(key)
        if descriptor is None:
            return True
        return self.setting_value(key) == descriptor.default

    def setting_is_risky_custom(self, key: str) -> bool:
        return key in RISKY_CUSTOM_SETTING_MESSAGES and not self.setting_is_default(key)

    def reset_group(self, group: str) -> bool:
        matched = False
        for descriptor in SETTING_DESCRIPTORS:
            if descriptor.group != group:
                continue
            self.clear_setting(descriptor.key)
            matched = True
        return matched

    def reset_all(self) -> None:
        for descriptor in SETTING_DESCRIPTORS:
            self.clear_setting(descriptor.key)

    def display_value(self, key: str) -> str:
        descriptor = self.descriptor(key)
        value = self.setting_value(key)
        if descriptor is None:
            return ""
        if value is None or value == "":
            return descriptor.empty_label
        if descriptor.kind == "bool":
            return "On" if value is True else "Off"
        if str(value) == "auto":
            return "Automatic"
        return str(value)

    def edit_value(self, key: str) -> str:
        value = self.setting_value(key)
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def path_value(self, key: str) -> Path | None:
        return _path_or_none(self.setting_value(key))

    def sections(self) -> tuple[TaskSection, ...]:
        sections = [
            TaskSection(
                key=descriptor.key,
                title=descriptor.title,
                status="warning" if self.setting_is_risky_custom(descriptor.key) else "ready",
                summary=self.display_value(descriptor.key),
                action_label=descriptor.action_label,
                detail=descriptor.group,
            )
            for descriptor in SETTING_DESCRIPTORS
        ]
        sections.append(
            TaskSection(
                key="config",
                title="Settings file",
                status="ready",
                summary=self._config_summary(),
                detail="Storage",
            )
        )
        return tuple(sections)

    def validate_task(self) -> TaskValidation:
        issues = list(self._local_issues())
        return TaskValidation(sections=self.sections(), issues=tuple(issues))

    def preview(self) -> TaskPreview:
        return TaskPreview(
            title=self.save_status,
            items=(PreviewItem(label="Settings file", detail=self._config_summary()),),
        )

    def execution_plan(self) -> TaskExecutionPlan:
        return TaskExecutionPlan(
            summary=f"Save settings to {self._config_summary()}",
            output_paths=(Path(self._config_summary()),),
            writes_files=True,
        )

    def execute(self) -> TaskExecutionResult:
        validation = self.validate_task()
        if not validation.ready:
            first_issue = validation.issues[0] if validation.issues else None
            message = first_issue.message if first_issue is not None else "Settings are not ready."
            raise ValueError(message)

        snapshot = apply_api_config_patch(self.config_path, self._config_patch())
        return TaskExecutionResult(
            ok=True,
            message="Settings saved.",
            output_paths=(Path(snapshot.path),),
        )

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def _config_patch(self) -> dict[str, object]:
        return {"values": copy.deepcopy(self.values)}

    def _config_summary(self) -> str:
        if self.config_path is not None:
            return str(self.config_path)
        return str(user_config_file_path(DEFAULT_CONFIG_FILENAME))

    def _local_issues(self) -> tuple[TaskIssue, ...]:
        issues: list[TaskIssue] = []
        for descriptor in SETTING_DESCRIPTORS:
            issues.extend(self._setting_issues(descriptor))
        issues.extend(self._relationship_issues())
        error_sections = {issue.section for issue in issues if issue.severity == "error"}
        for key, message in RISKY_CUSTOM_SETTING_MESSAGES.items():
            if key in error_sections or not self.setting_is_risky_custom(key):
                continue
            issues.append(
                TaskIssue(
                    code="SETTINGS_RISKY_CUSTOM_VALUE",
                    message=message,
                    severity="warning",
                    section=key,
                )
            )
        return tuple(issues)

    def _setting_issues(self, descriptor: SettingDescriptor) -> tuple[TaskIssue, ...]:
        value = self.setting_value(descriptor.key)
        if descriptor.kind == "enum":
            options = self.options.get(descriptor.option_key or "", ())
            if value is None:
                return ()
            if options and str(value) not in options:
                return (
                    TaskIssue(
                        code="SETTINGS_UNSUPPORTED_VALUE",
                        message=f"{descriptor.title} must be one of: {', '.join(options)}.",
                        section=descriptor.key,
                    ),
                )
        if descriptor.kind == "int" and not _is_positive_int(value):
            return (
                TaskIssue(
                    code="SETTINGS_POSITIVE_INTEGER_REQUIRED",
                    message=f"{descriptor.title} must be a positive whole number.",
                    section=descriptor.key,
                ),
            )
        if descriptor.kind == "optional_int" and value is not None and not _is_positive_int(value):
            return (
                TaskIssue(
                    code="SETTINGS_POSITIVE_INTEGER_REQUIRED",
                    message=f"{descriptor.title} must be a positive whole number or blank.",
                    section=descriptor.key,
                ),
            )
        if descriptor.kind == "render_jobs" and not (
            value is None or value == "auto" or _is_positive_int(value)
        ):
            return (
                TaskIssue(
                    code="SETTINGS_RENDER_JOBS_INVALID",
                    message="Use auto, a positive whole number, or blank.",
                    section=descriptor.key,
                ),
            )
        return ()

    def _relationship_issues(self) -> tuple[TaskIssue, ...]:
        issues: list[TaskIssue] = []
        chunk_min = self.setting_value("extension_chunk_min")
        chunk_target = self.setting_value("extension_chunk_target")
        chunk_max = self.setting_value("extension_chunk_max")
        if all(_is_positive_int(value) for value in (chunk_min, chunk_target, chunk_max)):
            chunk_min_int = cast(int, chunk_min)
            chunk_target_int = cast(int, chunk_target)
            chunk_max_int = cast(int, chunk_max)
            if not chunk_min_int <= chunk_target_int <= chunk_max_int:
                issues.append(
                    TaskIssue(
                        code="SETTINGS_CHUNKING_ORDER_INVALID",
                        message="Update chunk sizes must follow minimum <= target <= maximum.",
                        section="extension_chunk_target",
                    )
                )
        issues.extend(
            _paired_count_issues(
                threshold=self.setting_value("backup_shard_threshold"),
                count=self.setting_value("backup_shard_count"),
                section="backup_shard_threshold",
                label="Backup recovery",
            )
        )
        issues.extend(
            _paired_count_issues(
                threshold=self.setting_value("backup_signing_key_shard_threshold"),
                count=self.setting_value("backup_signing_key_shard_count"),
                section="backup_signing_key_shard_threshold",
                label="Backup signing key",
            )
        )
        issues.extend(
            _paired_count_issues(
                threshold=self.setting_value("extend_shard_threshold"),
                count=self.setting_value("extend_shard_count"),
                section="extend_shard_threshold",
                label="Update recovery",
            )
        )
        issues.extend(
            _paired_count_issues(
                threshold=self.setting_value("extend_signing_key_shard_threshold"),
                count=self.setting_value("extend_signing_key_shard_count"),
                section="extend_signing_key_shard_threshold",
                label="Update signing key",
            )
        )
        if self.setting_value("extend_unlock_policy") == "reuse-root" and (
            self.setting_value("extend_shard_threshold") is not None
            or self.setting_value("extend_shard_count") is not None
        ):
            issues.append(
                TaskIssue(
                    code="SETTINGS_EXTEND_REUSE_ROOT_CONFLICT",
                    message=(
                        "The original recovery set cannot be combined with separate update "
                        "recovery counts."
                    ),
                    section="extend_unlock_policy",
                )
            )
        return tuple(issues)


def _snapshot_options(options: dict[str, object]) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for key, value in options.items():
        if isinstance(value, list):
            result[key] = tuple(str(item) for item in value)
    return result


def _nested_value(values: dict[str, object], path: tuple[str, ...]) -> object:
    current: object = values
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _set_nested_value(values: dict[str, object], path: tuple[str, ...], value: object) -> None:
    current = values
    for key in path[:-1]:
        next_value = current.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            current[key] = next_value
        current = next_value
    current[path[-1]] = value


def _path_or_none(value: object) -> Path | None:
    if isinstance(value, str) and value:
        return Path(value)
    return None


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _paired_count_issues(
    *,
    threshold: object,
    count: object,
    section: str,
    label: str,
) -> tuple[TaskIssue, ...]:
    if threshold is None and count is None:
        return ()
    if not _is_positive_int(threshold) or not _is_positive_int(count):
        return (
            TaskIssue(
                code="SETTINGS_PAIRED_COUNT_REQUIRED",
                message=(
                    f"Set both the required and created sheet counts for {label.lower()}, "
                    "or leave both blank."
                ),
                section=section,
            ),
        )
    count_int = cast(int, count)
    threshold_int = cast(int, threshold)
    if count_int < threshold_int:
        return (
            TaskIssue(
                code="SETTINGS_COUNT_BELOW_THRESHOLD",
                message=f"{label}: sheets created must be at least the number required.",
                section=section,
            ),
        )
    return ()
