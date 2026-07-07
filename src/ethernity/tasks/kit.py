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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ethernity.cli.features.kit.workflow import DEFAULT_KIT_OUTPUT, render_kit_qr_document
from ethernity.tasks.models import (
    PreviewItem,
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskIssue,
    TaskPreview,
    TaskSection,
    TaskValidation,
)

KitVariant = Literal["lean", "scanner"]
PaperSize = Literal["A4", "LETTER"]


class PrintKitTaskState(BaseModel):
    """Beginner-facing state for printing the offline recovery kit."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    output_path: Path = Field(default_factory=lambda: Path(DEFAULT_KIT_OUTPUT))
    variant: KitVariant = "lean"
    paper_size: PaperSize = "A4"
    design: str = "sentinel"
    chunk_size: int | None = None

    @model_validator(mode="after")
    def _validate_chunk_size(self) -> PrintKitTaskState:
        if self.chunk_size is not None and self.chunk_size <= 0:
            raise ValueError("QR sizing value must be positive")
        return self

    def sections(self) -> tuple[TaskSection, ...]:
        return (
            TaskSection(
                key="output",
                title="Save PDF as",
                status="ready",
                summary=str(self.output_path),
                action_label="Choose PDF path...",
            ),
            TaskSection(
                key="layout",
                title="Print layout",
                status="ready",
                summary=f"{self.paper_size} {self.design}",
                action_label="Change layout",
            ),
            TaskSection(
                key="variant",
                title="Kit type",
                status="ready",
                summary="Camera scanner included"
                if self.variant == "scanner"
                else "Lean offline kit",
                action_label="Change variant",
            ),
        )

    def validate_task(self) -> TaskValidation:
        return TaskValidation(sections=self.sections())

    def preview(self) -> TaskPreview:
        items = [
            PreviewItem(label="Recovery kit PDF", detail=str(self.output_path)),
            PreviewItem(label="Offline browser kit", detail=self._variant_summary()),
            PreviewItem(label="QR sizing", detail=str(self.chunk_size or "automatic")),
        ]
        warnings = (
            TaskIssue(
                code="FINAL_REVIEW_REQUIRED",
                message="Nothing will be written until final review.",
                severity="warning",
            ),
        )
        return TaskPreview(title="Recovery kit to create", items=tuple(items), warnings=warnings)

    def execution_plan(self) -> TaskExecutionPlan:
        return TaskExecutionPlan(
            summary=f"Create recovery kit PDF at {self.output_path}",
            output_paths=(self.output_path,),
            writes_files=True,
        )

    def execute(self) -> TaskExecutionResult:
        result = render_kit_qr_document(
            output_path=self.output_path,
            config_path=None,
            paper_size=self.paper_size,
            design=self.design,
            variant=self.variant,
            chunk_size=self.chunk_size,
            quiet=True,
        )
        return TaskExecutionResult(
            ok=True,
            message=(
                f"Recovery kit created with {result.chunk_count} QR code(s) "
                f"from {result.bytes_total} bytes."
            ),
            output_paths=(result.output_path,),
        )

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def _variant_summary(self) -> str:
        if self.variant == "scanner":
            return "includes camera scanning support"
        return "smaller kit, manual QR scanning"
