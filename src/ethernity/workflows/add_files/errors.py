"""Typed Add Files workflow failures independent of adapter serialization."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AddFilesIssue:
    """A stable, adapter-neutral Add Files issue."""

    code: str
    message: str
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


class AddFilesWorkflowError(Exception):
    """Raised when Add Files cannot produce a valid result."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.issue = AddFilesIssue(code=code, message=message, details=details or {})

    @property
    def code(self) -> str:
        return self.issue.code

    @property
    def message(self) -> str:
        return self.issue.message

    @property
    def details(self) -> dict[str, object]:
        return self.issue.details
