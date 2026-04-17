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

from ethernity.render.utils import int_value as _int_value

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
        return _main_document_copy(context=context)
    if doc_key == "recovery_document":
        return _recovery_document_copy(context=context)
    if doc_key == "kit_document":
        return _kit_document_copy()
    if doc_key == "shard_document":
        return _shard_document_copy(context=context)
    if doc_key == "signing_key_shard_document":
        return _signing_key_shard_document_copy(context=context)
    if doc_key == "kit_index_document":
        return _kit_index_document_copy(context=context)
    return {}


def _lineage_mapping(context: Mapping[str, object]) -> Mapping[str, object]:
    lineage = context.get("lineage")
    if isinstance(lineage, Mapping):
        return lineage
    return {}


def _lineage_kind(context: Mapping[str, object]) -> str:
    lineage = _lineage_mapping(context)
    kind = lineage.get("kind")
    if isinstance(kind, str) and kind:
        return kind
    return "root_backup"


def _lineage_extension_index(context: Mapping[str, object]) -> int | None:
    lineage = _lineage_mapping(context)
    raw_value = lineage.get("extension_index")
    value = _int_value(raw_value, default=0)
    return value if value > 0 else None


def _extension_label(index: int | None) -> str:
    if index is None:
        return "Extension"
    return f"Extension {index:02d}"


def _lineage_label(context: Mapping[str, object]) -> str | None:
    kind = _lineage_kind(context)
    if kind == "extension":
        return _extension_label(_lineage_extension_index(context))
    if kind == "compaction_checkpoint":
        return "Compaction Checkpoint"
    return None


def _main_document_copy(*, context: Mapping[str, object]) -> dict[str, object]:
    lineage_kind = _lineage_kind(context)
    lineage_label = _lineage_label(context)
    if lineage_kind == "extension":
        if lineage_label is None:
            raise ValueError("extension lineage label is required")
        return {
            "title": "Extension Main Document",
            "subtitle": f"{lineage_label} - Appended generation payload",
            "header_guidance": "Use with the matching extension recovery document and root backup",
            "footer_guidance": "Use with the matching extension recovery document and root backup",
            "directives_label": "Directives",
            "security_notice_label": "Security Notice",
            "security_notice_body": (
                "This document contains encrypted extension payload fragments. Keep this printout "
                "air-gapped and physically secured with the root backup set."
            ),
            "continuation_hint": (
                f"Continuation sheet for {lineage_label.lower()} encrypted fragments. Scan "
                "segments in any order and use labels only to confirm completeness."
            ),
            "segment_prefix": "Segment",
            "lineage_badge": lineage_label,
        }
    if lineage_kind == "compaction_checkpoint":
        return {
            "title": "Compaction Checkpoint Main Document",
            "subtitle": "Fresh standalone checkpoint payload",
            "header_guidance": "Use with the matching compaction checkpoint recovery document",
            "footer_guidance": "Use with the matching compaction checkpoint recovery document",
            "directives_label": "Directives",
            "security_notice_label": "Security Notice",
            "security_notice_body": (
                "This document contains encrypted checkpoint payload fragments produced from the "
                "latest validated chain state. Keep this printout air-gapped and "
                "physically secured."
            ),
            "continuation_hint": (
                "Continuation sheet for encrypted checkpoint fragments. Scan segments in any "
                "order and use labels only to confirm completeness."
            ),
            "segment_prefix": "Segment",
            "lineage_badge": "Compaction Checkpoint",
        }
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


