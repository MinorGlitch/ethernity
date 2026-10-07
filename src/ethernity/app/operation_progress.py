"""Small, deliberately filtered presentation of workflow activity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from time import monotonic
from typing import Any

from ethernity.workflows.shared.execution_control import ExecutionControl

_PHASES = {
    "configuration": "Checking configuration",
    "source": "Reading backup documents",
    "authentication": "Verifying signatures",
    "unlock": "Reading recovery sheets",
    "output": "Preparing destination",
    "plan": "Checking inputs",
    "input": "Reading files",
    "scan": "Scanning backup documents",
    "backup": "Preparing backup",
    "prepare": "Preparing",
    "encrypt": "Encrypting files",
    "shard": "Preparing recovery sheets",
    "generate": "Preparing recovery sheets",
    "render": "Creating PDFs",
    "verify": "Checking generated documents",
    "validate": "Checking generated documents",
    "decrypt": "Unlocking backup",
    "write": "Preparing restored files",
    "save": "Saving output",
    "publish": "Saving output",
}

_DOCUMENTS = {
    "main": "Backup PDF",
    "recovery": "Recovery text PDF",
    "shard": "Recovery sheet",
    "signing_key_shard": "Signing-key sheet",
    "kit": "Recovery kit",
    "kit_index": "Document guide",
}


_PREPARE = (
    "",
    "plan",
    "configuration",
    "source",
    "authentication",
    "unlock",
    "output",
    "input",
    "scan",
    "backup",
    "prepare",
    "decrypt",
)
_DOCUMENT_STEPS = (
    ("Prepare", _PREPARE),
    ("Create PDFs", ("render",)),
    ("Check documents", ("verify", "validate")),
    ("Save output", ("save", "publish")),
)


def operation_steps(task: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if task in {"backup", "rebuild"}:
        return (
            ("Read files" if task == "backup" else "Read backup", _PREPARE),
            ("Encrypt backup", ("encrypt", "shard")),
            *_DOCUMENT_STEPS[1:],
        )
    if task == "restore":
        return (
            (
                "Read and verify documents",
                ("", "plan", "configuration", "source", "authentication", "scan", "input"),
            ),
            ("Unlock backup", ("unlock", "decrypt")),
            ("Prepare files", ("write",)),
            ("Save files", ("save",)),
        )
    if task == "replace_recovery_docs":
        return (
            ("Read backup", _PREPARE),
            ("Prepare sheets", ("generate",)),
            ("Create and check PDFs", ("render",)),
            _DOCUMENT_STEPS[-1],
        )
    return _DOCUMENT_STEPS


@dataclass(frozen=True)
class OperationProgress:
    phase: str = ""
    stage: str = "Starting"
    current: int | None = None
    total: int | None = None
    unit: str = ""
    document: str = ""
    documents_done: int | None = None
    documents_total: int | None = None
    destination: str = ""
    can_cancel: bool = True
    stopping: bool = False
    activity: tuple[str, ...] = ()

    @property
    def count_text(self) -> str:
        if self.current is None:
            return ""
        if self.total is None:
            return f"{self.current} {self.unit} processed"
        count = f"{self.current} of {self.total} {self.unit}"
        if self.document:
            count = f"{self.document}: {count}"
        if self.unit == "pages" and self.documents_total is not None:
            return f"{self.documents_done} of {self.documents_total} PDFs complete\n{count}"
        return count


class OperationProgressSink:
    """Ignore raw arguments, results, paths and labels that may contain secrets."""

    def __init__(
        self,
        control: ExecutionControl,
        publish: Callable[[OperationProgress], None],
    ) -> None:
        self._control = control
        self._publish = publish
        self._last_publish = 0.0
        self.snapshot = OperationProgress()

    def emit(self, event_type: str, **payload: Any) -> None:
        if event_type == "destination":
            self.snapshot = replace(self.snapshot, destination=str(payload["path"]))
        elif event_type in {"phase", "progress"}:
            stage = _PHASES.get(str(payload.get("id" if event_type == "phase" else "phase")))
            if stage is None:
                return
            phase = str(payload.get("id" if event_type == "phase" else "phase"))
            if self._control.committing and phase == "write":
                stage = "Saving output"
                phase = "save"
            previous = self.snapshot
            changed = previous.stage != stage
            activity = previous.activity
            if changed:
                activity = (*activity, stage)[-24:]
            current = total = None
            unit = payload.get("unit", "")
            if event_type == "progress" and unit in {"files", "documents", "pages", "bytes"}:
                current = max(0, int(payload["current"]))
                total = payload.get("total")
                if total is not None:
                    total = max(current, int(total)) or None
            self.snapshot = replace(
                previous,
                phase=phase,
                stage=stage,
                current=current,
                total=total,
                unit=unit,
                activity=activity,
                document=_DOCUMENTS.get(str(payload.get("details", {}).get("document_type")), ""),
                documents_done=current if unit == "documents" else previous.documents_done,
                documents_total=total if unit == "documents" else previous.documents_total,
            )
            if event_type == "progress" and not changed and monotonic() - self._last_publish < 0.1:
                return
        else:
            return
        self.snapshot = replace(
            self.snapshot,
            can_cancel=self._control.can_cancel,
            stopping=self._control.cancel_requested,
        )
        self._last_publish = monotonic()
        self._publish(self.snapshot)
