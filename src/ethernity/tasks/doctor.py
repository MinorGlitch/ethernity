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

import sys
import tempfile
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ethernity.cli.features.kit.workflow import DEFAULT_KIT_BUNDLE_NAME
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


class DoctorTaskState(BaseModel):
    """Local setup checks for terminal users."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    write_probe_dir: Path = Field(default_factory=lambda: Path.cwd())

    def sections(self) -> tuple[TaskSection, ...]:
        checks = self._checks()
        return tuple(
            TaskSection(
                key=check.code.lower(),
                title=check.title,
                status=check.status,
                summary=check.summary,
            )
            for check in checks
        )

    def validate_task(self) -> TaskValidation:
        return TaskValidation(sections=self.sections())

    def preview(self) -> TaskPreview:
        checks = self._checks()
        warnings = tuple(
            TaskIssue(
                code=check.code,
                message=check.summary,
                severity="warning" if check.status == "warning" else "error",
                section=check.code.lower(),
            )
            for check in checks
            if check.status in {"warning", "blocked"}
        )
        return TaskPreview(
            title="Setup check",
            items=tuple(PreviewItem(label=check.title, detail=check.summary) for check in checks),
            warnings=warnings,
            writes_files=False,
        )

    def execution_plan(self) -> TaskExecutionPlan:
        return TaskExecutionPlan(
            summary="Check local runtime, rendering, scanning, resources, and write access",
            writes_files=False,
        )

    def execute(self) -> TaskExecutionResult:
        checks = self._checks()
        has_errors = any(check.status == "blocked" for check in checks)
        has_warnings = any(check.status == "warning" for check in checks)
        if has_errors:
            message = "Setup check found blockers."
        elif has_warnings:
            message = "Setup check found warnings."
        else:
            message = "Setup check passed."
        return TaskExecutionResult(ok=not has_errors, message=message)

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.preview().warnings

    def _checks(self) -> tuple[_DoctorCheck, ...]:
        return (
            self._python_check(),
            self._library_check(),
            self._rendering_check(),
            self._scanner_check(),
            self._resources_check(),
            self._write_permission_check(),
        )

    def _python_check(self) -> _DoctorCheck:
        version_text = ".".join(str(part) for part in sys.version_info[:3])
        if sys.version_info >= (3, 11):
            return _DoctorCheck("PYTHON", "Python runtime", "ready", version_text)
        return _DoctorCheck("PYTHON", "Python runtime", "blocked", f"{version_text}; need 3.11+")

    def _library_check(self) -> _DoctorCheck:
        required = ("textual", "rich", "click", "pydantic")
        missing = [name for name in required if _package_version(name) is None]
        if missing:
            return _DoctorCheck(
                "TERMINAL_LIBS",
                "Terminal libraries",
                "blocked",
                "Missing " + ", ".join(missing),
            )
        versions = ", ".join(f"{name} {_package_version(name)}" for name in required)
        return _DoctorCheck("TERMINAL_LIBS", "Terminal libraries", "ready", versions)

    def _rendering_check(self) -> _DoctorCheck:
        try:
            import ethernity.render.direct_pdf  # noqa: F401
        except Exception as exc:
            return _DoctorCheck("RENDERING", "PDF rendering", "blocked", str(exc))
        return _DoctorCheck("RENDERING", "PDF rendering", "ready", "Direct renderer available")

    def _scanner_check(self) -> _DoctorCheck:
        if _package_version("zxing-cpp") is None:
            return _DoctorCheck("SCANNER", "QR scanning", "warning", "zxing-cpp is unavailable")
        return _DoctorCheck("SCANNER", "QR scanning", "ready", "zxing-cpp available")

    def _resources_check(self) -> _DoctorCheck:
        try:
            kit_bundle = files("ethernity.resources").joinpath("kit", DEFAULT_KIT_BUNDLE_NAME)
            kit_bundle.read_bytes()
            render_styles = files("ethernity.resources").joinpath("templates")
            if not render_styles.is_dir():
                raise FileNotFoundError("render style resources missing")
        except Exception as exc:
            return _DoctorCheck("RESOURCES", "Resources", "warning", str(exc))
        return _DoctorCheck(
            "RESOURCES",
            "Resources",
            "ready",
            "Render styles and recovery kit found",
        )

    def _write_permission_check(self) -> _DoctorCheck:
        try:
            self.write_probe_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.write_probe_dir, delete=True):
                pass
        except OSError as exc:
            return _DoctorCheck("WRITE_ACCESS", "Write access", "blocked", str(exc))
        return _DoctorCheck("WRITE_ACCESS", "Write access", "ready", str(self.write_probe_dir))


@dataclass(frozen=True)
class _DoctorCheck:
    code: str
    title: str
    status: TaskSectionStatus
    summary: str


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None
