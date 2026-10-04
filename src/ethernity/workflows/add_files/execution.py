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

"""Publish prepared extension documents."""

from __future__ import annotations

import os
import secrets
import shutil
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path

from ethernity import render as render_module
from ethernity.extensions.staging import (
    preflight_extension_publish_target,
    validate_staged_extension_dir,
)
from ethernity.publication import (
    discard_staging_directory,
    publish_staged_directory,
)
from ethernity.render.layout_debug import layout_debug_json_path
from ethernity.workflows.add_files import (
    output_settings as add_files_output_settings,
    rendering as add_files_rendering,
)
from ethernity.workflows.add_files.capacity import require_rebuildable_result
from ethernity.workflows.add_files.document_validation import validate_staged_extension_documents
from ethernity.workflows.add_files.errors import AddFilesWorkflowError
from ethernity.workflows.add_files.models import (
    EncryptedExtension,
    ExecutedAddFilesRun,
    ExtensionOutputSettings,
    ExtensionPublication,
    ExtensionRenderResult,
    PreparedAddFilesRun,
    PublishedExtensionResult,
)
from ethernity.workflows.add_files.prepare import (
    encrypt_prepared_extension_document,
    prepare_extension_publish,
)
from ethernity.workflows.add_files.reporting import (
    NULL_ADD_FILES_REPORTER,
    AddFilesReporter,
)
from ethernity.workflows.shared import api_codes

DirectoryIdentity = tuple[int, int]


@dataclass(frozen=True)
class AssessedAddFilesRun:
    """Authenticated, encrypted extension state approved for execution."""

    prepared: PreparedAddFilesRun
    output_settings: ExtensionOutputSettings
    encrypted: EncryptedExtension

    def __deepcopy__(self, _memo: dict[int, object]) -> AssessedAddFilesRun:
        """Keep one immutable reviewed payload across task snapshot copies."""

        return self


def _publish_staged_extension(
    plan: ExtensionPublication,
    *,
    output_settings: ExtensionOutputSettings,
    reporter: AddFilesReporter = NULL_ADD_FILES_REPORTER,
) -> PublishedExtensionResult:
    """Render into a staged extension directory, validate, and promote atomically."""

    staging_dir = plan.paths.staging_dir
    validate_phase_emitted = False

    def _validate_staging(path) -> None:
        nonlocal validate_phase_emitted
        if not validate_phase_emitted:
            reporter.phase(phase="validate", label="Validating staged extension documents")
            validate_phase_emitted = True
        if path != plan.paths.staging_dir:
            raise ValueError("publication staging path does not match the planned output")
        validate_staged_extension_dir(plan.paths)

    def _populate() -> ExtensionRenderResult:
        reporter.phase(phase="render", label="Rendering extension documents")
        rendered = add_files_rendering.render_extension_documents(
            plan,
            output_settings=output_settings,
            render_frames_to_pdf=render_module.render_frames_to_pdf,
            layout_debug_json_path=layout_debug_json_path,
        )
        reporter.progress(
            phase="render",
            current=1,
            total=1,
            unit="step",
            details={"staging_dir": staging_dir},
        )
        return rendered

    def _validate_result(rendered: ExtensionRenderResult) -> None:
        validate_staged_extension_documents(plan, rendered)
        reporter.progress(
            phase="validate",
            current=1,
            total=1,
            unit="step",
            details={"staging_dir": staging_dir},
        )
        reporter.phase(phase="publish", label="Publishing extension documents")

    publish_result = publish_staged_directory(
        staging_dir=staging_dir,
        final_dir=plan.paths.final_dir,
        populate=_populate,
        validate_staging=_validate_staging,
        validate_result=_validate_result,
        durability="required",
    )
    final_dir = publish_result.final_dir
    reporter.progress(
        phase="publish",
        current=1,
        total=1,
        unit="step",
        details={"extension_dir": final_dir},
    )

    return PublishedExtensionResult(
        index=plan.prepared.next_index,
        doc_id=plan.encrypted.doc_id,
        doc_hash=plan.encrypted.doc_hash,
        final_dir=final_dir,
        qr_document_path=final_dir / plan.paths.qr_document_path.name,
        recovery_document_path=final_dir / plan.paths.recovery_document_path.name,
        parent_head_index=plan.prepared.plan.parent.head_index,
        parent_head_doc_hash=plan.prepared.plan.parent.head_doc_hash.hex(),
        expected_head_doc_hash=plan.prepared.request.expected_head_doc_hash,
        recovery_frames=publish_result.payload.recovery_document_fallback_frames,
    )


