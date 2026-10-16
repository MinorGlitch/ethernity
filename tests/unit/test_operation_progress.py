from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from ethernity.app.operation_progress import OperationProgress, OperationProgressSink
from ethernity.workflows.shared import events, outputs
from ethernity.workflows.shared.execution_control import (
    ExecutionControl,
    OperationCancelled,
    cancellation_point,
    execution_session,
)


def test_cancellation_and_commit_are_mutually_exclusive() -> None:
    for _ in range(20):
        control = ExecutionControl()
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def commit(
            control: ExecutionControl, barrier: threading.Barrier, outcomes: list[str]
        ) -> None:
            barrier.wait()
            try:
                control.begin_commit()
                outcomes.append("committed")
            except OperationCancelled:
                outcomes.append("cancelled")

        worker = threading.Thread(target=commit, args=(control, barrier, outcomes))
        worker.start()
        barrier.wait()
        accepted = control.request_cancel()
        worker.join(timeout=2)
        assert outcomes == ["cancelled" if accepted else "committed"]
        assert not control.can_cancel


def test_cancelled_restore_removes_staging_and_preserves_destination(tmp_path: Path) -> None:
    destination = tmp_path / "restore"
    destination.mkdir()
    control = ExecutionControl()

    class CancelAfterFirstFile:
        def emit(self, event_type: str, **payload: object) -> None:
            if event_type == "progress" and payload.get("current") == 1:
                control.request_cancel()

    with execution_session(control), events.event_session(CancelAfterFirstFile()):
        with pytest.raises(OperationCancelled):
            outputs.write_recovered_outputs(
                str(destination),
                [
                    (SimpleNamespace(path="first.txt"), b"first"),
                    (SimpleNamespace(path="second.txt"), b"second"),
                ],
            )
    assert destination.is_dir()
    assert list(destination.iterdir()) == []
    assert list(tmp_path.iterdir()) == [destination]


def test_last_checkpoint_prevents_publication_and_commit_rejects_cancellation(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "payload").write_bytes(b"data")
    final = tmp_path / "final"
    control = ExecutionControl()
    control.request_cancel()
    with execution_session(control), pytest.raises(OperationCancelled):
        outputs.commit_prepared_output_dir(staging, final)
    assert not final.exists()
    assert staging.exists()  # The owning workflow performs cleanup when this unwinds.

    control = ExecutionControl()
    with execution_session(control):
        outputs.commit_prepared_output_dir(staging, final)
        assert not control.request_cancel()
        cancellation_point()
    assert (final / "payload").read_bytes() == b"data"


def test_progress_only_exposes_curated_activity_and_real_counts() -> None:
    published: list[OperationProgress] = []
    sink = OperationProgressSink(ExecutionControl(), published.append)
    secret = "do-not-display-this-secret"
    for event_type in ("started", "result", "error", "warning", "file"):
        sink.emit(event_type, args={"passphrase": secret}, message=secret, path=secret)
    sink.emit("phase", id="encrypt", label=secret)
    sink.emit("progress", phase="encrypt", current=1, total=1, unit="step", label=secret)
    assert sink.snapshot.total is None
    sink.emit(
        "progress",
        phase="render",
        current=2,
        total=4,
        unit="pages",
        details={"document_type": "recovery", "passphrase": secret},
    )
    assert sink.snapshot.count_text == "Recovery text PDF: 2 of 4 pages"
    assert secret not in repr(published)
    assert secret not in repr(sink.snapshot)


def test_progress_disables_cancel_at_final_write() -> None:
    published: list[OperationProgress] = []
    control = ExecutionControl()
    sink = OperationProgressSink(control, published.append)
    with execution_session(control), events.event_session(sink):
        events.emit_phase(phase="publish", label="Publishing update")
        assert published[-1].can_cancel
        events.emit_finalizing()
    assert published[-1].stage == "Saving output"
    assert not published[-1].can_cancel
    assert not control.request_cancel()
