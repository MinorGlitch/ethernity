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
from ethernity.tasks.models import (
    PreviewItem,
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskIssue,
    TaskPreview,
    TaskSection,
    TaskValidation,
)

PaperSize = Literal["A4", "LETTER"]
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


SETTING_DESCRIPTORS: tuple[SettingDescriptor, ...] = (
    SettingDescriptor(
        "render_style",
        ("render", "style"),
        "Printing",
        "Print design",
        "enum",
        "Change",
        "Default print design",
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
        "Default paper size",
        "A4",
        "page_sizes",
        "A4",
    ),
    SettingDescriptor(
        "qr_error",
        ("qr", "error"),
        "QR",
        "Error correction",
        "enum",
        "Change",
        "QR error correction level",
        "M",
        "qr_error_correction",
        "M",
    ),
    SettingDescriptor(
        "qr_chunk_size",
        ("qr", "chunk_size"),
        "QR",
        "Chunk size",
        "int",
        "Change",
        "Preferred ciphertext bytes per QR frame",
        512,
        placeholder="512",
    ),
    SettingDescriptor(
        "extension_chunk_target",
        ("extension", "chunking", "target_size"),
        "Extension Chunking",
        "Target size",
        "int",
        "Change",
        "Target content-defined chunk size for new extension chains",
        16384,
        placeholder="16384",
    ),
    SettingDescriptor(
        "extension_chunk_min",
        ("extension", "chunking", "min_size"),
        "Extension Chunking",
        "Minimum size",
        "int",
        "Change",
        "Minimum content-defined chunk size for new extension chains",
        4096,
        placeholder="4096",
    ),
    SettingDescriptor(
        "extension_chunk_max",
        ("extension", "chunking", "max_size"),
        "Extension Chunking",
        "Maximum size",
        "int",
        "Change",
        "Maximum content-defined chunk size for new extension chains",
        65536,
        placeholder="65536",
    ),
    SettingDescriptor(
        "backup_base_dir",
        ("defaults", "backup", "base_dir"),
        "Backup Defaults",
        "Input base folder",
        "path",
        "Choose",
        "Default folder for backup inputs",
        None,
    ),
    SettingDescriptor(
        "backup_output_dir",
        ("defaults", "backup", "output_dir"),
        "Backup Defaults",
        "Output folder",
        "save_path",
        "Choose",
        "Default folder where backup documents are saved",
        None,
        placeholder="backup-out",
    ),
    SettingDescriptor(
        "backup_shard_threshold",
        ("defaults", "backup", "shard_threshold"),
        "Backup Defaults",
        "Recovery threshold",
        "optional_int",
        "Change",
        "Default recovery document threshold",
        None,
        placeholder="2",
    ),
    SettingDescriptor(
        "backup_shard_count",
        ("defaults", "backup", "shard_count"),
        "Backup Defaults",
        "Recovery documents",
        "optional_int",
        "Change",
        "Default recovery document count",
        None,
        placeholder="3",
    ),
    SettingDescriptor(
        "backup_signing_key_mode",
        ("defaults", "backup", "signing_key_mode"),
        "Backup Defaults",
        "Signing key mode",
        "enum",
        "Change",
        "Default signing key storage mode",
        None,
        "signing_key_modes",
        "embedded",
    ),
    SettingDescriptor(
        "backup_signing_key_shard_threshold",
        ("defaults", "backup", "signing_key_shard_threshold"),
        "Backup Defaults",
        "Signing key threshold",
        "optional_int",
        "Change",
        "Default signing key shard threshold",
        None,
        placeholder="2",
    ),
    SettingDescriptor(
        "backup_signing_key_shard_count",
        ("defaults", "backup", "signing_key_shard_count"),
        "Backup Defaults",
        "Signing key shards",
        "optional_int",
        "Change",
        "Default signing key shard count",
        None,
        placeholder="3",
    ),
    SettingDescriptor(
        "backup_payload_codec",
        ("defaults", "backup", "payload_codec"),
        "Backup Defaults",
        "Payload codec",
        "enum",
        "Change",
        "Default backup payload codec",
        "auto",
        "payload_codecs",
        "auto",
    ),
    SettingDescriptor(
        "backup_qr_payload_codec",
        ("defaults", "backup", "qr_payload_codec"),
        "Backup Defaults",
        "QR payload codec",
        "enum",
        "Change",
        "Default QR payload codec for backup documents",
        "raw",
        "qr_payload_codecs",
        "raw",
    ),
    SettingDescriptor(
        "recover_output",
        ("defaults", "recover", "output"),
        "Restore Defaults",
        "Restore output",
        "save_path",
        "Choose",
        "Default restore output path",
        None,
        placeholder="recovered",
    ),
    SettingDescriptor(
        "extend_base_dir",
        ("defaults", "extend", "base_dir"),
        "Add Files Defaults",
        "Input base folder",
        "path",
        "Choose",
        "Default folder for added files",
        None,
    ),
    SettingDescriptor(
        "extend_unlock_policy",
        ("defaults", "extend", "unlock_policy"),
        "Add Files Defaults",
        "Unlock policy",
        "enum",
        "Change",
        "Default unlock policy for backup updates",
        None,
        "extension_unlock_policies",
        "self-contained",
    ),
    SettingDescriptor(
        "extend_shard_threshold",
        ("defaults", "extend", "shard_threshold"),
        "Add Files Defaults",
        "Recovery threshold",
        "optional_int",
        "Change",
        "Default extension recovery threshold",
        None,
        placeholder="2",
    ),
    SettingDescriptor(
        "extend_shard_count",
        ("defaults", "extend", "shard_count"),
        "Add Files Defaults",
        "Recovery documents",
        "optional_int",
        "Change",
        "Default extension recovery document count",
        None,
        placeholder="3",
    ),
    SettingDescriptor(
        "extend_signing_key_mode",
        ("defaults", "extend", "signing_key_mode"),
        "Add Files Defaults",
        "Signing key mode",
        "enum",
        "Change",
        "Default signing key storage for backup updates",
        None,
        "extension_signing_key_modes",
        "not-stored",
    ),
    SettingDescriptor(
        "extend_signing_key_shard_threshold",
        ("defaults", "extend", "signing_key_shard_threshold"),
        "Add Files Defaults",
        "Signing key threshold",
        "optional_int",
        "Change",
        "Default extension signing key shard threshold",
        None,
        placeholder="2",
    ),
    SettingDescriptor(
        "extend_signing_key_shard_count",
        ("defaults", "extend", "signing_key_shard_count"),
        "Add Files Defaults",
        "Signing key shards",
        "optional_int",
        "Change",
        "Default extension signing key shard count",
        None,
        placeholder="3",
    ),
    SettingDescriptor(
        "extend_qr_payload_codec",
        ("defaults", "extend", "qr_payload_codec"),
        "Add Files Defaults",
        "QR payload codec",
        "enum",
        "Change",
        "Default QR payload codec for backup updates",
        "raw",
        "qr_payload_codecs",
        "raw",
    ),
    SettingDescriptor(
        "ui_quiet",
        ("ui", "quiet"),
        "Terminal UI",
        "Quiet output",
        "bool",
        "Toggle",
        "Default quiet mode for scriptable commands",
        False,
    ),
    SettingDescriptor(
        "ui_no_color",
        ("ui", "no_color"),
        "Terminal UI",
        "No color",
        "bool",
        "Toggle",
        "Disable color by default for scriptable commands",
        False,
    ),
    SettingDescriptor(
        "ui_no_animations",
        ("ui", "no_animations"),
        "Terminal UI",
        "No animations",
        "bool",
        "Toggle",
        "Disable terminal animations by default",
        False,
    ),
    SettingDescriptor(
        "debug_max_bytes",
        ("debug", "max_bytes"),
        "Internals",
        "Preview bytes",
        "optional_int",
        "Change",
        "Maximum internal payload preview bytes",
        1024,
        placeholder="1024",
    ),
    SettingDescriptor(
        "runtime_render_jobs",
        ("runtime", "render_jobs"),
        "Runtime",
        "Render jobs",
        "render_jobs",
        "Change",
        "PDF/QR render concurrency: auto or a positive integer",
        "auto",
        placeholder="auto",
    ),
)


