"""Resolved backup choices shared by previews, workspaces, and final review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ethernity.tasks.backup_estimate import BackupEstimate
from ethernity.tasks.file_summary import format_count

RecoveryMethod = Literal["recommended_shards", "single_phrase", "custom_shards"]
SigningKeyMode = Literal["embedded", "sharded"]


@dataclass(frozen=True, slots=True)
class SheetQuorum:
    required: int
    total: int

    @property
    def summary(self) -> str:
        return f"{self.total} recovery sheets; any {self.required} required"


RECOMMENDED_RECOVERY = SheetQuorum(required=2, total=3)


@dataclass(frozen=True, slots=True)
class RecoveryOption:
    key: RecoveryMethod
    label: str
    selected: bool


@dataclass(frozen=True, slots=True)
class BackupDocument:
    kind: Literal["backup", "guide", "recovery", "signing", "inventory"]
    label: str
    detail: str = ""
    review_label: str | None = None
    compact_label: str = ""


@dataclass(frozen=True, slots=True)
class BackupFacts:
    recovery_method: RecoveryMethod
    recovery: SheetQuorum | None
    custom_recovery: SheetQuorum
    signing_key_mode: SigningKeyMode | None
    signing_quorum: SheetQuorum
    include_inventory: bool
    selected_files: int
    selected_folders: int
    estimate: BackupEstimate | None
    estimate_error: str | None

    @property
    def recovery_summary(self) -> str:
        if self.recovery is None:
            return "One recovery phrase"
        if self.recovery_method == "recommended_shards":
            return (
                f"{self.recovery.total} recovery sheets; "
                f"any {self.recovery.required} can restore (recommended)"
            )
        return self.recovery.summary

    @property
    def storage_note(self) -> str:
        if self.recovery is None:
            return "Keep the recovery phrase separate from backup pages."
        return "Store recovery sheets separately from backup pages."

    @property
    def recovery_options(self) -> tuple[RecoveryOption, ...]:
        recommended = RECOMMENDED_RECOVERY
        labels = (
            (
                "recommended_shards",
                f"{recommended.total} sheets, any {recommended.required} unlock (recommended)",
            ),
            ("single_phrase", "Single recovery phrase"),
            (
                "custom_shards",
                f"Custom: {self.custom_recovery.total} sheets; "
                f"any {self.custom_recovery.required} required",
            ),
        )
        return tuple(
            RecoveryOption(key, label, self.recovery_method == key) for key, label in labels
        )

    @property
    def signing_recovery(self) -> SheetQuorum | None:
        if self.signing_key_mode == "sharded" and self.recovery is not None:
            return self.signing_quorum
        return None

    @property
    def signing_summary(self) -> str:
        if self.signing_key_mode == "sharded":
            quorum = self.signing_quorum
            return f"{quorum.total} key sheets; any {quorum.required} can recover the key"
        if self.signing_key_mode is None:
            return "From settings"
        return "Embedded in backup"

    @property
    def documents(self) -> tuple[BackupDocument, ...]:
        main_label = (
            f"About {format_count(self.estimate.backup_pages, 'backup page')}"
            if self.estimate is not None
            else "Backup pages"
        )
        documents = [
            BackupDocument("backup", main_label, "Contain your encrypted files", "Backup PDF"),
            BackupDocument(
                "guide",
                "Recovery guide",
                "Instructions and a full text backup",
                "Recovery guide",
                "guide",
            ),
        ]
        if self.recovery is None:
            documents.append(
                BackupDocument("recovery", "One recovery phrase", compact_label="1 recovery phrase")
            )
        else:
            label = format_count(self.recovery.total, "recovery sheet")
            documents.append(
                BackupDocument(
                    "recovery",
                    label,
                    f"Any {self.recovery.required} unlock the backup",
                    label,
                    label,
                )
            )
        if self.signing_recovery is not None:
            quorum = self.signing_recovery
            label = format_count(quorum.total, "signing-key recovery sheet")
            documents.append(
                BackupDocument(
                    "signing",
                    label,
                    f"any {quorum.required} can restore",
                    label,
                    format_count(quorum.total, "key sheet"),
                )
            )
        if self.include_inventory:
            documents.append(
                BackupDocument(
                    "inventory",
                    "Document inventory",
                    "Lists the printed kit",
                    "Document inventory PDF",
                    "inventory",
                )
            )
        return tuple(documents)

    @property
    def document_summary(self) -> str:
        return "\n".join(doc.review_label for doc in self.documents if doc.review_label is not None)

    @property
    def compact_document_summary(self) -> str:
        documents = self.documents
        main = next(doc.label for doc in documents if doc.kind == "backup")
        recovery = next(doc.compact_label for doc in documents if doc.kind == "recovery")
        extras = [
            doc.compact_label
            for kind in ("guide", "inventory", "signing")
            for doc in documents
            if doc.kind == kind
        ]
        return f"{main} + {recovery}\nAlso: {', '.join(extras)}"
