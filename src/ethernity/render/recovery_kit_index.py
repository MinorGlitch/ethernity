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

"""Recovery-kit index helpers shared by rendering workflows."""

from __future__ import annotations

from ethernity.config import AppConfig
from ethernity.crypto.sharding import ShardPayload
from ethernity.render.designs import load_design_manifest_by_name
from ethernity.render.doc_types import DOC_TYPE_KIT_INDEX
from ethernity.render.template_style import load_template_style


def supports_recovery_kit_index_style(style: str) -> bool:
    """Return whether a built-in style supports recovery-kit index rendering."""

    manifest = load_design_manifest_by_name(style)
    if not manifest.supports_doc_type(DOC_TYPE_KIT_INDEX):
        return False
    return load_template_style(style).capabilities.recovery_kit_index_document


def resolve_recovery_kit_index_style(config: AppConfig) -> str | None:
    """Resolve the active style when it supports recovery-kit index rendering."""

    if supports_recovery_kit_index_style(config.design_name):
        return config.design_name
    return None


def build_recovery_kit_index_inventory_rows(
    *,
    shard_payloads: list[ShardPayload],
    signing_key_shard_payloads: list[ShardPayload],
    component_id_prefix: str = "",
) -> list[dict[str, str]]:
    """Build inventory rows for the optional recovery kit index document."""

    rows = [
        {
            "component_id": f"{component_id_prefix}QR-DOC-01",
            "detail": "Encrypted payload and auth QR frames",
            "status": "Generated",
        },
        {
            "component_id": f"{component_id_prefix}RECOVERY-DOC-01",
            "detail": "Recovery keys and full fallback text",
            "status": "Generated",
        },
    ]

    if shard_payloads:
        for shard in sorted(shard_payloads, key=lambda item: item.share_index):
            rows.append(
                {
                    "component_id": f"{component_id_prefix}SHARD-{shard.share_index:02d}",
                    "detail": (f"Passphrase shard {shard.share_index} of {shard.share_count}"),
                    "status": "Generated",
                }
            )

    if signing_key_shard_payloads:
        for shard in sorted(signing_key_shard_payloads, key=lambda item: item.share_index):
            rows.append(
                {
                    "component_id": (f"{component_id_prefix}SIGNING-SHARD-{shard.share_index:02d}"),
                    "detail": (f"Signing-key shard {shard.share_index} of {shard.share_count}"),
                    "status": "Generated",
                }
            )

    return rows


__all__ = [
    "build_recovery_kit_index_inventory_rows",
    "resolve_recovery_kit_index_style",
    "supports_recovery_kit_index_style",
]
