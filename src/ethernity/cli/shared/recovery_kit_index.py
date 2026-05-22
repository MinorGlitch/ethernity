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

"""Shared recovery-kit index helpers for backup and extension flows."""

from __future__ import annotations

from pathlib import Path

from ethernity.config import AppConfig
from ethernity.config.paths import TEMPLATES_RESOURCE_ROOT
from ethernity.crypto.sharding import ShardPayload

KIT_INDEX_TEMPLATE_MARKER = "kit_index_inventory_artifacts_v3"
KIT_INDEX_TEMPLATE_NAME = "kit_index_document.html.j2"


def is_compatible_kit_index_template(path: Path) -> bool:
    """Return whether a kit index template contains the expected compatibility marker."""

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return KIT_INDEX_TEMPLATE_MARKER in content


def resolve_recovery_kit_index_template_path(config: AppConfig) -> Path | None:
    """Resolve an optional compatible recovery-kit index template for the active design."""

    kit_template_path = Path(config.kit_template_path)
    candidate = kit_template_path.with_name(KIT_INDEX_TEMPLATE_NAME)
    package_candidate = (
        TEMPLATES_RESOURCE_ROOT / kit_template_path.parent.name / KIT_INDEX_TEMPLATE_NAME
    )

    if candidate.is_file() and is_compatible_kit_index_template(candidate):
        return candidate

    if package_candidate.is_file() and is_compatible_kit_index_template(package_candidate):
        return package_candidate

    return None


def build_recovery_kit_index_inventory_rows(
    *,
    shard_payloads: list[ShardPayload],
    signing_key_shard_payloads: list[ShardPayload],
) -> list[dict[str, str]]:
    """Build inventory rows for the optional recovery kit index document."""

    rows = [
        {
            "component_id": "QR-DOC-01",
            "detail": "Encrypted payload and auth QR frames",
            "status": "Generated",
        },
        {
            "component_id": "RECOVERY-DOC-01",
            "detail": "Recovery keys and full fallback text",
            "status": "Generated",
        },
    ]

    if shard_payloads:
        for shard in sorted(shard_payloads, key=lambda item: item.share_index):
            rows.append(
                {
                    "component_id": f"SHARD-{shard.share_index:02d}",
                    "detail": (f"Passphrase shard {shard.share_index} of {shard.share_count}"),
                    "status": "Generated",
                }
            )

    if signing_key_shard_payloads:
        for shard in sorted(signing_key_shard_payloads, key=lambda item: item.share_index):
            rows.append(
                {
                    "component_id": f"SIGNING-SHARD-{shard.share_index:02d}",
                    "detail": (f"Signing-key shard {shard.share_index} of {shard.share_count}"),
                    "status": "Generated",
                }
            )

    return rows


__all__ = [
    "KIT_INDEX_TEMPLATE_MARKER",
    "KIT_INDEX_TEMPLATE_NAME",
    "build_recovery_kit_index_inventory_rows",
    "is_compatible_kit_index_template",
    "resolve_recovery_kit_index_template_path",
]
