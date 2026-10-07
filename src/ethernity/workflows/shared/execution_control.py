"""Cooperative cancellation up to the first irreversible output write."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock


class OperationCancelled(BaseException):
    """Unwind staging cleanup without being mistaken for a workflow failure."""


class ExecutionControl:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cancel_requested = False
        self._committing = False

    @property
    def can_cancel(self) -> bool:
        with self._lock:
            return not self._committing and not self._cancel_requested

    @property
    def cancel_requested(self) -> bool:
        with self._lock:
            return self._cancel_requested

    @property
    def committing(self) -> bool:
        with self._lock:
            return self._committing

    def request_cancel(self) -> bool:
        with self._lock:
            if self._committing:
                return False
            self._cancel_requested = True
            return True

    def checkpoint(self) -> None:
        with self._lock:
            if self._cancel_requested:
                raise OperationCancelled

    def begin_commit(self) -> None:
        # Cancellation and publication must agree on which one happened first.
        with self._lock:
            if self._cancel_requested:
                raise OperationCancelled
            self._committing = True


_ACTIVE_CONTROL: ContextVar[ExecutionControl | None] = ContextVar("execution_control", default=None)


@contextmanager
def execution_session(control: ExecutionControl) -> Iterator[None]:
    token = _ACTIVE_CONTROL.set(control)
    try:
        yield
    finally:
        _ACTIVE_CONTROL.reset(token)


def cancellation_point() -> None:
    control = _ACTIVE_CONTROL.get()
    if control is not None:
        control.checkpoint()


def begin_final_write() -> None:
    """Reject pending cancellation, then lock it for the remainder of this run."""
    control = _ACTIVE_CONTROL.get()
    if control is not None:
        control.begin_commit()
