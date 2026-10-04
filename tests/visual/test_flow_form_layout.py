"""Reachability and row geometry for every step, including steps outside snapshot fixtures."""

from __future__ import annotations

import asyncio

import pytest
from textual.widgets import Button, Select

from ethernity.app.widgets.form import FormRow, FormSection
from ethernity.app.widgets.workbench import workbench_steps
from tests.visual.production_states import ProductionVisualApp, production_case


@pytest.mark.parametrize("size", [(160, 48), (120, 32), (80, 24)])
@pytest.mark.parametrize(
    "case",
    [
        "backup-ready",
        "restore-ready",
        "add-files-ready",
        "rebuild-warning",
        "replacement-dense",
        "kit-warning",
    ],
)
def test_each_flow_step_has_bounded_rows_and_reachable_controls(case, size) -> None:
    async def run() -> None:
        app = ProductionVisualApp(production_case(case))
        app.animation_level = "none"
        async with app.run_test(size=size, tooltips=False) as pilot:
            await pilot.pause()
            canvas = app.query_one("#task-canvas")
            steps = workbench_steps(canvas._presentation)
            for step in steps:
                if step.key == "review":
                    continue
                await app._select_workbench_step(step.key)
                await pilot.pause()
                rows = [
                    row
                    for row in app.query(FormRow)
                    if row.display and all(parent.display for parent in row.ancestors)
                ]
                sections = [
                    section
                    for section in app.query(FormSection)
                    if section.display and all(parent.display for parent in section.ancestors)
                ]
                assert (
                    sections
                    and sum(section.has_class("first-section") for section in sections) == 1
                )
                viewport = app.query_one("#canvas-task-workspaces").region
                assert viewport.contains_region(sections[0].query_one(".form-section-title").region)
                for row in rows:
                    for control in row.query("Button, Select, Input"):
                        if not control.display or control.disabled:
                            continue
                        control.focus(scroll_visible=False)
                        control.scroll_visible(animate=False, immediate=True)
                        await pilot.pause(0.01)
                        assert viewport.contains_region(control.region), (
                            case,
                            size,
                            step.key,
                            control.id,
                        )
                        if isinstance(control, Button):
                            text = control.render_line(control.content_size.height // 2).text
                            assert str(control.label) in text
                    for value in row.query(".form-value, .form-path-value"):
                        controls = row.query_one(".form-controls")
                        assert controls.region.contains_region(value.region)
                        button = row.query_one(Button)
                        assert button.region.x == value.region.right + 1
                    for select in row.query(Select):
                        assert select.region.width <= 48

    asyncio.run(run())
