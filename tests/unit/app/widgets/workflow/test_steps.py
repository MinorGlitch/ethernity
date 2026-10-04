"""Workflow step composition and navigation behavior."""

import asyncio
from dataclasses import replace

import pytest
from textual.widgets import Button, Input, RadioSet, Static

from ethernity.app.widgets.workflow.options import OptionsEditor
from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.app.widgets.workflow.steps import (
    CompositeStepBody,
    WorkflowStep,
    WorkflowStepStack,
)
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    CompositeBodyPartPresentation,
    CompositeBodyPresentation,
    DestinationBodyPresentation,
    InlineNoticePresentation,
    OptionsBodyPresentation,
    StepPresentation,
    UnlockBodyPresentation,
    WorkspaceAction,
)
from tests.unit.app.widgets.workflow.widget_harness import (
    WorkflowWidgetHarness,
    sample_restore_workflow,
    sample_source_body,
)


def test_step_stack_shows_active_editor_and_focuses_its_first_control() -> None:
    async def run() -> None:
        workflow = sample_restore_workflow(
            active_step="source",
            steps=(
                StepPresentation(
                    "source",
                    "Backup source",
                    "current",
                    "Choose a source",
                    sample_source_body(),
                ),
                StepPresentation(
                    "unlock",
                    "Unlock backup",
                    "available",
                    "Waiting for source",
                    UnlockBodyPresentation(
                        methods=(ChoicePresentation("passphrase", "Passphrase", selected=True),)
                    ),
                ),
                StepPresentation(
                    "destination",
                    "Destination",
                    "available",
                    "Waiting for unlock",
                    DestinationBodyPresentation(),
                ),
            ),
        )
        stack = WorkflowStepStack(workflow, id="steps")
        app = WorkflowWidgetHarness(stack)
        async with app.run_test(size=(80, 24)) as pilot:
            steps = list(stack.query(WorkflowStep))
            bodies = list(stack.query(".guided-step-body"))

            assert [body.display for body in bodies] == [True, False, False]
            assert steps[0].region.height > 0
            assert steps[1].region.height == 0
            assert all(not step.can_focus for step in steps)

            stack.focus_active()
            await pilot.pause()
            assert app.focused is stack.query_one("#workflow-restore-source-body-load", Button)
            assert not steps[2].display

            updated = replace(
                workflow,
                active_step="unlock",
                steps=(
                    replace(workflow.steps[0], state="complete", summary="4 scanned pages"),
                    replace(
                        workflow.steps[1],
                        state="current",
                        summary="Passphrase required",
                        issue=InlineNoticePresentation(
                            "Enter the backup passphrase.",
                            tone="error",
                        ),
                        severity="error",
                    ),
                    workflow.steps[2],
                ),
            )
            stack.sync_presentation(updated)
            await pilot.pause()
            stack.focus_active()
            await pilot.pause()

            assert [body.display for body in bodies] == [False, True, False]
            assert not stack.query(".workflow-step-heading")
            assert app.focused is stack.query_one(
                "#workflow-restore-unlock-body RadioSet", RadioSet
            )
            await pilot.press("tab")
            assert app.focused is stack.query_one("#workflow-restore-unlock-body Input", Input)
            assert "Enter the backup passphrase" in str(
                steps[1].query_one(".guided-step-issue", Static).content
            )
            assert all(body.region.bottom <= 24 for body in bodies if body.display)

    asyncio.run(run())


def test_composite_step_body_keeps_keyed_parts_mounted_and_enforces_kinds() -> None:
    async def run() -> None:
        trust = OptionsBodyPresentation(
            actions=(WorkspaceAction("accept", "Use these scans", visible=False),)
        )
        body = CompositeBodyPresentation(
            parts=(
                CompositeBodyPartPresentation(
                    "source", sample_source_body(), title="Backup documents"
                ),
                CompositeBodyPartPresentation("trust", trust, title="Backup version"),
            )
        )
        composite = CompositeStepBody(body, id="combined")
        app = WorkflowWidgetHarness(composite)
        async with app.run_test(size=(80, 24)) as pilot:
            source = composite.query_one("#combined-source", SourceChooser)
            trust_editor = composite.query_one("#combined-trust", OptionsEditor)

            assert source.display
            assert not trust_editor.display
            assert composite.region.bottom <= 24

            updated = replace(
                body,
                parts=(
                    body.parts[0],
                    replace(
                        body.parts[1],
                        body=replace(
                            trust,
                            actions=(WorkspaceAction("accept", "Use these scans"),),
                        ),
                    ),
                ),
            )
            composite.sync_presentation(updated)
            await pilot.pause()

            assert trust_editor.display

            with pytest.raises(ValueError, match="part keys cannot change"):
                composite.sync_presentation(
                    replace(
                        updated,
                        parts=(updated.parts[0], replace(updated.parts[1], key="freshness")),
                    )
                )
            with pytest.raises(ValueError, match="part kinds cannot change"):
                composite.sync_presentation(
                    replace(
                        updated,
                        parts=(
                            updated.parts[0],
                            replace(updated.parts[1], body=DestinationBodyPresentation()),
                        ),
                    )
                )

    asyncio.run(run())


def test_hidden_optional_section_stays_mounted_and_can_be_disclosed() -> None:
    async def run() -> None:
        workflow = sample_restore_workflow(
            active_step="source",
            steps=(
                StepPresentation("source", "Backup", "current", "Loaded", sample_source_body()),
                StepPresentation(
                    "target",
                    "Version",
                    "complete",
                    "Newest supplied version",
                    OptionsBodyPresentation(),
                    visible=False,
                ),
                StepPresentation(
                    "destination",
                    "Save to",
                    "available",
                    "Choose folder",
                    DestinationBodyPresentation(),
                ),
            ),
        )
        stack = WorkflowStepStack(workflow)
        app = WorkflowWidgetHarness(stack)
        async with app.run_test(size=(80, 24)) as pilot:
            target = stack.query_one("#workflow-restore-target")
            assert target is not None and not target.display
            assert not stack.query_one("#workflow-restore-destination").disabled
            stack.sync_presentation(
                replace(
                    workflow,
                    active_step="target",
                    steps=(
                        replace(workflow.steps[0], state="complete"),
                        replace(workflow.steps[1], visible=True, state="current"),
                        workflow.steps[2],
                    ),
                )
            )
            await pilot.pause()
            assert target.display

    asyncio.run(run())
