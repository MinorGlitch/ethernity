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

"""Adapter-neutral Add Files workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ethernity.workflows.add_files.errors import AddFilesIssue, AddFilesWorkflowError
from ethernity.workflows.add_files.execution import (
    AssessedAddFilesRun,
    assess_prepared_add_files,
    execute_assessed_add_files,
)
from ethernity.workflows.add_files.models import ExecutedAddFilesRun
from ethernity.workflows.add_files.prepare import prepare_add_files_run
from ethernity.workflows.add_files.reporting import (
    NULL_ADD_FILES_REPORTER,
    AddFilesReporter,
)
from ethernity.workflows.add_files.request import AddFilesRequest
from ethernity.workflows.execution import (
    ReplacementRecoveryRequest,
    execute_replacement_recovery,
)
from ethernity.workflows.replacement_recovery.service import (
    replacement_recovery_directory_name,
    require_replacement_recovery_output_available,
)
from ethernity.workflows.shared import api_codes


@dataclass(frozen=True)
class AddFilesAssessment:
    """Authenticated planning assessment returned to application adapters."""

    request: AddFilesRequest
    assessed: AssessedAddFilesRun | None = None
    recovery_sheet_output_dir: Path | None = None
    issues: tuple[AddFilesIssue, ...] = ()

    @property
    def ready(self) -> bool:
        return self.assessed is not None and not self.issues


@dataclass(frozen=True)
class RecoverySheetCreationResult:
    """Outcome of the optional post-publication recovery-sheet step."""

    status: Literal["not_requested", "created", "failed"] = "not_requested"
    output_dir: Path | None = None
    paths: tuple[Path, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class AddFilesExecutionResult:
    """Publication and optional recovery-sheet results returned to application adapters."""

    assessment: AddFilesAssessment
    executed: ExecutedAddFilesRun | None = None
    recovery_sheets: RecoverySheetCreationResult = field(
        default_factory=RecoverySheetCreationResult
    )
    execution_issues: tuple[AddFilesIssue, ...] = ()

    @property
    def issues(self) -> tuple[AddFilesIssue, ...]:
        return self.execution_issues or self.assessment.issues

    @property
    def ok(self) -> bool:
        return self.executed is not None and not self.issues

    @property
    def partial(self) -> bool:
        return self.ok and self.recovery_sheets.status == "failed"


def assess_add_files(request: AddFilesRequest) -> AddFilesAssessment:
    """Plan and validate a request without publishing files."""

    try:
        assessed = assess_prepared_add_files(prepare_add_files_run(request))
    except AddFilesWorkflowError as exc:
        return AddFilesAssessment(request=request, issues=(exc.issue,))
    except (OSError, RuntimeError, ValueError) as exc:
        return AddFilesAssessment(
            request=request,
            issues=(
                AddFilesIssue(
                    code=api_codes.RUNTIME_ERROR,
                    message=str(exc),
                ),
            ),
        )
    recovery_sheet_output_dir = _recovery_sheet_output_dir(request, assessed)
    if recovery_sheet_output_dir is not None:
        try:
            require_replacement_recovery_output_available(recovery_sheet_output_dir)
        except ValueError:
            return AddFilesAssessment(
                request=request,
                assessed=assessed,
                recovery_sheet_output_dir=recovery_sheet_output_dir,
                issues=(
                    AddFilesIssue(
                        code=api_codes.ADD_FILES_RECOVERY_OUTPUT_EXISTS,
                        message=(
                            f"The recovery sheet folder already exists: "
                            f"{recovery_sheet_output_dir}. Remove it or leave new recovery "
                            "sheets off."
                        ),
                        details={"path": str(recovery_sheet_output_dir)},
                    ),
                ),
            )
    return AddFilesAssessment(
        request=request,
        assessed=assessed,
        recovery_sheet_output_dir=recovery_sheet_output_dir,
    )


def execute_add_files(
    assessment: AddFilesAssessment,
    *,
    config_path: str | None = None,
    nonce: str | None = None,
    reporter: AddFilesReporter = NULL_ADD_FILES_REPORTER,
) -> AddFilesExecutionResult:
    """Publish the exact payload approved by a successful assessment."""

    if not assessment.ready or assessment.assessed is None:
        execution_issues = (
            ()
            if assessment.issues
            else (
                AddFilesIssue(
                    code=api_codes.RUNTIME_ERROR,
                    message="Add Files must pass assessment before execution.",
                ),
            )
        )
        return AddFilesExecutionResult(
            assessment=assessment,
            execution_issues=execution_issues,
        )
    try:
        executed = execute_assessed_add_files(
            assessment.assessed,
            config_path=config_path,
            nonce=nonce,
            reporter=reporter,
        )
    except AddFilesWorkflowError as exc:
        return AddFilesExecutionResult(assessment=assessment, execution_issues=(exc.issue,))
    except (OSError, RuntimeError, ValueError) as exc:
        return AddFilesExecutionResult(
            assessment=assessment,
            execution_issues=(AddFilesIssue(code=api_codes.RUNTIME_ERROR, message=str(exc)),),
        )
    recovery_sheets = _create_recovery_sheets(assessment, executed)
    return AddFilesExecutionResult(
        assessment=assessment,
        executed=executed,
        recovery_sheets=recovery_sheets,
    )


def _recovery_sheet_output_dir(
    request: AddFilesRequest,
    assessed: AssessedAddFilesRun,
) -> Path | None:
    if not request.create_recovery_sheets or request.output_dir is None:
        return None
    update_folder = Path(request.output_dir).expanduser()
    update_name = update_folder.name or "update"
    sheets_parent = update_folder.parent / f"{update_name}-recovery-sheets"
    return sheets_parent / replacement_recovery_directory_name(assessed.encrypted.doc_id)


def _create_recovery_sheets(
    assessment: AddFilesAssessment,
    executed: ExecutedAddFilesRun,
) -> RecoverySheetCreationResult:
    request = assessment.request
    output_dir = assessment.recovery_sheet_output_dir
    if not request.create_recovery_sheets or output_dir is None:
        return RecoverySheetCreationResult()
    try:
        result = execute_replacement_recovery(
            ReplacementRecoveryRequest(
                config_path=Path(request.config_path) if request.config_path is not None else None,
                paper_size=executed.output_settings.config.paper_size,
                design=executed.output_settings.config.design_name,
                frames=(*executed.prepared.source_frames, *executed.result.recovery_frames),
                passphrase=executed.prepared.encryption_passphrase,
                extension_doc_hash=executed.result.doc_hash.hex(),
                expected_head_doc_hash=executed.result.doc_hash.hex(),
                output_dir=output_dir,
                shard_threshold=request.recovery_threshold,
                shard_count=request.recovery_sheet_count,
                create_passphrase_shards=True,
                create_signing_key_shards=False,
            )
        )
    except Exception as exc:
        return RecoverySheetCreationResult(
            status="failed",
            output_dir=output_dir,
            error=str(exc),
        )
    return RecoverySheetCreationResult(
        status="created",
        output_dir=output_dir,
        paths=result.shard_paths,
    )


__all__ = [
    "assess_add_files",
    "execute_add_files",
    "AddFilesAssessment",
    "AddFilesExecutionResult",
    "AddFilesIssue",
    "AddFilesRequest",
    "AddFilesWorkflowError",
    "RecoverySheetCreationResult",
]
