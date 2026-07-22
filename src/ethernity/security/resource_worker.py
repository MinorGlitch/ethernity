"""Disposable subprocesses with fail-closed resource limits."""

from __future__ import annotations

import ctypes
import multiprocessing
import os
import pickle
import signal
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import TypeVar, cast

import psutil

ResultT = TypeVar("ResultT")


@dataclass(frozen=True, slots=True)
class WorkerLimits:
    """Hard resource ceilings for one hostile operation."""

    memory_bytes: int
    cpu_seconds: int
    wall_seconds: float
    output_bytes: int

    def __post_init__(self) -> None:
        if self.memory_bytes < 1:
            raise ValueError("worker memory limit must be positive")
        if self.cpu_seconds < 1:
            raise ValueError("worker CPU limit must be positive")
        if self.wall_seconds <= 0:
            raise ValueError("worker wall-time limit must be positive")
        if self.output_bytes < 1:
            raise ValueError("worker output limit must be positive")


class DisposableWorkerError(RuntimeError):
    """A bounded worker failed, exceeded a limit, or was terminated."""


_active_workers: set[BaseProcess] = set()
_active_workers_lock = threading.Lock()
_windows_job_handle: int | None = None


def run_disposable_worker(
    operation: str,
    target: Callable[..., ResultT],
    args: tuple[object, ...],
    *,
    limits: WorkerLimits,
) -> ResultT:
    """Run one picklable operation in a fresh, resource-bounded subprocess."""

    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker_main,
        args=(child_connection, target, args, limits),
        name=f"ethernity-{operation}",
        daemon=True,
    )
    try:
        process.start()
    except (OSError, RuntimeError, ValueError) as exc:
        parent_connection.close()
        child_connection.close()
        raise DisposableWorkerError(f"{operation} worker could not start") from exc
    child_connection.close()
    with _active_workers_lock:
        _active_workers.add(process)
    monitored_process = psutil.Process(process.pid)

    deadline = time.monotonic() + limits.wall_seconds
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process(process)
                raise DisposableWorkerError(
                    f"{operation} exceeded its {limits.wall_seconds:g} second wall-time limit"
                )
            if parent_connection.poll(min(remaining, 0.05)):
                try:
                    payload = parent_connection.recv_bytes(limits.output_bytes + 4096)
                except (EOFError, OSError) as exc:
                    _terminate_process(process)
                    raise DisposableWorkerError(
                        f"{operation} worker returned excessive or invalid output"
                    ) from exc
                try:
                    status, value = pickle.loads(payload)
                except (pickle.PickleError, EOFError, ValueError, TypeError) as exc:
                    raise DisposableWorkerError(
                        f"{operation} worker returned invalid output"
                    ) from exc
                process.join(timeout=1)
                if status == "ok":
                    return cast(ResultT, value)
                raise DisposableWorkerError(f"{operation} worker failed: {value}")
            _enforce_parent_observed_limits(operation, process, monitored_process, limits)
            if not process.is_alive():
                process.join(timeout=1)
                raise DisposableWorkerError(
                    f"{operation} worker was terminated by a CPU or memory limit"
                )
    finally:
        parent_connection.close()
        if process.is_alive():
            _terminate_process(process)
        else:
            process.join(timeout=1)
        with _active_workers_lock:
            _active_workers.discard(process)


def terminate_active_workers() -> None:
    """Terminate every active hostile-input worker in this application process."""

    with _active_workers_lock:
        workers = tuple(_active_workers)
    for process in workers:
        _terminate_process(process)


def _worker_main(
    connection: Connection,
    target: Callable[..., object],
    args: tuple[object, ...],
    limits: WorkerLimits,
) -> None:
    try:
        _install_resource_limits(limits)
        result = target(*args)
        payload = pickle.dumps(("ok", result), protocol=pickle.HIGHEST_PROTOCOL)
        if len(payload) > limits.output_bytes:
            raise RuntimeError("worker output limit exceeded")
    except BaseException as exc:  # worker boundary must normalize library/process failures
        message = str(exc).strip() or type(exc).__qualname__
        payload = pickle.dumps(("error", message[:4096]), protocol=pickle.HIGHEST_PROTOCOL)
    try:
        connection.send_bytes(payload)
    except (BrokenPipeError, EOFError, OSError):
        pass
    finally:
        connection.close()


def _terminate_process(process: BaseProcess) -> None:
    if not process.is_alive():
        process.join(timeout=0.1)
        return
    process.terminate()
    process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)


def _install_resource_limits(limits: WorkerLimits) -> None:
    if os.name == "nt":
        _install_windows_job_limits(limits)
        return
    try:
        import resource

        if sys.platform != "darwin":
            resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        if hasattr(resource, "RLIMIT_CORE"):
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if hasattr(resource, "RLIMIT_FSIZE"):
            resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    except (ImportError, OSError, ValueError) as exc:
        raise RuntimeError(
            "worker resource isolation is unavailable on this platform: "
            f"{type(exc).__qualname__}: {exc}"
        ) from exc
    signal.signal(signal.SIGXCPU, signal.SIG_DFL)


def _enforce_parent_observed_limits(
    operation: str,
    process: BaseProcess,
    monitored_process: psutil.Process,
    limits: WorkerLimits,
) -> None:
    try:
        memory_bytes = monitored_process.memory_info().rss
        cpu_times = monitored_process.cpu_times()
    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
        return
    if memory_bytes > limits.memory_bytes:
        _terminate_process(process)
        raise DisposableWorkerError(f"{operation} exceeded its memory limit")
    if cpu_times.user + cpu_times.system > limits.cpu_seconds:
        _terminate_process(process)
        raise DisposableWorkerError(f"{operation} exceeded its CPU limit")


def _install_windows_job_limits(limits: WorkerLimits) -> None:
    global _windows_job_handle

    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise RuntimeError("Windows job object creation failed")

    process_time_limit = 0x00000002
    process_memory_limit = 0x00000100
    kill_on_job_close = 0x00002000
    info = ExtendedLimitInformation()
    info.BasicLimitInformation.PerProcessUserTimeLimit = limits.cpu_seconds * 10_000_000
    info.BasicLimitInformation.LimitFlags = (
        process_time_limit | process_memory_limit | kill_on_job_close
    )
    info.ProcessMemoryLimit = limits.memory_bytes
    if not kernel32.SetInformationJobObject(
        job,
        9,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        kernel32.CloseHandle(job)
        raise RuntimeError("Windows job object limits could not be installed")
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        kernel32.CloseHandle(job)
        raise RuntimeError("worker could not enter its Windows job object")
    _windows_job_handle = int(job)
