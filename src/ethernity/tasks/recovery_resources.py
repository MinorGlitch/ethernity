"""Present recoverable work-limit failures without interpreting exception text."""

from __future__ import annotations

from dataclasses import dataclass

from ethernity.crypto.age_policy import RecoveryWorkLimitExceeded


@dataclass(frozen=True, slots=True)
class RecoveryResourceRetry:
    memory_bytes: int

    @property
    def message(self) -> str:
        memory_mib = round(self.memory_bytes / (1024 * 1024))
        return (
            f"Estimated peak memory for unlocking: about {memory_mib:,} MiB, "
            "plus application overhead. Higher limits apply to this attempt only."
        )


def recovery_resource_retry(error: BaseException | None) -> RecoveryResourceRetry | None:
    """Preserve typed resource information through workflow exception wrappers."""

    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, RecoveryWorkLimitExceeded):
            return RecoveryResourceRetry(memory_bytes=error.memory_bytes)
        error = error.__cause__
    return None
