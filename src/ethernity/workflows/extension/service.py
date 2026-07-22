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

"""Public extension workflow facade."""

from __future__ import annotations

from dataclasses import dataclass

from ethernity.workflows.extension.errors import ExtensionIssue, ExtensionWorkflowError
from ethernity.workflows.extension.execution import (
    AssessedExtendRun,
    assess_prepared_extend,
    execute_assessed_extend,
    execute_prepared_extend,
    execute_staged_extension_publish,
    run_extend,
    validate_prepared_extend_render,
)
from ethernity.workflows.extension.models import (
    EXTENSION_INPUT_REQUIRED,
    EXTENSION_INVALID_POLICY,
    EXTENSION_MAIN_CARRIER_INVALID,
    EXTENSION_NO_CHANGES,
    EXTENSION_SHARD_CARRIER_INVALID,
    EXTENSION_TOO_LARGE,
    EncryptedPreparedExtension,
    ExecutedExtendRun,
    ExtensionArtifactRenderer,
    ExtensionPassphraseShards,
    ExtensionSigningKeyShards,
    PreparedExtendRun,
    PreparedExtensionPublishPlan,
    PublishedExtensionResult,
    ResolvedExtendRuntime,
    ReuseRootPassphraseShards,
)
from ethernity.workflows.extension.planning import (
    ResolvedExtensionPlan,
    ValidatedAppendAuthority,
    ValidatedChainLineage,
)
from ethernity.workflows.extension.prepare import (
    assemble_prepared_extension_document,
    encrypt_prepared_extension_document,
    prepare_extend_run,
    prepare_extend_run_from_state,
    prepare_staged_extension_publish,
)
from ethernity.workflows.extension.reporting import (
    NULL_EXTENSION_REPORTER,
    ExtensionReporter,
)
from ethernity.workflows.extension.request import ExtensionRequest
from ethernity.workflows.extension.runtime import resolve_extend_runtime


@dataclass(frozen=True)
class ExtensionAssessment:
    """Planning and render assessment returned to application adapters."""

    request: ExtensionRequest
    assessed: AssessedExtendRun | None = None
    issues: tuple[ExtensionIssue, ...] = ()

    @property
    def ready(self) -> bool:
        return self.assessed is not None and not self.issues


@dataclass(frozen=True)
class ExtensionExecutionResult:
    """Typed extension execution outcome returned to application adapters."""

    assessment: ExtensionAssessment
    executed: ExecutedExtendRun | None = None
    issues: tuple[ExtensionIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return self.executed is not None and not self.issues


def assess_extension(request: ExtensionRequest) -> ExtensionAssessment:
    """Plan and validate a request without publishing artifacts."""

    try:
        assessed = assess_prepared_extend(prepare_extend_run(request))
    except ExtensionWorkflowError as exc:
        return ExtensionAssessment(request=request, issues=(exc.issue,))
    except (OSError, RuntimeError, ValueError) as exc:
        return ExtensionAssessment(
            request=request,
            issues=(
                ExtensionIssue(
                    code="EXTENSION_ASSESSMENT_FAILED",
                    message=str(exc),
                ),
            ),
        )
    return ExtensionAssessment(request=request, assessed=assessed)


def execute_extension(
    assessment: ExtensionAssessment,
    *,
    config_path: str | None = None,
    nonce: str | None = None,
    reporter: ExtensionReporter = NULL_EXTENSION_REPORTER,
) -> ExtensionExecutionResult:
    """Publish the exact payload approved by a successful assessment."""

    if not assessment.ready or assessment.assessed is None:
        issues = assessment.issues or (
            ExtensionIssue(
                code="EXTENSION_NOT_ASSESSED",
                message="Extension request must pass assessment before execution.",
            ),
        )
        return ExtensionExecutionResult(assessment=assessment, issues=issues)
    try:
        executed = execute_assessed_extend(
            assessment.assessed,
            config_path=config_path,
            nonce=nonce,
            reporter=reporter,
        )
    except ExtensionWorkflowError as exc:
        return ExtensionExecutionResult(assessment=assessment, issues=(exc.issue,))
    except (OSError, RuntimeError, ValueError) as exc:
        return ExtensionExecutionResult(
            assessment=assessment,
            issues=(ExtensionIssue(code="EXTENSION_EXECUTION_FAILED", message=str(exc)),),
        )
    return ExtensionExecutionResult(assessment=assessment, executed=executed)


__all__ = [
    "assess_extension",
    "execute_extension",
    "ExtensionAssessment",
    "ExtensionExecutionResult",
    "ExtensionIssue",
    "ExtensionRequest",
    "ExtensionWorkflowError",
    "ExecutedExtendRun",
    "EncryptedPreparedExtension",
    "EXTENSION_INVALID_POLICY",
    "EXTENSION_INPUT_REQUIRED",
    "EXTENSION_MAIN_CARRIER_INVALID",
    "EXTENSION_NO_CHANGES",
    "EXTENSION_SHARD_CARRIER_INVALID",
    "EXTENSION_TOO_LARGE",
    "ExtensionArtifactRenderer",
    "ExtensionPassphraseShards",
    "ExtensionSigningKeyShards",
    "ReuseRootPassphraseShards",
    "AssessedExtendRun",
    "PreparedExtensionPublishPlan",
    "PreparedExtendRun",
    "PublishedExtensionResult",
    "ResolvedExtendRuntime",
    "ResolvedExtensionPlan",
    "ValidatedAppendAuthority",
    "ValidatedChainLineage",
    "assemble_prepared_extension_document",
    "execute_staged_extension_publish",
    "execute_prepared_extend",
    "encrypt_prepared_extension_document",
    "prepare_extend_run",
    "prepare_extend_run_from_state",
    "prepare_staged_extension_publish",
    "resolve_extend_runtime",
    "run_extend",
    "validate_prepared_extend_render",
]
