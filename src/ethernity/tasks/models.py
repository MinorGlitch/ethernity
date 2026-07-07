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

from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

TaskSectionStatus = Literal["missing", "ready", "warning", "blocked"]
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


class TaskAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    enabled: bool = True
    disabled_reason: str | None = None


class TaskValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    sections: tuple[TaskSection, ...]
    issues: tuple[TaskIssue, ...] = ()

    @property
    def ready(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


class TaskExecutionPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: str
    output_paths: tuple[Path, ...] = Field(default_factory=tuple)
    writes_files: bool = True


class TaskExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    message: str
    output_paths: tuple[Path, ...] = Field(default_factory=tuple)


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
