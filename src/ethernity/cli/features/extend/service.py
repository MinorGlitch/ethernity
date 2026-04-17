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

"""Public extend execution facade."""

from __future__ import annotations

from ethernity.cli.features.extend.execution import (
    execute_prepared_extend,
    execute_staged_extension_publish,
    run_extend,
)
from ethernity.cli.features.extend.models import (
    EXTENSION_INPUT_REQUIRED,
    EXTENSION_INVALID_POLICY,
    EXTENSION_MAIN_CARRIER_INVALID,
    EXTENSION_NO_CHANGES,
    EXTENSION_SHARD_CARRIER_INVALID,
    EncryptedPreparedExtension,
    ExecutedExtendRun,
    ExtensionArtifactRenderer,
    PreparedExtendRun,
    PreparedExtensionPublishPlan,
    PublishedExtensionResult,
    ResolvedExtendRuntime,
)
from ethernity.cli.features.extend.prepare import (
    assemble_prepared_extension_document,
    encrypt_prepared_extension_document,
    prepare_extend_run,
    prepare_staged_extension_publish,
)
from ethernity.cli.features.extend.runtime import resolve_extend_runtime

__all__ = [
    "ExecutedExtendRun",
    "EncryptedPreparedExtension",
    "EXTENSION_INVALID_POLICY",
    "EXTENSION_INPUT_REQUIRED",
    "EXTENSION_MAIN_CARRIER_INVALID",
    "EXTENSION_NO_CHANGES",
    "EXTENSION_SHARD_CARRIER_INVALID",
    "ExtensionArtifactRenderer",
    "PreparedExtensionPublishPlan",
    "PreparedExtendRun",
    "PublishedExtensionResult",
    "ResolvedExtendRuntime",
    "assemble_prepared_extension_document",
    "execute_staged_extension_publish",
    "execute_prepared_extend",
    "encrypt_prepared_extension_document",
    "prepare_extend_run",
    "prepare_staged_extension_publish",
    "resolve_extend_runtime",
    "run_extend",
]
