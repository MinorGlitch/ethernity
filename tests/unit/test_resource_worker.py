from __future__ import annotations

import threading
import time

import pytest

from ethernity.security import resource_worker
from ethernity.security.resource_worker import (
    DisposableWorkerError,
    WorkerLimits,
    run_disposable_worker,
    terminate_active_workers,
)


def _return_bytes(size: int) -> bytes:
    return b"x" * size


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _limits(*, wall_seconds: float = 5, output_bytes: int = 1024) -> WorkerLimits:
    return WorkerLimits(
        memory_bytes=256 * 1024 * 1024,
        cpu_seconds=5,
        wall_seconds=wall_seconds,
        output_bytes=output_bytes,
    )


def test_disposable_worker_returns_bounded_output() -> None:
    assert (
        run_disposable_worker(
            "test",
            _return_bytes,
            (8,),
            limits=_limits(),
        )
        == b"x" * 8
    )


def test_disposable_worker_rejects_excessive_output() -> None:
    with pytest.raises(DisposableWorkerError, match="output limit exceeded"):
        run_disposable_worker(
            "test",
            _return_bytes,
            (4096,),
            limits=_limits(output_bytes=128),
        )


def test_disposable_worker_enforces_wall_time() -> None:
    with pytest.raises(DisposableWorkerError, match="wall-time limit"):
        run_disposable_worker(
            "test",
            _sleep,
            (5.0,),
            limits=_limits(wall_seconds=0.2),
        )


def test_cancellation_terminates_active_worker() -> None:
    errors: list[BaseException] = []

    def run_worker() -> None:
        try:
            run_disposable_worker(
                "test",
                _sleep,
                (5.0,),
                limits=_limits(wall_seconds=10),
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_worker)
    thread.start()
    time.sleep(0.5)
    terminate_active_workers()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert errors and isinstance(errors[0], DisposableWorkerError)


def test_parent_monitor_hard_stops_worker_over_memory_limit(monkeypatch) -> None:
    process = object()
    monitored = type(
        "Monitored",
        (),
        {
            "memory_info": lambda self: type("Memory", (), {"rss": 300 * 1024 * 1024})(),
            "cpu_times": lambda self: type("Cpu", (), {"user": 0.0, "system": 0.0})(),
        },
    )()
    terminated: list[object] = []
    monkeypatch.setattr(resource_worker, "_terminate_process", terminated.append)

    with pytest.raises(DisposableWorkerError, match="memory limit"):
        resource_worker._enforce_parent_observed_limits(
            "test",
            process,
            monitored,
            _limits(),
        )

    assert terminated == [process]


def test_parent_monitor_hard_stops_worker_over_cpu_limit(monkeypatch) -> None:
    process = object()
    monitored = type(
        "Monitored",
        (),
        {
            "memory_info": lambda self: type("Memory", (), {"rss": 1})(),
            "cpu_times": lambda self: type("Cpu", (), {"user": 5.1, "system": 0.0})(),
        },
    )()
    terminated: list[object] = []
    monkeypatch.setattr(resource_worker, "_terminate_process", terminated.append)

    with pytest.raises(DisposableWorkerError, match="CPU limit"):
        resource_worker._enforce_parent_observed_limits(
            "test",
            process,
            monitored,
            _limits(),
        )

    assert terminated == [process]
