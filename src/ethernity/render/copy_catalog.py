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
from dataclasses import dataclass

from ethernity.core.validation import integer_text_or_default
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)

__all__ = ["InstructionCopy", "build_copy_bundle", "build_instruction_copy"]


@dataclass(frozen=True)
class InstructionCopy:
    """Instruction heading and lines for one rendered document type."""

    label: str
    lines: tuple[str, ...]


def build_copy_bundle(*, doc_type: str, context: Mapping[str, object]) -> dict[str, object]:
    normalized_doc_type = doc_type.strip().lower()
    if normalized_doc_type == DOC_TYPE_MAIN:
        instructions = (
            "Scan every QR code in any order; check that all segment numbers are present.",
            "If scanning fails, use the Recovery Document's text fallback.",
        )
        if _origin_kind(context) == "extension":
            instructions = (_extension_dependencies(context), *instructions)
        return {
            **_main_document_copy(context=context),
            "scan_instructions": "\n".join(instructions),
        }
    if normalized_doc_type == DOC_TYPE_RECOVERY:
        return _recovery_document_copy(context=context)
    if normalized_doc_type == DOC_TYPE_KIT:
        return {
            **_kit_document_copy(context=context),
            **_kit_guide_copy(),
            "segment_prefix": "Part",
            "scan_instructions": build_instruction_copy(doc_type=doc_type, context=context).lines[
                0
            ],
        }
    if normalized_doc_type == DOC_TYPE_SHARD:
        return _shard_document_copy(context=context)
    if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD:
        return _signing_key_shard_document_copy(context=context)
    if normalized_doc_type == DOC_TYPE_KIT_INDEX:
        return _kit_index_document_copy(context=context)
    raise ValueError(f"unsupported render doc_type for copy bundle: {doc_type!r}")


def build_instruction_copy(
    *,
    doc_type: str,
    context: Mapping[str, object],
) -> InstructionCopy:
    """Build the instructions rendered for a document type."""

    normalized_doc_type = doc_type.strip().lower()
    if normalized_doc_type == DOC_TYPE_MAIN:
        lines = (
            "Record all segment labels for this document set.",
            "Scan segments in any order; capture each label once.",
            "Use Recovery Document text fallback only if scanning fails.",
        )
    elif normalized_doc_type == DOC_TYPE_RECOVERY:
        lines = (
            "This document contains recovery keys and full text fallback.",
            "Keep it separate from the main document.",
            "Fallback includes AUTH + MAIN sections; keep the labels when transcribing.",
        )
    elif normalized_doc_type in {DOC_TYPE_KIT, DOC_TYPE_KIT_INDEX}:
        lines = (
            "Copy QR 1, then QR 2 into one plain-text file.",
            "Save as start.html and open it in a browser.",
            "Paste QR 3 onwards into the page in any order.",
            "Choose Save recovery kit, then open the downloaded HTML.",
        )
    elif normalized_doc_type in {DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD}:
        shard_total = _int_value(context.get("shard_total"), default=1)
        shard_threshold = _int_value(context.get("shard_threshold"), default=shard_total)
        secret = "signing key" if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD else "secret"
        recovery_notice = _shard_recovery_notice(shard_threshold, secret=secret)
        if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD and shard_threshold == 1:
            lines = (
                recovery_notice,
                "This shard alone can authorize future extensions. Keep it secure.",
                f"Recovery requires {shard_threshold}/{shard_total} shards. "
                "Store apart from passphrase documents.",
            )
        else:
            lines = (
                recovery_notice,
                f"Recovery requires {shard_threshold}/{shard_total} shards. "
                "Keep each shard secure.",
                "Keep it apart from recovery documents and other shards.",
            )
    else:
        raise ValueError(f"unsupported render doc_type for instruction copy: {doc_type!r}")

    if (
        normalized_doc_type in {DOC_TYPE_MAIN, DOC_TYPE_RECOVERY}
        and _origin_kind(context) == "extension"
    ):
        lines = (_extension_dependencies(context), *lines[1:])

    return InstructionCopy(label="Instructions", lines=lines)