def _recovery_document_copy(*, context: Mapping[str, object]) -> dict[str, object]:
    lineage_kind = _lineage_kind(context)
    lineage_label = _lineage_label(context)
    if lineage_kind == "extension":
        if lineage_label is None:
            raise ValueError("extension lineage label is required")
        return {
            "title": "Recovery Document",
            "subtitle": f"{lineage_label} - Keys + Text Fallback",
            "header_guidance": "Transcribe exactly; keep with the root backup set",
            "footer_guidance": "Transcribe exactly; keep with the root backup set",
            "warning_title": "Critical Security Warning",
            "warning_body": (
                f"This sheet belongs to {lineage_label}. Operate in an air-gapped "
                "environment only and keep it with the root backup set."
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
                "[ ] Recovery sheet stays with the root backup and extension set.",
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
            "lineage_badge": lineage_label,
        }
    if lineage_kind == "compaction_checkpoint":
        return {
            "title": "Recovery Document",
            "subtitle": "Fresh standalone checkpoint keys + text fallback",
            "header_guidance": (
                "Transcribe exactly; keep separate from the checkpoint main document"
            ),
            "footer_guidance": (
                "Transcribe exactly; keep separate from the checkpoint main document"
            ),
            "warning_title": "Critical Security Warning",
            "warning_body": (
                "This sheet belongs to the compaction checkpoint. Operate in an air-gapped "
                "environment only and keep it separate from the checkpoint main document."
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
                "[ ] Recovery sheet kept separate from the checkpoint main document.",
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
            "lineage_badge": "Compaction Checkpoint",
        }
    return {
        "title": "Recovery Document",
        "subtitle": "Keys + Text Fallback",
        "header_guidance": "Transcribe exactly; keep separate from the main document",
        "footer_guidance": "Transcribe exactly; keep separate from the main document",
        "warning_title": "Critical Security Warning",
        "warning_body": (
            "Operate in an air-gapped environment only. Verify each fallback line and keep "
            "this sheet physically separate from the main document."
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
            "[ ] Recovery sheet kept separate from the main document.",
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
    lineage_kind = _lineage_kind(context)
    lineage_label = _lineage_label(context)
    if lineage_kind == "extension":
        if lineage_label is None:
            raise ValueError("extension lineage label is required")
        return {
            "title": "Extension Shard Document",
            "subtitle": f"{lineage_label} - Shard {shard_index} of {shard_total}",
            "header_guidance": "Single shard cannot recover the extension secret",
            "footer_guidance": "Single shard cannot recover the extension secret",
            "warning_title": "Critical Security Notice",
            "warning_body": (
                f"This document contains {lineage_label.lower()} shard {shard_index} of "
                f"{shard_total}. Possession of this shard alone is insufficient for recovery. "
                f"Recovery requires {shard_threshold}/{shard_total} shards. Store it separately "
                "from sibling shards and keep it associated with the correct extension generation."
            ),
            "manual_transcription_label": "Manual Transcription",
            "lineage_badge": lineage_label,
        }
    if lineage_kind == "compaction_checkpoint":
        return {
            "title": "Compaction Checkpoint Shard Document",
            "subtitle": f"Compaction Checkpoint - Shard {shard_index} of {shard_total}",
            "header_guidance": "Single shard cannot recover the checkpoint secret",
            "footer_guidance": "Single shard cannot recover the checkpoint secret",
            "warning_title": "Critical Security Notice",
            "warning_body": (
                f"This document contains checkpoint shard {shard_index} of {shard_total}. "
                f"Possession of this shard alone is insufficient for recovery. Recovery requires "
                f"{shard_threshold}/{shard_total} shards. Store it separately from sibling shards "
                "and checkpoint recovery documents."
            ),
            "manual_transcription_label": "Manual Transcription",
            "lineage_badge": "Compaction Checkpoint",
        }
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
    lineage_kind = _lineage_kind(context)
    lineage_label = _lineage_label(context)
    if lineage_kind == "extension":
        if lineage_label is None:
            raise ValueError("extension lineage label is required")
        return {
            "title": "Extension Signing Key Shard",
            "subtitle": f"{lineage_label} - Signing key shard {shard_index} of {shard_total}",
            "header_guidance": "Store apart from passphrase and sibling signing shards",
            "footer_guidance": "Store apart from passphrase and sibling signing shards",
            "warning_title": "Critical Security Notice",
            "warning_body": (
                f"This page contains one signing key shard for {lineage_label.lower()}. Never "
                "store it with other signing shards, passphrase documents, or the wrong "
                "extension generation."
            ),
            "key_material_label": "Key Material Payload",
            "master_fingerprint_label": "Master Fingerprint",
            "empty_fallback_text": "No fallback payload on this page.",
            "lineage_badge": lineage_label,
        }
    if lineage_kind == "compaction_checkpoint":
        return {
            "title": "Compaction Checkpoint Signing Key Shard",
            "subtitle": (
                f"Compaction Checkpoint - Signing key shard {shard_index} of {shard_total}"
            ),
            "header_guidance": "Store apart from passphrase and sibling signing shards",
            "footer_guidance": "Store apart from passphrase and sibling signing shards",
            "warning_title": "Critical Security Notice",
            "warning_body": (
                "This page contains one signing key shard for the compaction checkpoint. Never "
                "store it with other signing shards or passphrase documents."
            ),
            "key_material_label": "Key Material Payload",
            "master_fingerprint_label": "Master Fingerprint",
            "empty_fallback_text": "No fallback payload on this page.",
            "lineage_badge": "Compaction Checkpoint",
        }
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


def _kit_index_document_copy(*, context: Mapping[str, object]) -> dict[str, object]:
    lineage_kind = _lineage_kind(context)
    lineage_label = _lineage_label(context)
    if lineage_kind == "extension":
        if lineage_label is None:
            raise ValueError("extension lineage label is required")
        return {
            "title": "Extension Recovery Kit Index",
            "subtitle": f"{lineage_label} - Inventory + Custody Log",
            "header_guidance": "Inventory record only; keep with the root backup and extension set",
            "footer_guidance": "Inventory record only; keep with the root backup and extension set",
            "warning_title": "Critical Security Warning",
            "warning_body": (
                f"This document is an inventory index for {lineage_label.lower()} only. Keep it "
                "separate from shard and recovery documents while preserving the full "
                "extension set."
            ),
            "hardware_inventory_label": "Hardware Inventory",
            "chain_of_custody_label": "Chain of Custody",
            "lineage_badge": lineage_label,
        }
    if lineage_kind == "compaction_checkpoint":
        return {
            "title": "Compaction Checkpoint Recovery Kit Index",
            "subtitle": "Compaction Checkpoint - Inventory + Custody Log",
            "header_guidance": "Inventory record only; keep separate from checkpoint recovery docs",
            "footer_guidance": "Inventory record only; keep separate from checkpoint recovery docs",
            "warning_title": "Critical Security Warning",
            "warning_body": (
                "This document is an inventory index for the compaction checkpoint only. Keep "
                "it separate from shard and recovery documents."
            ),
            "hardware_inventory_label": "Hardware Inventory",
            "chain_of_custody_label": "Chain of Custody",
            "lineage_badge": "Compaction Checkpoint",
        }
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
