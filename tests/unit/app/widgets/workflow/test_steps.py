"""Workflow step composition and navigation behavior."""

import asyncio
from dataclasses import replace

import pytest
from textual.widgets import Static

from ethernity.app.widgets.workflow.options import OptionsEditor
from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.app.widgets.workflow.steps import (
    CompositeStepBody,
    WorkflowStepHeader,
    WorkflowStepStack,
)
from ethernity.tasks.presentation.models import (
    CompositeBodyPartPresentation,
    CompositeBodyPresentation,
    DestinationBodyPresentation,
    InlineNoticePresentation,
    OptionsBodyPresentation,
    StepPresentation,
    UnlockBodyPresentation,
    WorkspaceAction,
)
from tests.unit.app.widgets.workflow.helpers import (
    PrimitiveHarness,
    make_source_body,
    make_workflow,
)


def test_step_stack_expands_only_active_step_and_reports_keyboard_requests() -> None:
    async def run() -> None:
        workflow = make_workflow(
            active_step="source",
            steps=(
                StepPresentation(
                    "source",
                    "Backup source",
                    "current",
                    "Choose a source",
                    make_source_body(),
                ),
                StepPresentation(
                    "unlock",
                    "Unlock backup",
                    "locked",
                    "Waiting for source",
                    UnlockBodyPresentation(),
                ),
                StepPresentation(
                    "destination",
                    "Destination",
                    "locked",
                    "Waiting for unlock",
                    DestinationBodyPresentation(),
                ),
            ),
        )
        stack = WorkflowStepStack(workflow, id="steps")
        app = PrimitiveHarness(stack)
        async with app.run_test(size=(80, 24)) as pilot:
            headers = list(stack.query(WorkflowStepHeader))
            bodies = list(stack.query(".guided-step-body"))

            assert [body.display for body in bodies] == [True, False, False]
            assert headers[1].disabled
            assert headers[0].region.height == 2
            assert headers[1].region.height == 1
            assert not headers[1].query_one(".workflow-step-summary", Static).display

            headers[0].focus()
            await pilot.press("enter")
            await pilot.pause()

            assert app.step_requests == ["source"]

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
            stack.focus_active()
            await pilot.pause()

            assert [body.display for body in bodies] == [False, True, False]
            assert headers[1].has_class("step-current")
            assert headers[1].has_class("step-error")
            assert str(headers[1].query_one(".workflow-step-status", Static).content) == (
                "Current / Error"
            )
            assert app.focused is headers[1]
            assert all(body.region.bottom <= 24 for body in bodies if body.display)

    asyncio.run(run())


def test_step_header_keeps_progress_and_severity_visible_without_wrapping() -> None:
    async def run() -> None:
        header = WorkflowStepHeader(
            StepPresentation(
                "source",
                "Existing backup",
                "current",
                "A very long source path that must not turn into a paragraph at narrow widths",
                make_source_body(),
                severity="warning",
            ),
            1,
        )
        app = PrimitiveHarness(header)
        async with app.run_test(size=(40, 8)):
            marker = header.query_one(".workflow-step-marker", Static)
            number = header.query_one(".workflow-step-number", Static)
            title = header.query_one(".workflow-step-title", Static)
            summary = header.query_one(".workflow-step-summary", Static)
            status = header.query_one(".workflow-step-status", Static)

            assert str(marker.content) == "[>]"
            assert str(number.content) == "1"
            assert str(title.content) == "Existing backup"
            assert str(status.content) == "Current / Warning"
            assert header.has_class("step-current")
            assert header.has_class("step-warning")
            assert summary.region.height == 1
            assert summary.render_line(0).text.rstrip().endswith("\u2026")

    asyncio.run(run())


def test_composite_step_body_keeps_keyed_parts_mounted_and_enforces_kinds() -> None:
    async def run() -> None:
        trust = OptionsBodyPresentation(
            actions=(WorkspaceAction("accept", "Use these scans", visible=False),)
        )
        body = CompositeBodyPresentation(
            parts=(
                CompositeBodyPartPresentation("source", make_source_body()),
                CompositeBodyPartPresentation("trust", trust),
            )
        )
        composite = CompositeStepBody(body, id="combined")
        app = PrimitiveHarness(composite)
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
