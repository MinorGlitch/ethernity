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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ethernity.cli.features.kit.workflow import DEFAULT_KIT_OUTPUT, render_kit_qr_document
from ethernity.page_sizes import (
    DEFAULT_PAPER_SIZE_NAME,
    PaperSizeName,
    paper_size_display_name,
    resolve_paper_size,
)
from ethernity.tasks.file_summary import format_count
from ethernity.tasks.models import (
    PreviewItem,
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskIssue,
    TaskPreview,
    TaskSection,
    TaskSectionStatus,
    TaskValidation,
)
from ethernity.tasks.output_checks import (
    existing_output_warning,
    selected_output_status,
)
from ethernity.tasks.page_layout import KIT_RENDER_DOC_TYPES, require_workflow_page_size

KitVariant = Literal["lean", "scanner"]


class PrintKitTaskState(BaseModel):
    """Beginner-facing state for printing the offline recovery kit."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    output_path: Path = Field(default_factory=lambda: Path(DEFAULT_KIT_OUTPUT))
    config_path: Path | None = None
    variant: KitVariant = "lean"
    paper_size: PaperSizeName = DEFAULT_PAPER_SIZE_NAME
    design: str = "sentinel"
    chunk_size: int | None = None

    @field_validator("paper_size")
    @classmethod
    def _validate_paper_size(cls, value: str) -> PaperSizeName:
        return resolve_paper_size(value).name

    @model_validator(mode="after")
    def _validate_chunk_size(self) -> PrintKitTaskState:
        require_workflow_page_size(
            self.design,
            self.paper_size,
            candidate_doc_types=KIT_RENDER_DOC_TYPES,
        )
        if self.chunk_size is not None and self.chunk_size <= 0:
            raise ValueError("QR sizing value must be positive")
        return self

    def sections(self) -> tuple[TaskSection, ...]:
        return (
            TaskSection(
                key="output",
                title="Save PDF as",
                status=self._output_status(),
                summary=self._output_summary(),
                action_label="Choose PDF file...",
            ),
            TaskSection(
                key="layout",
                title="Print setup",
                status="ready",
                summary=f"{paper_size_display_name(self.paper_size)}, {self.design.title()}",
                action_label="Change layout",
            ),
            TaskSection(
                key="variant",
                title="Kit type",
                status="ready",
                summary="Camera scanning included"
                if self.variant == "scanner"
                else "Smaller offline kit",
                action_label="Change variant",
            ),
            TaskSection(
                key="qr",
                title="QR sizing",
                status="warning" if self.chunk_size is not None else "optional",
                summary=self._qr_sizing_summary(),
                action_label="Set QR sizing...",
            ),
        )

    def validate_task(self) -> TaskValidation:
        output_issue = self._output_issue()
        return TaskValidation(
            sections=self.sections(),
            issues=(output_issue,) if output_issue is not None else (),
        )

    def preview(self) -> TaskPreview:
        items = [
            PreviewItem(label="PDF file", detail=self._output_summary()),
            PreviewItem(label="Kit type", detail=self._variant_summary()),
            PreviewItem(label="QR sizing", detail=self._qr_sizing_summary()),
        ]
        warnings = (
            *self._output_warnings(),
            *self._qr_sizing_warnings(),
        )
        return TaskPreview(title="Recovery kit to create", items=tuple(items), warnings=warnings)

    def execution_plan(self) -> TaskExecutionPlan:
        return TaskExecutionPlan(
            summary=f"Create recovery kit PDF at {self._output_summary()}",
            output_paths=(self.output_path,),
            writes_files=True,
            safety_notes=(
                "Ethernity will create the PDF at the selected path. Its parent folder must be "
                "writable.",
            ),
            recovery_notes=(
                "Recovery kit contains offline restore tools; it does not replace backup "
                "documents or recovery sheets.",
            ),
        )

    def execute(self) -> TaskExecutionResult:
        validation = self.validate_task()
        if not validation.ready:
            raise ValueError(validation.issues[0].message)

        result = render_kit_qr_document(
            output_path=self.output_path,
            config_path=self.config_path,
            paper_size=self.paper_size,
            design=self.design,
            variant=self.variant,
            chunk_size=self.chunk_size,
            quiet=True,
        )
        return TaskExecutionResult(
            ok=True,
            message=(
                f"Recovery kit created with {format_count(result.chunk_count, 'QR code')} "
                f"from {format_count(result.bytes_total, 'byte')}."
            ),
            output_paths=(result.output_path,),
        )

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def _variant_summary(self) -> str:
        if self.variant == "scanner":
            return "Camera scanning included"
        return "Smaller kit for manual scanning"

    def _output_summary(self) -> str:
        issue = self._output_issue()
        if issue is not None:
            return issue.message
        if self.output_path.is_absolute():
            summary = str(self.output_path)
        elif self.output_path.parent == Path("."):
            summary = f"{self.output_path} (current folder)"
        else:
            summary = f"{self.output_path} (relative)"
        if self.output_path.exists():
            return f"Existing PDF: {summary}"
        return summary

    def _output_status(self) -> TaskSectionStatus:
        if self._output_issue() is not None:
            return "blocked"
        status = selected_output_status(self.output_path)
        if status == "missing":
            return "ready"
        return status

    def _output_issue(self) -> TaskIssue | None:
        if not self.output_path.name:
            return TaskIssue(
                code="KIT_OUTPUT_REQUIRED",
                message="Choose a PDF file name.",
                section="output",
            )
        if self.output_path.exists() and self.output_path.is_dir():
            return TaskIssue(
                code="KIT_OUTPUT_IS_DIRECTORY",
                message="Choose a PDF file, not a folder.",
                section="output",
            )
        if self.output_path.suffix.lower() != ".pdf":
            return TaskIssue(
                code="KIT_OUTPUT_PDF_REQUIRED",
                message="Use a .pdf file name.",
                section="output",
            )
        parent = self.output_path.parent
        if parent.exists() and not parent.is_dir():
            return TaskIssue(
                code="KIT_OUTPUT_PARENT_INVALID",
                message="The PDF's parent path is not a folder.",
                section="output",
            )
        return None

    def _output_warnings(self) -> tuple[TaskIssue, ...]:
        if self._output_issue() is not None:
            return ()
        return existing_output_warning(
            self.output_path,
            code="KIT_OUTPUT_EXISTS",
            target="pdf_file",
        )

    def _qr_sizing_summary(self) -> str:
        if self.chunk_size is None:
            return "Automatic (recommended)"
        return f"{self.chunk_size} bytes per code"

    def _qr_sizing_warnings(self) -> tuple[TaskIssue, ...]:
        if self.chunk_size is None:
            return ()
        return (
            TaskIssue(
                code="KIT_CUSTOM_QR_SIZING",
                message="Custom sizing can change page count and make codes harder to scan.",
                severity="warning",
                section="qr",
            ),
        )