def _int_value(value: object, *, default: int) -> int:
    """Coerce a copy-context value to an integer or use its default."""

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return integer_text_or_default(value, default)


def _origin_mapping(context: Mapping[str, object]) -> Mapping[str, object]:
    origin = context.get("origin")
    if isinstance(origin, Mapping):
        return origin
    return {}


def _origin_kind(context: Mapping[str, object]) -> str:
    origin = _origin_mapping(context)
    kind = origin.get("kind")
    if isinstance(kind, str) and kind:
        return kind
    return "root_backup"


def _origin_extension_index(context: Mapping[str, object]) -> int | None:
    origin = _origin_mapping(context)
    raw_value = origin.get("extension_index")
    value = _int_value(raw_value, default=0)
    return value if value > 0 else None


def _extension_label(index: int | None) -> str:
    if index is None:
        return "Extension"
    return f"Extension {index:02d}"


def _extension_subtitle(context: Mapping[str, object], *, fallback: str) -> str:
    root_doc_id = _origin_mapping(context).get("root_doc_id")
    index = _origin_extension_index(context)
    if isinstance(root_doc_id, str) and root_doc_id and index is not None:
        return f"Update {index:02d} | Original backup ID: {root_doc_id}"
    return fallback


def _extension_dependencies(context: Mapping[str, object], *, compact: bool = False) -> str:
    if _origin_mapping(context).get("update_mode") == "cumulative":
        if compact:
            return "Keep original + this update"
        return "Keep the original backup and this update; earlier updates are not required."
    if compact:
        return "Keep original + all updates through this one"
    return "Keep the original backup and every update through this one."


def _origin_label(context: Mapping[str, object]) -> str | None:
    kind = _origin_kind(context)
    if kind == "extension":
        return _extension_label(_origin_extension_index(context))
    if kind == "rebuilt_backup":
        return "Rebuilt Backup"
    if kind == "replacement_recovery":
        return "Replacement Shard Set"
    if kind == "recovery_kit":
        return "Recovery Kit"
    return None


