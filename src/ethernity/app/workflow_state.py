from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(slots=True)
class WorkflowUiState:
    """Session-only interaction state for one guided workflow.

    Task models continue to own domain values and validation. This object owns only what the
    presentation needs to know about the user's progress through the current app session.
    """

    step_keys: tuple[str, ...]
    active_step: str
    touched_fields: set[str] = field(default_factory=set)
    attempted_review: bool = False
    advanced_expanded: bool = False
    source_assessment_loading: bool = False
    draft_values: dict[str, dict[str, str]] = field(default_factory=dict)
    draft_errors: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.step_keys:
            raise ValueError("a guided workflow must define at least one step")
        if len(self.step_keys) != len(set(self.step_keys)):
            raise ValueError("guided workflow step keys must be unique")
        self.activate(self.active_step)

    @classmethod
    def start(cls, *step_keys: str) -> WorkflowUiState:
        if not step_keys:
            raise ValueError("a guided workflow must define at least one step")
        return cls(step_keys=step_keys, active_step=step_keys[0])

    def activate(self, step_key: str) -> None:
        if step_key not in self.step_keys:
            raise KeyError(f"unknown workflow step: {step_key}")
        self.active_step = step_key

    def touch(self, *field_keys: str) -> None:
        self.touched_fields.update(field_keys)

    def untouch(self, *field_keys: str) -> None:
        self.touched_fields.difference_update(field_keys)

    def is_touched(self, field_key: str) -> bool:
        return field_key in self.touched_fields

    def mark_review_attempted(self) -> None:
        self.attempted_review = True

    def set_invalid_draft(
        self,
        step_key: str,
        values: Mapping[str, str],
        *,
        message: str,
    ) -> None:
        if step_key not in self.step_keys:
            raise KeyError(f"unknown workflow step: {step_key}")
        self.draft_values[step_key] = dict(values)
        self.draft_errors[step_key] = message

    def clear_draft(self, step_key: str) -> None:
        self.draft_values.pop(step_key, None)
        self.draft_errors.pop(step_key, None)

    def has_invalid_draft(self, step_key: str | None = None) -> bool:
        """Report invalid UI drafts for one step, or anywhere in this workflow."""

        if step_key is None:
            return bool(self.draft_errors)
        return step_key in self.draft_errors

    def draft_error(self, step_key: str) -> str | None:
        return self.draft_errors.get(step_key)

    def reset_interaction(self) -> None:
        self.touched_fields.clear()
        self.attempted_review = False
        self.draft_values.clear()
        self.draft_errors.clear()
