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

from collections.abc import Mapping

_TEMPLATE_COPY_BUILDERS: dict[str, str] = {
    "main_document.html.j2": "main_document",
    "recovery_document.html.j2": "recovery_document",
    "kit_document.html.j2": "kit_document",
    "shard_document.html.j2": "shard_document",
    "signing_key_shard_document.html.j2": "signing_key_shard_document",
    "kit_index_document.html.j2": "kit_index_document",
}


def build_copy_bundle(*, template_name: str, context: Mapping[str, object]) -> dict[str, object]:
    doc_key = _TEMPLATE_COPY_BUILDERS.get(template_name)
    if doc_key is None:
        return {}
    if doc_key == "main_document":
        return _main_document_copy()
    if doc_key == "recovery_document":
        return _recovery_document_copy()
    if doc_key == "kit_document":
        return _kit_document_copy()
    if doc_key == "shard_document":
        return _shard_document_copy(context=context)
    if doc_key == "signing_key_shard_document":
        return _signing_key_shard_document_copy(context=context)
    return _kit_index_document_copy()


def _main_document_copy() -> dict[str, object]:
    return {
        "title": "Main Document",
        "subtitle": "Passphrase-protected payload",
        "header_guidance": "Use with matching recovery document",
        "footer_guidance": "Use with matching recovery document",
        "directives_label": "Directives",
        "security_notice_label": "Security Notice",
        "security_notice_body": (
            "This document contains encrypted backup payload fragments. "
            "Keep this printout air-gapped and physically secured."
        ),
        "continuation_hint": (
            "Continuation sheet for encrypted backup fragments. "
            "Scan segments in any order and use labels only to confirm completeness."
        ),
        "segment_prefix": "Segment",
    }


def _recovery_document_copy() -> dict[str, object]:
    return {
        "title": "Recovery Document",
        "subtitle": "Keys + Text Fallback",
        "header_guidance": "Transcribe exactly; keep separate from QR pages",
        "footer_guidance": "Transcribe exactly; keep separate from QR pages",
        "warning_title": "Critical Security Warning",
        "warning_body": (
            "Operate in an air-gapped environment only. Verify each fallback line and keep "
            "this sheet physically separate from QR pages."
        ),
        "session_log_label": "Recovery Session Log",
        "workspace_check_label": "Recovery Workspace Check",
        "completion_check_label": "Recovery Completion Check",
        "transcription_sequence_label": "Manual Transcription Sequence",
        "transcription_helper": "Transcribe decrypted recovery lines exactly as shown.",
        "continuation_hint": "Keep row order intact and copy each line exactly.",
        "workspace_checklist": (
            "[ ] Network radios off (Wi-Fi / Ethernet / Bluetooth).",
            "[ ] No phone or camera in the recovery area.",
            "[ ] Only required recovery artifacts are on the desk.",
            "[ ] Recovery sheet kept separate from QR packet.",
        ),
        "completion_checklist": (
            "[ ] Restored output opened and format looks correct.",
            "[ ] Hash / byte comparison matches trusted source.",
            "[ ] Temporary recovery copies removed per policy.",
        ),
        "verified_sha_label": "Verified output SHA-256:",
        "data_entry_label": "Data Entry Block",
        "verify_label": "Verify",
        "index_label": "Idx",
    }


def _kit_document_copy() -> dict[str, object]:
    return {
        "title": "Recovery Kit",
        "subtitle": "Offline HTML bundle",
        "header_guidance": "Scan left-to-right, top-to-bottom in offline recovery flow",
        "footer_guidance": "Scan left-to-right, top-to-bottom in offline recovery flow",
        "warning_title": "Critical Security Warning",
        "warning_body": (
            "Perform kit reconstruction in an offline environment. Keep this document "
            "separate from shard and recovery documents."
        ),
        "checklist_label": "Security Verification Checklist",
        "continuation_hint": "Scan every QR code left to right, top to bottom before continuing.",
    }


def _shard_document_copy(*, context: Mapping[str, object]) -> dict[str, object]:
    shard_index = _int_value(context.get("shard_index"), default=1)
    shard_total = _int_value(context.get("shard_total"), default=1)
    shard_threshold = _int_value(context.get("shard_threshold"), default=shard_total)
    return {
        "title": "Shard Document",
        "subtitle": f"Shard {shard_index} of {shard_total}",
        "header_guidance": "Single shard cannot recover the secret",
        "footer_guidance": "Single shard cannot recover the secret",
        "warning_title": "Critical Security Notice",
        "warning_body": (
            f"This document contains shard {shard_index} of {shard_total}. Possession of this "
            f"shard alone is insufficient for recovery. Recovery requires {shard_threshold}/"
            f"{shard_total} shards. Store separately from other shards to prevent unauthorized "
            "reassembly."
        ),
        "manual_transcription_label": "Manual Transcription",
    }


def _signing_key_shard_document_copy(*, context: Mapping[str, object]) -> dict[str, object]:
    shard_index = _int_value(context.get("shard_index"), default=1)
    shard_total = _int_value(context.get("shard_total"), default=1)
    return {
        "title": "Signing Key Shard",
        "subtitle": f"Signing key shard {shard_index} of {shard_total}",
        "header_guidance": "Store apart from passphrase and sibling signing shards",
        "footer_guidance": "Store apart from passphrase and sibling signing shards",
        "warning_title": "Critical Security Notice",
        "warning_body": (
            "This page contains one signing key shard. Never store it with other signing "
            "shards or passphrase documents."
        ),
        "key_material_label": "Key Material Payload",
        "master_fingerprint_label": "Master Fingerprint",
        "empty_fallback_text": "No fallback payload on this page.",
    }


def _kit_index_document_copy() -> dict[str, object]:
    return {
        "title": "Recovery Kit Index",
        "subtitle": "Inventory + Custody Log",
        "header_guidance": "Inventory record only; keep separate from shard/recovery docs",
        "footer_guidance": "Inventory record only; keep separate from shard/recovery docs",
        "warning_title": "Critical Security Warning",
        "warning_body": (
            "This document is an inventory index only. Keep it separate from shard and "
            "recovery documents."
        ),
        "hardware_inventory_label": "Hardware Inventory",
        "chain_of_custody_label": "Chain of Custody",
    }


def _int_value(raw: object, *, default: int) -> int:
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if text:
            try:
                return int(text)
            except ValueError:
                return default
    return default
