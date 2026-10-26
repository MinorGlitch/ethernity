from __future__ import annotations

import threading
import time

import pytest

from ethernity.core.execution_control import ExecutionControl, OperationCancelled, execution_session
from ethernity.security import resource_worker
from ethernity.security.resource_worker import (
    DisposableWorkerError,
    WorkerLimits,
    run_disposable_worker,
)

pytestmark = pytest.mark.portability


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


def test_completed_worker_result_is_read_after_timed_poll_misses_it(monkeypatch) -> None:
    poll = resource_worker.Connection.poll
    first_poll = True

    def miss_first_poll(connection, timeout=0):
        nonlocal first_poll
        if first_poll:
            first_poll = False
            return False
        return poll(connection, timeout)

    def finish_before_liveness_check(_operation, process, _monitored, _limits):
        process.join(timeout=5)
        assert process.exitcode == 0

    monkeypatch.setattr(resource_worker.Connection, "poll", miss_first_poll)
    monkeypatch.setattr(
        resource_worker, "_enforce_parent_observed_limits", finish_before_liveness_check
    )

    assert run_disposable_worker("test", _return_bytes, (8,), limits=_limits()) == b"x" * 8
    assert not first_poll


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


def test_cancellation_only_stops_its_own_worker(monkeypatch) -> None:
    outcomes: dict[str, object] = {}
    started = {name: threading.Event() for name in ("cancelled", "independent")}
    control = ExecutionControl()
    enforce_limits = resource_worker._enforce_parent_observed_limits

    def observe_start(operation, process, monitored, limits):
        started[operation].set()
        enforce_limits(operation, process, monitored, limits)

    monkeypatch.setattr(resource_worker, "_enforce_parent_observed_limits", observe_start)

    def run_worker(name: str, operation_control: ExecutionControl, seconds: float) -> None:
        try:
            with execution_session(operation_control):
                run_disposable_worker(name, _sleep, (seconds,), limits=_limits(wall_seconds=10))
            outcomes[name] = "completed"
        except BaseException as exc:
            outcomes[name] = exc

    cancelled = threading.Thread(target=run_worker, args=("cancelled", control, 5.0))
    independent = threading.Thread(target=run_worker, args=("independent", ExecutionControl(), 0.5))
    cancelled.start()
    independent.start()
    try:
        assert all(event.wait(timeout=5) for event in started.values())
        control.request_cancel()
    finally:
        cancelled.join(timeout=7)
        independent.join(timeout=7)
    assert not cancelled.is_alive() and not independent.is_alive()
    assert isinstance(outcomes["cancelled"], OperationCancelled)
    assert outcomes["independent"] == "completed"


def test_cancelled_operation_does_not_start_another_worker(monkeypatch) -> None:
    control = ExecutionControl()
    control.request_cancel()

    def unexpected_start(*_args):
        pytest.fail("cancelled operation started a new subprocess")

    monkeypatch.setattr(resource_worker.multiprocessing, "get_context", unexpected_start)
    with execution_session(control), pytest.raises(OperationCancelled):
        run_disposable_worker("test", _return_bytes, (8,), limits=_limits())


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
