"""Failure metadata that does not depend on presentation wording."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FailureStage(StrEnum):
    CONFIGURATION = "configuration"
    SOURCE = "source"
    INPUT = "input"
    AUTHENTICATION = "authentication"
    UNLOCK = "unlock"
    SELECTION = "selection"
    LAYOUT = "layout"
    OUTPUT = "output"
    RECOVERY = "recovery"


@dataclass(frozen=True, slots=True)
class FailureInfo:
    code: str
    stage: FailureStage | None = None