def assess_prepared_add_files(
    prepared: PreparedAddFilesRun,
) -> AssessedAddFilesRun:
    """Assemble and encrypt an extension without rendering publication files."""

    output_settings = add_files_output_settings.resolve_add_files_output_settings(
        prepared,
        create_layout_debug_dir=False,
    )
    _preflight_prepared_extension_publish_target(prepared)
    encrypted = encrypt_prepared_extension_document(prepared)
    require_rebuildable_result(prepared, encrypted.built)
    return AssessedAddFilesRun(
        prepared=prepared,
        output_settings=output_settings,
        encrypted=encrypted,
    )


def execute_assessed_add_files(
    assessed: AssessedAddFilesRun,
    *,
    config_path: str | None = None,
    nonce: str | None = None,
    reporter: AddFilesReporter = NULL_ADD_FILES_REPORTER,
) -> ExecutedAddFilesRun:
    """Publish the exact payload and output settings approved by assessment."""

    prepared = (
        assessed.prepared
        if config_path is None
        else replace(
            assessed.prepared,
            request=replace(assessed.prepared.request, config_path=config_path),
        )
    )
    _preflight_prepared_extension_publish_target(prepared)
    require_rebuildable_result(prepared, assessed.encrypted.built)
    return _execute_resolved_add_files(
        prepared,
        output_settings=assessed.output_settings,
        encrypted=assessed.encrypted,
        nonce=nonce,
        reporter=reporter,
    )


def _execute_resolved_add_files(
    prepared: PreparedAddFilesRun,
    *,
    output_settings: ExtensionOutputSettings,
    encrypted: EncryptedExtension,
    nonce: str | None,
    reporter: AddFilesReporter,
) -> ExecutedAddFilesRun:
    """Render and publish a resolved extension, optionally using an assessed payload."""

    output_settings = replace(
        output_settings,
        layout_debug_dir=add_files_output_settings.resolve_add_files_layout_debug_dir(
            prepared.request.layout_debug_directory,
            output_dir=prepared.request.output_dir,
        ),
    )
    nonce_value = nonce or secrets.token_hex(4)
    publish = prepare_extension_publish(
        prepared,
        encrypted=encrypted,
        nonce=nonce_value,
    )
    try:
        (
            render_settings,
            layout_debug_staging_dir,
            layout_debug_dir_identity,
        ) = _settings_with_staged_layout_debug(
            output_settings,
            nonce=nonce_value,
        )
    except BaseException:
        discard_staging_directory(publish.paths.staging_dir)
        raise

    try:
        result = _publish_staged_extension(
            publish,
            output_settings=render_settings,
            reporter=reporter,
        )
    except BaseException:
        _discard_staged_layout_debug(layout_debug_staging_dir)
        raise
    _publish_staged_layout_debug(
        layout_debug_staging_dir,
        output_settings.layout_debug_dir,
        expected_final_dir_identity=layout_debug_dir_identity,
        reporter=reporter,
    )
    return ExecutedAddFilesRun(
        prepared=prepared,
        output_settings=output_settings,
        publish=publish,
        result=result,
    )


def _preflight_prepared_extension_publish_target(prepared: PreparedAddFilesRun) -> None:
    output_dir = prepared.request.output_dir
    if not output_dir:
        raise AddFilesWorkflowError(
            code=api_codes.EXTENSION_PUBLISH_TARGET_INVALID,
            message="Add Files requires an output directory",
            details={"stage": "publish_target"},
        )
    try:
        preflight_extension_publish_target(output_dir)
    except ValueError as exc:
        raise AddFilesWorkflowError(
            code=api_codes.EXTENSION_PUBLISH_TARGET_INVALID,
            message=str(exc),
            details={"stage": "publish_target"},
        ) from exc


