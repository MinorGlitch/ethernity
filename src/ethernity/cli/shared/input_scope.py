"""Compatibility facade for adapter-neutral input-scope services."""

from ethernity.workflows.shared.input_scope import (
    InputScopeDiff,
    SelectedInputScope,
    empty_scope_inspection_payload,
    load_input_scope,
    scope_path_selectors,
    summarize_input_scope_diff,
)

__all__ = [
    "InputScopeDiff",
    "SelectedInputScope",
    "empty_scope_inspection_payload",
    "load_input_scope",
    "scope_path_selectors",
    "summarize_input_scope_diff",
]
