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

"""Validation of rendered chain-bound recovery-kit carriers."""

from __future__ import annotations

from ethernity.qr.scan import scan_qr_payloads
from ethernity.workflows.extension.errors import ExtensionWorkflowError
from ethernity.workflows.extension.models import (
    EXTENSION_KIT_CARRIER_INVALID,
    PreparedExtensionPublishPlan,
    ResolvedExtendRuntime,
)
from ethernity.workflows.kit.service import KitAnchor, validate_chain_bound_kit_carrier


def validate_staged_chain_bound_kit_carrier(
    plan: PreparedExtensionPublishPlan,
    *,
    runtime: ResolvedExtendRuntime,
) -> None:
    """Scan and exact-validate the staged extension's chain-bound kit PDF."""

    path = plan.artifacts.recovery_kit_path
    try:
        raw_qr_payloads = scan_qr_payloads([path])
        validate_chain_bound_kit_carrier(
            raw_qr_payloads,
            config=runtime.config,
            anchor=KitAnchor(
                root_document_hash=plan.prepared.root_doc_hash,
                root_signing_public_key=runtime.sign_pub,
                expected_latest_head_hash=plan.encrypted.doc_hash,
            ),
        )
    except Exception as exc:
        raise ExtensionWorkflowError(
            code=EXTENSION_KIT_CARRIER_INVALID,
            message=f"rendered chain-bound recovery kit {path.name} is invalid: {exc}",
        ) from exc


__all__ = ["validate_staged_chain_bound_kit_carrier"]
