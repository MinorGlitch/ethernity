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

from collections.abc import Collection
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ethernity.core.failures import FailureInfo

TaskSectionStatus = Literal["missing", "ready", "optional", "warning", "blocked"]
TaskIssueSeverity = Literal["info", "warning", "error"]


class TaskSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    title: str
    status: TaskSectionStatus
    summary: str
    action_label: str | None = None
    detail: str | None = None


class TaskIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    severity: TaskIssueSeverity = "error"
    section: str | None = None


class TaskValidationError(ValueError):
    """A task issue with an explicit editing destination."""

    def __init__(self, issue: TaskIssue) -> None:
        super().__init__(issue.message)
        self.code = issue.code
        self.section = issue.section


def optional_section_status(
    blocking_issues: Collection[TaskIssue],
    warnings: Collection[TaskIssue],
) -> TaskSectionStatus:
    """Resolve the shared blocked/warning/optional section policy."""

    if blocking_issues:
        return "blocked"
    if warnings:
        return "warning"
    return "optional"


class PreviewItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    detail: str | None = None


class TaskPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    items: tuple[PreviewItem, ...] = ()
    warnings: tuple[TaskIssue, ...] = ()
    writes_files: bool = True


class TaskValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    sections: tuple[TaskSection, ...]
    issues: tuple[TaskIssue, ...] = ()

    @property
    def ready(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def require_ready(self, message: str) -> None:
        if self.ready:
            return
        issue = next((issue for issue in self.issues if issue.severity == "error"), None)
        raise TaskValidationError(issue or TaskIssue(code="TASK_NOT_READY", message=message))


class TaskExecutionPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: str
    read_paths: tuple[Path, ...] = Field(default_factory=tuple)
    output_paths: tuple[Path, ...] = Field(default_factory=tuple)
    writes_files: bool = True
    safety_notes: tuple[str, ...] = Field(default_factory=tuple)
    trust_notes: tuple[str, ...] = Field(default_factory=tuple)
    recovery_notes: tuple[str, ...] = Field(default_factory=tuple)


class TaskResultDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    value: str | int | bool | None | tuple[str, ...]


class TaskExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["succeeded", "partially_succeeded", "failed", "cancelled"]
    message: str
    output_paths: tuple[Path, ...] = Field(default_factory=tuple)
    failure: FailureInfo | None = None
    recovery_check_paths: tuple[Path, ...] = Field(
        default_factory=tuple,
        description="Generated QR-bearing documents to use for a disposable recovery check.",
    )
    details: tuple[TaskResultDetail, ...] = Field(default_factory=tuple)
    next_steps: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status in {"succeeded", "partially_succeeded"}


class TaskDiagnosticBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    content: str
    sensitive_content: str | None = None

    def display_content(self, *, reveal_sensitive: bool) -> str:
        if reveal_sensitive and self.sensitive_content is not None:
            return self.sensitive_content
        return self.content


class TaskDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str = "Internals"
    blocks: tuple[TaskDiagnosticBlock, ...] = ()

    @property
    def has_sensitive_values(self) -> bool:
        return any(block.sensitive_content is not None for block in self.blocks)


class TaskState(Protocol):
    def sections(self) -> tuple[TaskSection, ...]: ...

    def validate_task(self) -> TaskValidation: ...

    def preview(self) -> TaskPreview: ...

    def execution_plan(self) -> TaskExecutionPlan: ...

    def execute(self) -> TaskExecutionResult: ...

    def recoverable_errors(self) -> tuple[TaskIssue, ...]: ...