def _main_document_copy(*, context: Mapping[str, object]) -> dict[str, object]:
    origin_kind = _origin_kind(context)
    origin_label = _origin_label(context)
    if origin_kind == "extension":
        if origin_label is None:
            raise ValueError("extension origin label is required")
        return {
            "title": "Update Document",
            "subtitle": _extension_subtitle(
                context, fallback=f"{origin_label} - Added and replaced files"
            ),
            "header_guidance": _extension_dependencies(context, compact=True),
            "footer_guidance": _extension_dependencies(context, compact=True),
            "directives_label": "Directives",
            "security_notice_label": "Security Notice",
            "security_notice_body": (
                "This document contains encrypted extension payload fragments. Keep this printout "
                "air-gapped and physically secured with the root backup set."
            ),
            "continuation_hint": (
                f"Continuation sheet for {origin_label.lower()} encrypted fragments. Scan "
                "segments in any order and use labels only to confirm completeness."
            ),
            "segment_prefix": "Segment",
            "origin_badge": origin_label,
        }
    if origin_kind == "rebuilt_backup":
        return {
            "title": "Rebuilt Backup Main Document",
            "subtitle": "Fresh standalone backup payload",
            "header_guidance": "Use with the matching rebuilt backup recovery document",
            "footer_guidance": "Use with the matching rebuilt backup recovery document",
            "directives_label": "Directives",
            "security_notice_label": "Security Notice",
            "security_notice_body": (
                "This document contains encrypted backup payload fragments produced from the "
                "latest supplied validated chain state. Keep this printout air-gapped and "
                "physically secured."
            ),
            "continuation_hint": (
                "Continuation sheet for encrypted backup fragments. Scan segments in any "
                "order and use labels only to confirm completeness."
            ),
            "segment_prefix": "Segment",
            "origin_badge": "Rebuilt Backup",
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
    origin_kind = _origin_kind(context)
    origin_label = _origin_label(context)
    if origin_kind == "extension":
        if origin_label is None:
            raise ValueError("extension origin label is required")
        return {
            "title": "Recovery Document",
            "subtitle": _extension_subtitle(
                context, fallback=f"{origin_label} - Keys + Text Fallback"
            ),
            "header_guidance": _extension_dependencies(context, compact=True),
            "footer_guidance": _extension_dependencies(context, compact=True),
            "warning_title": "Critical Security Warning",
            "warning_body": (
                f"This sheet belongs to {origin_label}. Operate in an air-gapped "
                "environment only and keep it with the root backup set."
            ),
            "session_log_label": "Recovery Session Log",
            "workspace_check_label": "Recovery Workspace Check",
            "completion_check_label": "Recovery Completion Check",
            "transcription_sequence_label": "Manual Transcription Sequence",
            "transcription_guidance": "Transcribe encoded fallback lines exactly as shown.",
            "continuation_hint": "Keep row order intact and copy each line exactly.",
            "workspace_checklist": (
                "[ ] Network radios off (Wi-Fi / Ethernet / Bluetooth).",
                "[ ] No phone or camera in the recovery area.",
                "[ ] Only required recovery sheets are on the desk.",
                f"[ ] {_extension_dependencies(context)}",
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
            "origin_badge": origin_label,
        }
    if origin_kind == "rebuilt_backup":
        return {
            "title": "Recovery Document",
            "subtitle": "Backup keys + text fallback",
            "header_guidance": ("Transcribe exactly; keep separate from the backup main document"),
            "footer_guidance": ("Transcribe exactly; keep separate from the backup main document"),
            "warning_title": "Critical Security Warning",
            "warning_body": (
                "This sheet belongs to the rebuilt backup. Operate in an air-gapped "
                "environment only and keep it separate from the backup main document."
            ),
            "session_log_label": "Recovery Session Log",
            "workspace_check_label": "Recovery Workspace Check",
            "completion_check_label": "Recovery Completion Check",
            "transcription_sequence_label": "Manual Transcription Sequence",
            "transcription_guidance": "Transcribe decrypted recovery lines exactly as shown.",
            "continuation_hint": "Keep row order intact and copy each line exactly.",
            "workspace_checklist": (
                "[ ] Network radios off (Wi-Fi / Ethernet / Bluetooth).",
                "[ ] No phone or camera in the recovery area.",
                "[ ] Only required recovery sheets are on the desk.",
                "[ ] Recovery sheet kept separate from the backup main document.",
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
            "origin_badge": "Rebuilt Backup",
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
        "transcription_guidance": "Transcribe decrypted recovery lines exactly as shown.",
        "continuation_hint": "Keep row order intact and copy each line exactly.",
        "workspace_checklist": (
            "[ ] Network radios off (Wi-Fi / Ethernet / Bluetooth).",
            "[ ] No phone or camera in the recovery area.",
            "[ ] Only required recovery sheets are on the desk.",
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


def _kit_guide_copy() -> dict[str, object]:
    scan = (
        "Scan QR 1, then QR 2.",
        "Copy both scans, in that order, into one plain-text file.",
        "Save as start.html and open it in a browser.",
        "Paste QR 3 onwards into the page in any order.",
    )
    open_steps = (
        "When all parts are collected, choose Save recovery kit.",
        "Open the downloaded HTML file.",
        "Disconnect before adding your backup and recovery secrets.",
    )
    help_steps = (
        "Missing or damaged parts: rescan the QR numbers shown on the page.",
        "Startup fails: recopy QR 1 and QR 2.",
        "Browser support error: try a newer browser.",
    )
    storage = (
        "Keep the HTML file to reuse the kit without scanning.",
        "Keep the printed kit in case the digital copy is lost.",
    )
    security = (
        "Disconnect before entering recovery secrets.",
        "Use a computer you trust.",
    )
    return {
        "guide_title": "REBUILD THE RECOVERY KIT",
        "guide_intro": "Rebuild the app from these QR pages, then use it to restore your backup.",
        "guide_scan_steps": scan,
        "guide_open_steps": open_steps,
        "guide_help_steps": help_steps,
        "guide_verify": (
            "The browser should show Ethernity Recovery Kit.",
            "Open it offline before relying on this copy.",
        ),
        "guide_storage": storage,
        "guide_security": security,
        "guide_checklist": (
            "Both startup codes saved in start.html.",
            "Assembly page reports all parts collected.",
            "Recovery kit downloaded as HTML.",
            "Kit opens without errors.",
            "Kit works while offline.",
            "Recovered files saved and checked.",
        ),
        "guide_scan": scan[0],
        "guide_paste": " ".join(scan[1:3]),
        "guide_save": scan[3],
        "guide_open": " ".join(open_steps[:2]),
        "guide_offline": " ".join(security),
        "guide_help_text": help_steps[1],
        "guide_help_parts": help_steps[0],
        "guide_help_browser": help_steps[2],
        "guide_keep": " ".join(storage),
    }


def _kit_document_copy(*, context: Mapping[str, object]) -> dict[str, object]:
    origin_kind = _origin_kind(context)
    if origin_kind == "recovery_kit":
        return {
            "title": "Recovery Kit",
            "subtitle": "Standalone offline HTML bundle",
            "header_guidance": "Start with QR 1 and QR 2; add remaining scans in any order",
            "footer_guidance": "Start with QR 1 and QR 2; add remaining scans in any order",
            "warning_title": "Critical Security Warning",
            "warning_body": (
                "Perform kit reconstruction in an offline environment. This standalone kit "
                "document contains only recovery-app bundle fragments, not backup secrets."
            ),
            "checklist_label": "Security Verification Checklist",
            "continuation_hint": (
                "Create start.html from QR 1 and QR 2; paste the rest into that page."
            ),
            "origin_badge": "Recovery Kit",
        }
    return {
        "title": "Recovery Kit",
        "subtitle": "Offline HTML bundle",
        "header_guidance": "Start with QR 1 and QR 2; add remaining scans in any order",
        "footer_guidance": "Start with QR 1 and QR 2; add remaining scans in any order",
        "warning_title": "Critical Security Warning",
        "warning_body": (
            "Perform kit reconstruction in an offline environment. Keep this document "
            "separate from shard and recovery documents."
        ),
        "checklist_label": "Security Verification Checklist",
        "continuation_hint": "Create start.html from QR 1 and QR 2; paste the rest into that page.",
    }


def _shard_recovery_notice(threshold: int, *, secret: str) -> str:
    if threshold == 1:
        return f"This shard alone can recover the {secret}."
    return f"This shard alone cannot recover the {secret}."


def _shard_document_copy(*, context: Mapping[str, object]) -> dict[str, object]:
    shard_index = _int_value(context.get("shard_index"), default=1)
    shard_total = _int_value(context.get("shard_total"), default=1)
    threshold = _int_value(context.get("shard_threshold"), default=shard_total)
    origin = _origin_kind(context)
    prefix = {
        "rebuilt_backup": "Rebuilt Backup ",
        "replacement_recovery": "Replacement ",
    }.get(origin, "")
    recovery_notice = _shard_recovery_notice(threshold, secret="secret")
    guidance = (
        "This shard alone recovers the secret"
        if threshold == 1
        else "Single shard cannot recover the secret"
    )
    copy: dict[str, object] = {
        "title": f"{prefix}Shard Document",
        "subtitle": f"{prefix}Shard {shard_index} of {shard_total}",
        "qr_caption": f"Shard {shard_index} of {shard_total}",
        "header_guidance": guidance,
        "footer_guidance": guidance,
        "handling_guidance": f"Passphrase Shard // Store Separately // {guidance}",
        "warning_title": "Critical Security Notice",
        "warning_body": (
            f"This document contains {prefix.lower()}shard {shard_index} of {shard_total}. "
            f"{recovery_notice} "
            f"Recovery requires {threshold}/{shard_total} shards. Keep this sheet secure and "
            "separate from recovery documents and other shards."
        ),
        "manual_transcription_label": "Manual Transcription",
    }
    if prefix:
        copy["origin_badge"] = _origin_label(context)
    if origin == "replacement_recovery":
        copy["warning_body"] = (
            str(copy["warning_body"]) + " Verify this set before retiring any older set."
        )
    return copy


def _signing_key_shard_document_copy(*, context: Mapping[str, object]) -> dict[str, object]:
    shard_index = _int_value(context.get("shard_index"), default=1)
    shard_total = _int_value(context.get("shard_total"), default=1)
    threshold = _int_value(context.get("shard_threshold"), default=shard_total)
    origin = _origin_kind(context)
    prefix = {
        "rebuilt_backup": "Rebuilt Backup ",
        "replacement_recovery": "Replacement ",
    }.get(origin, "")
    recovery_notice = _shard_recovery_notice(threshold, secret="signing key")
    append_permission = (
        "This shard alone can authorize future extensions."
        if threshold == 1
        else "A quorum can authorize future extensions."
    )
    guidance = (
        "This shard alone recovers the signing key"
        if threshold == 1
        else "Store apart from passphrase and sibling signing-key shards"
    )
    copy: dict[str, object] = {
        "title": f"{prefix}Signing Key Shard",
        "subtitle": f"{prefix.rstrip()} - Signing key shard {shard_index} of {shard_total}"
        if prefix
        else f"Signing key shard {shard_index} of {shard_total}",
        "qr_caption": f"Shard {shard_index} of {shard_total}",
        "header_guidance": guidance,
        "footer_guidance": guidance,
        "warning_title": "Critical Security Notice",
        "warning_body": (
            f"{recovery_notice} {append_permission} "
            "Store apart from passphrase documents and other signing-key shards."
        ),
        "key_share_label": "Key Share",
        "document_id_label": "Document ID",
        "empty_fallback_text": "No fallback payload on this page.",
    }
    if prefix:
        copy["origin_badge"] = _origin_label(context)
    if origin == "replacement_recovery":
        copy["warning_body"] = (
            str(copy["warning_body"]) + " Verify this set before retiring any older set."
        )
    return copy


def _kit_index_document_copy(*, context: Mapping[str, object]) -> dict[str, object]:
    origin_kind = _origin_kind(context)
    if origin_kind == "rebuilt_backup":
        return {
            "title": "Rebuilt Backup Recovery Kit Index",
            "subtitle": "Rebuilt Backup - Inventory + Handling Log",
            "header_guidance": "Inventory record only; keep separate from backup recovery docs",
            "footer_guidance": "Inventory record only; keep separate from backup recovery docs",
            "warning_title": "Critical Security Warning",
            "warning_body": (
                "This document is an inventory index for the rebuilt backup only. Keep "
                "it separate from shard and recovery documents."
            ),
            "hardware_inventory_label": "Hardware Inventory",
            "handling_log_label": "Handling Log",
            "origin_badge": "Rebuilt Backup",
        }
    return {
        "title": "Recovery Kit Index",
        "subtitle": "Inventory + Handling Log",
        "header_guidance": "Inventory record only; keep separate from shard/recovery docs",
        "footer_guidance": "Inventory record only; keep separate from shard/recovery docs",
        "warning_title": "Critical Security Warning",
        "warning_body": (
            "This document is an inventory index only. Keep it separate from shard and "
            "recovery documents."
        ),
        "hardware_inventory_label": "Hardware Inventory",
        "handling_log_label": "Handling Log",
    }