def _settings_with_staged_layout_debug(
    output_settings,
    *,
    nonce: str,
):
    if output_settings.layout_debug_dir is None:
        return output_settings, None, None
    layout_debug_dir = Path(output_settings.layout_debug_dir)
    layout_debug_dir_identity = _layout_debug_dir_identity(layout_debug_dir)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".extension-layout-{nonce}-",
            dir=str(layout_debug_dir),
        )
    )
    return (
        replace(output_settings, layout_debug_dir=str(staging_dir)),
        staging_dir,
        layout_debug_dir_identity,
    )


def _publish_staged_layout_debug(
    staging_dir: Path | None,
    final_dir: str | None,
    *,
    expected_final_dir_identity: DirectoryIdentity | None,
    reporter: AddFilesReporter,
) -> None:
    if staging_dir is None or final_dir is None:
        return
    final_path = Path(final_dir)
    try:
        try:
            _replace_layout_debug_sidecars(
                staging_dir,
                final_path,
                expected_final_dir_identity=expected_final_dir_identity,
            )
        except (OSError, ValueError) as exc:
            reporter.warning(
                "Extension published, but layout debug sidecar promotion failed.",
                details={
                    "layout_debug_dir": str(final_path),
                    "layout_debug_staging_dir": str(staging_dir),
                    "error": str(exc),
                },
            )
    finally:
        _discard_staged_layout_debug(staging_dir)


def _discard_staged_layout_debug(staging_dir: Path | None) -> None:
    if staging_dir is None:
        return
    with suppress(OSError):
        shutil.rmtree(staging_dir, ignore_errors=True)


def _replace_layout_debug_sidecars(
    staging_dir: Path,
    final_path: Path,
    *,
    expected_final_dir_identity: DirectoryIdentity | None,
) -> None:
    sidecars = sorted(staging_dir.glob("*.layout.json"))
    if expected_final_dir_identity is None:
        for path in sidecars:
            path.replace(final_path / path.name)
        return
    if os.replace in os.supports_dir_fd:
        final_fd = _open_verified_layout_debug_dir(final_path, expected_final_dir_identity)
        try:
            for path in sidecars:
                os.replace(path, path.name, dst_dir_fd=final_fd)
        finally:
            os.close(final_fd)
        return
    for path in sidecars:
        _require_layout_debug_dir_identity(final_path, expected_final_dir_identity)
        path.replace(final_path / path.name)


def _layout_debug_dir_identity(path: Path) -> DirectoryIdentity:
    stat_result = path.lstat()
    if stat.S_ISLNK(stat_result.st_mode):
        raise ValueError("layout debug directory must not be a symlink")
    if not stat.S_ISDIR(stat_result.st_mode):
        raise ValueError("layout debug path must be a directory")
    return stat_result.st_dev, stat_result.st_ino


def _require_layout_debug_dir_identity(path: Path, expected: DirectoryIdentity) -> None:
    actual = _layout_debug_dir_identity(path)
    if actual != expected:
        raise ValueError("layout debug directory changed before sidecar promotion")


def _open_verified_layout_debug_dir(path: Path, expected: DirectoryIdentity) -> int:
    _require_layout_debug_dir_identity(path, expected)
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        stat_result = os.fstat(fd)
        if not stat.S_ISDIR(stat_result.st_mode):
            raise ValueError("layout debug path must be a directory")
        if (stat_result.st_dev, stat_result.st_ino) != expected:
            raise ValueError("layout debug directory changed before sidecar promotion")
    except BaseException:
        os.close(fd)
        raise
    return fd


__all__ = [
    "AssessedAddFilesRun",
    "assess_prepared_add_files",
    "execute_assessed_add_files",
]
