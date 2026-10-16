"""Errors shared by render validation and its isolated PDF worker."""

from collections.abc import Mapping


class RenderValidationError(ValueError):
    """Raised when a rendered document does not match its recorded summary."""

    def __init__(self, message: str, *, details: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})
