"""Presentation-model invariants used by workflow widgets."""

from dataclasses import replace

import pytest

from ethernity.app.workflow_state import WorkflowUiState
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    CompositeBodyPartPresentation,
    CompositeBodyPresentation,
    InlineNoticePresentation,
    OptionsBodyPresentation,
    SelectFieldPresentation,
    SelectOptionPresentation,
    SourceBodyPresentation,
    StepPresentation,
    UnlockBodyPresentation,
)
from tests.unit.app.widgets.workflow.helpers import make_source_body, make_workflow


def test_workflow_presentation_enforces_typed_step_invariants() -> None:
    with pytest.raises(ValueError, match="at most one"):
        SourceBodyPresentation(
            methods=(
                ChoicePresentation("scans", "Scanned pages", selected=True),
                ChoicePresentation("text", "Recovery text", selected=True),
            )
        )

    workflow = make_workflow(
        active_step="unlock",
        steps=(
            StepPresentation(
                "source",
                "Backup source",
                "complete",
                "4 scanned pages",
                make_source_body(selected="scans"),
            ),
            StepPresentation(
                "unlock",
                "Unlock backup",
                "current",
                "Passphrase required",
                UnlockBodyPresentation(),
                InlineNoticePresentation("Enter the backup passphrase.", tone="error"),
                "error",
            ),
        ),
    )

    assert workflow.progress_label == "Step 2 of 2"

    with pytest.raises(ValueError, match="exactly active_step"):
        replace(
            workflow,
            steps=(workflow.steps[0], replace(workflow.steps[1], state="locked")),
        )
    with pytest.raises(ValueError, match="exactly active_step"):
        replace(
            workflow,
            steps=(replace(workflow.steps[0], state="current"), workflow.steps[1]),
        )


def test_select_and_composite_presentations_enforce_keyed_structure() -> None:
    paper = SelectFieldPresentation(
        "workspace-rebuild-paper",
        "Paper size",
        (
            SelectOptionPresentation("A4", "A4"),
            SelectOptionPresentation("LETTER", "Letter"),
        ),
        value="A4",
        allow_blank=False,
    )

    with pytest.raises(ValueError, match="value must identify an option"):
        replace(paper, value="LEGAL")
    with pytest.raises(ValueError, match="option keys must be unique"):
        replace(
            paper,
            options=(
                SelectOptionPresentation("A4", "First"),
                SelectOptionPresentation("A4", "Second"),
            ),
        )
    with pytest.raises(ValueError, match="option select keys must be unique"):
        OptionsBodyPresentation(selects=(paper, paper))
    with pytest.raises(ValueError, match="requires a selected value"):
        replace(paper, value=None)

    source = CompositeBodyPartPresentation("source", make_source_body())
    with pytest.raises(ValueError, match="part keys must be unique"):
        CompositeBodyPresentation(parts=(source, source))
    with pytest.raises(ValueError, match="at least one part"):
        CompositeBodyPresentation()


def test_workflow_ui_state_keeps_interaction_lifecycle_out_of_task_models() -> None:
    state = WorkflowUiState.start("source", "unlock", "destination")

    state.activate("unlock")
    state.touch("unlock.method", "unlock.passphrase")
    state.mark_review_attempted()
    state.advanced_expanded = True
    state.set_invalid_draft(
        "unlock",
        {"threshold": "6", "count": "3"},
        message="Required sheets cannot exceed the total sheet count.",
    )

    assert state.active_step == "unlock"
    assert state.is_touched("unlock.passphrase")
    assert state.attempted_review
    assert state.advanced_expanded
    assert state.has_invalid_draft()
    assert state.has_invalid_draft("unlock")
    assert state.draft_values["unlock"] == {"threshold": "6", "count": "3"}
    assert state.draft_error("unlock") == ("Required sheets cannot exceed the total sheet count.")

    state.clear_draft("unlock")

    assert not state.has_invalid_draft()
    assert state.draft_error("unlock") is None

    state.set_invalid_draft("unlock", {"threshold": ""}, message="Enter a threshold.")

    state.reset_interaction()

    assert not state.touched_fields
    assert not state.attempted_review
    assert not state.has_invalid_draft()
    with pytest.raises(KeyError, match="unknown workflow step"):
        state.activate("missing")