class SettingsTaskState(BaseModel):
    """User-facing settings state backed by the config API."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    config_path: Path | None = None
    values: dict[str, object] = Field(default_factory=dict)
    options: dict[str, tuple[str, ...]] = Field(default_factory=dict)

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
    def paper_size(self) -> PaperSize:
        return "LETTER" if str(self.setting_value("page_size")).upper() == "LETTER" else "A4"

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

    def display_value(self, key: str) -> str:
        descriptor = self.descriptor(key)
        value = self.setting_value(key)
        if descriptor is None:
            return ""
        if value is None or value == "":
            return "Ask each time" if descriptor.kind in {"path", "save_path"} else "Default"
        if descriptor.kind == "bool":
            return "On" if value is True else "Off"
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
                status="ready",
                summary=self.display_value(descriptor.key),
                action_label=descriptor.action_label,
                detail=descriptor.group,
            )
            for descriptor in SETTING_DESCRIPTORS
        ]
        sections.append(
            TaskSection(
                key="config",
                title="Config file",
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
            title="Saved automatically",
            items=(PreviewItem(label="Config file", detail=self._config_summary()),),
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
                    message=f"{descriptor.title} must be a positive integer.",
                    section=descriptor.key,
                ),
            )
        if descriptor.kind == "optional_int" and value is not None and not _is_positive_int(value):
            return (
                TaskIssue(
                    code="SETTINGS_POSITIVE_INTEGER_REQUIRED",
                    message=f"{descriptor.title} must be a positive integer or unset.",
                    section=descriptor.key,
                ),
            )
        if descriptor.kind == "render_jobs" and not (
            value is None or value == "auto" or _is_positive_int(value)
        ):
            return (
                TaskIssue(
                    code="SETTINGS_RENDER_JOBS_INVALID",
                    message="Render jobs must be auto, a positive integer, or unset.",
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
                        message="Extension chunking must satisfy minimum <= target <= maximum.",
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
                label="Add-files recovery",
            )
        )
        issues.extend(
            _paired_count_issues(
                threshold=self.setting_value("extend_signing_key_shard_threshold"),
                count=self.setting_value("extend_signing_key_shard_count"),
                section="extend_signing_key_shard_threshold",
                label="Add-files signing key",
            )
        )
        if self.setting_value("extend_unlock_policy") == "reuse-root" and (
            self.setting_value("extend_shard_threshold") is not None
            or self.setting_value("extend_shard_count") is not None
        ):
            issues.append(
                TaskIssue(
                    code="SETTINGS_EXTEND_REUSE_ROOT_CONFLICT",
                    message="Reuse-root add-files unlock policy cannot set extension shards.",
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
                message=f"{label} threshold and count must be set together.",
                section=section,
            ),
        )
    count_int = cast(int, count)
    threshold_int = cast(int, threshold)
    if count_int < threshold_int:
        return (
            TaskIssue(
                code="SETTINGS_COUNT_BELOW_THRESHOLD",
                message=f"{label} count must be greater than or equal to threshold.",
                section=section,
            ),
        )
    return ()
