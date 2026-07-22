"""Screenshot gates for the real Ethernity application workflows."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from textual.command import CommandPalette
from textual.containers import Vertical, VerticalScroll
from textual.geometry import Region
from textual.pilot import Pilot
from textual.scroll_view import ScrollView
from textual.widget import Widget
from textual.widgets import Button, Footer, RadioSet, Static, TabbedContent, TabPane

from ethernity.app.application import ETHERNITY_DARK_THEME, ETHERNITY_LIGHT_THEME
from ethernity.app.execution import build_review_decision_facts
from ethernity.app.screens.help import HelpScreen
from ethernity.app.screens.review_task import ReviewTaskScreen
from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.app.task_view import _REVIEW_TITLES
from ethernity.app.workflow_registry import workflow_definition
from ethernity.app.workspaces.common import BaseWorkspace
from tests.visual.production_states import (
    PRODUCTION_SNAPSHOT_CASES,
    RESULT_SNAPSHOT_CASES,
    REVIEW_SNAPSHOT_CASES,
    VISUAL_SECRET,
    ProductionSnapshotCase,
    ProductionVisualApp,
    ResultSnapshotCase,
    ReviewSnapshotCase,
    SettingsVisualApp,
    production_case,
)
from tests.visual.snapshot_support import assert_svg_snapshot, capture_svg

SNAPSHOT_DIR = Path(__file__).with_name("snapshots")
TARGET_SIZES = ((160, 48), (120, 32), (80, 24))
REVIEW_SIZE = (120, 32)
LIGHT_THEME_SIZE = (120, 32)
LIGHT_WORKFLOW_CASE = production_case("restore-ready")
READY_CASE_BY_TASK = {
    "backup": "backup-ready",
    "restore": "restore-ready",
    "add_files": "add-files-ready",
    "rebuild": "rebuild-warning",
    "replace_recovery_docs": "replacement-warning",
    "kit": "kit-default",
}
HELP_SIZE = (120, 32)
COMMAND_PALETTE_SIZE = (120, 32)
SCROLLED_SETTINGS_SIZE = (80, 24)
HELP_SNAPSHOT_CASES = tuple(
    (task, case_key, HELP_SIZE) for task, case_key in READY_CASE_BY_TASK.items()
) + (("restore", READY_CASE_BY_TASK["restore"], (80, 24)),)


def test_production_snapshot_catalog_covers_requested_workflows_and_states() -> None:
    keys = tuple(case.key for case in PRODUCTION_SNAPSHOT_CASES)
    assert len(keys) == len(set(keys))
    assert {case.task for case in PRODUCTION_SNAPSHOT_CASES} == {
        "backup",
        "restore",
        "add_files",
        "rebuild",
        "replace_recovery_docs",
        "kit",
    }
    counts = {
        task: sum(case.task == task for case in PRODUCTION_SNAPSHOT_CASES)
        for task in {case.task for case in PRODUCTION_SNAPSHOT_CASES}
    }
    assert all(counts[task] >= 2 for task in counts)

    dense_replacement = next(
        case for case in PRODUCTION_SNAPSHOT_CASES if case.key == "replacement-dense"
    )
    assert dense_replacement.expected_ready
    assert dense_replacement.advanced_focus == "#workspace-replace-signing-key-select"

    review_tasks = {
        production_case(review_case.workflow_case_key).task for review_case in REVIEW_SNAPSHOT_CASES
    }
    assert review_tasks == set(READY_CASE_BY_TASK)
    assert all(
        production_case(review_case.workflow_case_key).expected_ready
        for review_case in REVIEW_SNAPSHOT_CASES
    )
    assert all(review_case.expected_fact_labels for review_case in REVIEW_SNAPSHOT_CASES)

    result_sizes = {result_case.terminal_size for result_case in RESULT_SNAPSHOT_CASES}
    assert (160, 48) in result_sizes
    assert (80, 24) in result_sizes
    assert any(result_case.result.ok for result_case in RESULT_SNAPSHOT_CASES)
    assert any(not result_case.result.ok for result_case in RESULT_SNAPSHOT_CASES)
    assert any(
        not result_case.result.ok and result_case.result.output_paths
        for result_case in RESULT_SNAPSHOT_CASES
    )
    assert any(result_case.task != "restore" for result_case in RESULT_SNAPSHOT_CASES)
    action_ids = {
        action_id
        for result_case in RESULT_SNAPSHOT_CASES
        for action_id in result_case.expected_action_ids
    }
    assert {"result-copy-paths", "result-open-folder"} <= action_ids

    assert {task for task, _case_key, _size in HELP_SNAPSHOT_CASES} == set(READY_CASE_BY_TASK)
    assert any(size == (80, 24) for _task, _case_key, size in HELP_SNAPSHOT_CASES)

    expected_names = _expected_snapshot_names()
    assert len(expected_names) == len(set(expected_names))


@pytest.mark.parametrize(
    "case",
    PRODUCTION_SNAPSHOT_CASES,
    ids=lambda case: case.key,
)
@pytest.mark.parametrize(
    "terminal_size",
    TARGET_SIZES,
    ids=lambda size: f"{size[0]}x{size[1]}",
)
def test_production_workflow_snapshot(
    case: ProductionSnapshotCase,
    terminal_size: tuple[int, int],
    update_tui_snapshots: bool,
) -> None:
    width, height = terminal_size
    svg = capture_svg(
        lambda: ProductionVisualApp(case),
        terminal_size=terminal_size,
        title=f"Ethernity - {case.key} - {width}x{height}",
        run_before=lambda app, pilot: _prepare_workspace_capture(
            cast(ProductionVisualApp, app),
            pilot,
            terminal_size,
            expected_theme=ETHERNITY_DARK_THEME.name,
        ),
    )

    assert VISUAL_SECRET not in svg
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"app-{case.key}-{width}x{height}.svg",
        update=update_tui_snapshots,
    )


@pytest.mark.parametrize(
    "terminal_size",
    TARGET_SIZES,
    ids=lambda size: f"{size[0]}x{size[1]}",
)
def test_settings_snapshot(
    terminal_size: tuple[int, int],
    update_tui_snapshots: bool,
) -> None:
    width, height = terminal_size
    svg = capture_svg(
        SettingsVisualApp,
        terminal_size=terminal_size,
        title=f"Ethernity - settings - {width}x{height}",
        run_before=lambda app, pilot: _prepare_settings_capture(
            cast(SettingsVisualApp, app),
            pilot,
            terminal_size,
            expected_theme=ETHERNITY_DARK_THEME.name,
        ),
    )

    assert VISUAL_SECRET not in svg
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"app-settings-{width}x{height}.svg",
        update=update_tui_snapshots,
    )


def test_light_theme_workflow_snapshot(update_tui_snapshots: bool) -> None:
    width, height = LIGHT_THEME_SIZE
    svg = capture_svg(
        lambda: ProductionVisualApp(
            LIGHT_WORKFLOW_CASE,
            theme=ETHERNITY_LIGHT_THEME.name,
        ),
        terminal_size=LIGHT_THEME_SIZE,
        title=f"Ethernity - light-{LIGHT_WORKFLOW_CASE.key} - {width}x{height}",
        run_before=lambda app, pilot: _prepare_workspace_capture(
            cast(ProductionVisualApp, app),
            pilot,
            LIGHT_THEME_SIZE,
            expected_theme=ETHERNITY_LIGHT_THEME.name,
        ),
    )

    assert VISUAL_SECRET not in svg
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"app-light-{LIGHT_WORKFLOW_CASE.key}-{width}x{height}.svg",
        update=update_tui_snapshots,
    )


def test_light_theme_settings_snapshot(update_tui_snapshots: bool) -> None:
    width, height = LIGHT_THEME_SIZE
    svg = capture_svg(
        lambda: SettingsVisualApp(theme=ETHERNITY_LIGHT_THEME.name),
        terminal_size=LIGHT_THEME_SIZE,
        title=f"Ethernity - light-settings - {width}x{height}",
        run_before=lambda app, pilot: _prepare_settings_capture(
            cast(SettingsVisualApp, app),
            pilot,
            LIGHT_THEME_SIZE,
            expected_theme=ETHERNITY_LIGHT_THEME.name,
        ),
    )

    assert VISUAL_SECRET not in svg
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"app-light-settings-{width}x{height}.svg",
        update=update_tui_snapshots,
    )


@pytest.mark.parametrize(
    ("task", "workflow_case_key", "terminal_size"),
    HELP_SNAPSHOT_CASES,
    ids=lambda value: str(value).replace("_", "-"),
)
def test_workflow_help_snapshot(
    task: str,
    workflow_case_key: str,
    terminal_size: tuple[int, int],
    update_tui_snapshots: bool,
) -> None:
    width, height = terminal_size
    svg = capture_svg(
        lambda: ProductionVisualApp(production_case(workflow_case_key)),
        terminal_size=terminal_size,
        title=f"Ethernity - help-{task} - {width}x{height}",
        run_before=lambda app, pilot: _open_help_overlay(
            cast(ProductionVisualApp, app),
            pilot,
            terminal_size,
        ),
    )

    assert VISUAL_SECRET not in svg
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"app-help-{task.replace('_', '-')}-{width}x{height}.svg",
        update=update_tui_snapshots,
    )


def test_settings_help_snapshot(update_tui_snapshots: bool) -> None:
    width, height = HELP_SIZE
    svg = capture_svg(
        SettingsVisualApp,
        terminal_size=HELP_SIZE,
        title=f"Ethernity - help-settings - {width}x{height}",
        run_before=lambda app, pilot: _open_help_overlay(
            cast(SettingsVisualApp, app),
            pilot,
            HELP_SIZE,
        ),
    )

    assert VISUAL_SECRET not in svg
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"app-help-settings-{width}x{height}.svg",
        update=update_tui_snapshots,
    )


def test_advanced_settings_snapshot(update_tui_snapshots: bool) -> None:
    width, height = HELP_SIZE
    svg = capture_svg(
        SettingsVisualApp,
        terminal_size=HELP_SIZE,
        title=f"Ethernity - settings-advanced - {width}x{height}",
        run_before=lambda app, pilot: _prepare_advanced_settings_capture(
            cast(SettingsVisualApp, app),
            pilot,
        ),
    )

    assert VISUAL_SECRET not in svg
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"app-settings-advanced-{width}x{height}.svg",
        update=update_tui_snapshots,
    )


def test_scrolled_advanced_settings_snapshot(update_tui_snapshots: bool) -> None:
    width, height = SCROLLED_SETTINGS_SIZE
    svg = capture_svg(
        SettingsVisualApp,
        terminal_size=SCROLLED_SETTINGS_SIZE,
        title=f"Ethernity - settings-advanced-scrolled - {width}x{height}",
        run_before=lambda app, pilot: _prepare_scrolled_advanced_settings_capture(
            cast(SettingsVisualApp, app),
            pilot,
        ),
    )

    assert VISUAL_SECRET not in svg
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"app-settings-advanced-scrolled-{width}x{height}.svg",
        update=update_tui_snapshots,
    )


def test_command_palette_snapshot(update_tui_snapshots: bool) -> None:
    width, height = COMMAND_PALETTE_SIZE
    svg = capture_svg(
        lambda: ProductionVisualApp(LIGHT_WORKFLOW_CASE),
        terminal_size=COMMAND_PALETTE_SIZE,
        title=f"Ethernity - command-palette-restore - {width}x{height}",
        run_before=lambda app, pilot: _open_command_palette(
            cast(ProductionVisualApp, app),
            pilot,
        ),
    )

    assert VISUAL_SECRET not in svg
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"app-command-palette-restore-{width}x{height}.svg",
        update=update_tui_snapshots,
    )


@pytest.mark.parametrize(
    "review_case",
    REVIEW_SNAPSHOT_CASES,
    ids=lambda case: case.key,
)
def test_final_review_snapshot(
    review_case: ReviewSnapshotCase,
    update_tui_snapshots: bool,
) -> None:
    width, height = REVIEW_SIZE
    workflow_case = production_case(review_case.workflow_case_key)
    svg = capture_svg(
        lambda: ProductionVisualApp(workflow_case),
        terminal_size=REVIEW_SIZE,
        title=f"Ethernity - {review_case.key} - {width}x{height}",
        run_before=lambda app, pilot: _open_review_overlay(
            cast(ProductionVisualApp, app),
            pilot,
            review_case,
        ),
    )

    assert VISUAL_SECRET not in svg
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"app-{review_case.key}-{width}x{height}.svg",
        update=update_tui_snapshots,
    )


@pytest.mark.parametrize(
    "result_case",
    RESULT_SNAPSHOT_CASES,
    ids=lambda case: case.key,
)
def test_task_result_snapshot(
    result_case: ResultSnapshotCase,
    update_tui_snapshots: bool,
) -> None:
    width, height = result_case.terminal_size
    workflow_case = production_case(READY_CASE_BY_TASK[result_case.task])
    svg = capture_svg(
        lambda: ProductionVisualApp(workflow_case),
        terminal_size=result_case.terminal_size,
        title=f"Ethernity - {result_case.key} - {width}x{height}",
        run_before=lambda app, pilot: _open_result_overlay(
            cast(ProductionVisualApp, app),
            pilot,
            result_case,
        ),
    )

    assert VISUAL_SECRET not in svg
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"app-{result_case.key}-{width}x{height}.svg",
        update=update_tui_snapshots,
    )


async def _prepare_workspace_capture(
    app: ProductionVisualApp,
    pilot: Pilot[object],
    terminal_size: tuple[int, int],
    *,
    expected_theme: str,
) -> None:
    case = app.visual_case
    if case.active_step is not None:
        ui_state = app.workflow_ui_states[case.task]
        ui_state.reset_interaction()
        app.refresh_task_view()
        await pilot.pause()
    if case.advanced_focus is not None:
        definition = workflow_definition(case.task)
        assert definition.workspace_id is not None
        workspace = app.query_one(f"#{definition.workspace_id}", BaseWorkspace)
        assert workspace.reveal_advanced_focus_target(case.advanced_focus)
        workspace.query_one(case.advanced_focus).focus()
        await pilot.pause()
        app.screen.refresh(layout=True)
        await pilot.pause()
    _assert_production_geometry(app, terminal_size, expected_theme=expected_theme)


async def _prepare_settings_capture(
    app: SettingsVisualApp,
    _pilot: Pilot[object],
    terminal_size: tuple[int, int],
    *,
    expected_theme: str,
) -> None:
    _assert_settings_geometry(app, terminal_size, expected_theme=expected_theme)


async def _open_review_overlay(
    app: ProductionVisualApp,
    pilot: Pilot[object],
    review_case: ReviewSnapshotCase,
) -> None:
    state = app.visual_state
    definition = workflow_definition(app.visual_case.task)
    validation = state.validate_task()
    plan = state.execution_plan()
    facts = build_review_decision_facts(app.visual_case.task, state, plan)
    assert validation.ready
    assert tuple(fact.label for fact in facts) == review_case.expected_fact_labels
    screen = ReviewTaskScreen(
        title=_REVIEW_TITLES[app.visual_case.task],
        validation=validation,
        preview=state.preview(),
        plan=plan,
        execute_label=definition.execute_label,
        decision_facts=facts,
    )

    await app.push_screen(screen)
    await pilot.pause()
    app.screen.refresh(layout=True)
    await pilot.pause()
    _assert_review_geometry(app, review_case, REVIEW_SIZE)


async def _open_result_overlay(
    app: ProductionVisualApp,
    pilot: Pilot[object],
    result_case: ResultSnapshotCase,
) -> None:
    reviewed_plan = None
    if result_case.reviewed_workflow_case_key is not None:
        assert app.visual_case.key == result_case.reviewed_workflow_case_key
        reviewed_plan = app.visual_state.execution_plan()

    screen = TaskResultScreen(
        task=result_case.task,
        title=result_case.title,
        result=result_case.result,
        error=result_case.error,
        error_detail=result_case.error_detail,
        recoverable_errors=result_case.recoverable_errors,
        reviewed_plan=reviewed_plan,
        return_section=result_case.return_section,
    )
    await app.push_screen(screen)
    await pilot.pause()
    app.screen.refresh(layout=True)
    await pilot.pause()
    _assert_result_geometry(app, result_case)


async def _open_help_overlay(
    app: ProductionVisualApp | SettingsVisualApp,
    pilot: Pilot[object],
    terminal_size: tuple[int, int],
) -> None:
    await app.action_help()
    await pilot.pause()
    app.screen.refresh(layout=True)
    await pilot.pause()

    screen = app.screen
    assert isinstance(screen, HelpScreen)
    modal = screen.query_one("#help-modal")
    title = screen.query_one("#help-title", Static)
    intro = screen.query_one("#help-intro", Static)
    body = screen.query_one("#help-body")
    actions = screen.query_one("#help-actions")
    close = screen.query_one("#help-close", Button)
    viewport = Region(0, 0, *terminal_size)

    assert str(title.content) == workflow_definition(app.active_task).title
    assert str(intro.content).strip()
    for widget in (modal, title, intro, body, actions, close):
        assert _inside(viewport if widget is modal else modal.region, widget.region)
    assert body.region.bottom <= actions.region.y
    assert str(close.label) == "Close"
    for scroll_view in screen.query(ScrollView):
        if scroll_view.region.width > 0 and scroll_view.region.height > 0:
            assert scroll_view.max_scroll_x == 0, f"help-{app.active_task}: {scroll_view.id}"


async def _prepare_advanced_settings_capture(
    app: SettingsVisualApp,
    pilot: Pilot[object],
) -> None:
    tabs = app.query_one("#settings-tabs", TabbedContent)
    tabs.active = "settings-pane-advanced"
    await pilot.pause()
    app.screen.refresh(layout=True)
    await pilot.pause()

    assert tabs.active == "settings-pane-advanced"
    assert not list(app.query("#settings-advanced-panel"))
    assert app.query_one("#setting-row-qr_error").region.height > 0
    assert app.query_one("#setting-row-qr_chunk_size").region.height > 0
    assert app.query_one("#settings-pane-advanced", TabPane).max_scroll_x == 0


async def _prepare_scrolled_advanced_settings_capture(
    app: SettingsVisualApp,
    pilot: Pilot[object],
) -> None:
    tabs = app.query_one("#settings-tabs", TabbedContent)
    tabs.active = "settings-pane-advanced"
    await pilot.pause()

    tab_bar = app.query_one("#settings-tabs Tabs")
    pane = app.query_one("#settings-pane-advanced", TabPane)
    save_row = app.query_one("#settings-save-row")
    fixed_regions = (tab_bar.region, save_row.region)
    assert pane.max_scroll_y > 0
    quiet_row = app.query_one("#setting-row-ui_quiet")
    scroll_target = quiet_row.region.y - pane.region.y

    pane.scroll_to(y=scroll_target, animate=False)
    await pilot.pause()
    app.screen.refresh(layout=True)
    await pilot.pause()

    assert pane.scroll_offset.y == scroll_target
    assert (tab_bar.region, save_row.region) == fixed_regions
    assert app.query_one("#setting-row-qr_error").region.y < pane.region.y
    assert quiet_row.region.y == pane.region.y


async def _open_command_palette(
    app: ProductionVisualApp,
    pilot: Pilot[object],
) -> None:
    await pilot.press("ctrl+p")
    await pilot.pause()
    app.screen.refresh(layout=True)
    await pilot.pause()

    screen = app.screen
    assert isinstance(screen, CommandPalette)
    viewport = Region(0, 0, *COMMAND_PALETTE_SIZE)
    command_input = screen.query_one("#--input")
    results = screen.query_one("#--results")
    for widget in (command_input, results):
        assert _inside(viewport, widget.region)


def _assert_production_geometry(
    app: ProductionVisualApp,
    terminal_size: tuple[int, int],
    *,
    expected_theme: str,
) -> None:
    case = app.visual_case
    assert app.active_task == case.task
    assert app.current_theme.name == expected_theme
    assert app.visual_state.validate_task().ready is case.expected_ready

    width, height = terminal_size
    body = app.query_one("#canvas-task-workspaces")
    action_bar = app.query_one("#task-action-bar")
    footer = app.query_one(Footer)
    primary = action_bar.query_one("#canvas-primary", Button)

    assert _inside(Region(0, 0, width, height), body.region)
    assert _inside(Region(0, 0, width, height), action_bar.region)
    assert body.region.y + body.region.height <= action_bar.region.y
    assert action_bar.region.y + action_bar.region.height <= footer.region.y
    assert _inside(action_bar.region, primary.region)
    assert len(str(primary.label)) <= primary.region.width

    definition = workflow_definition(case.task)
    assert definition.workspace_id is not None
    workspace = app.query_one(f"#{definition.workspace_id}")
    visible_controls = 0
    for widget in workspace.query(Widget):
        region = widget.region
        if not widget.can_focus or region.width <= 0 or region.height <= 0:
            continue
        if not _overlaps(region, body.region):
            continue
        visible_controls += 1
        assert _inside(body.region, region), f"{case.key}: {widget.id or type(widget).__name__}"
        if isinstance(widget, Button):
            rendered = "\n".join(
                widget.render_line(line).text for line in range(widget.region.height)
            )
            assert str(widget.label) in rendered, f"{case.key}: clipped label on {widget.id}"

    assert visible_controls > 0
    for scroll_view in workspace.query(ScrollView):
        if scroll_view.region.width > 0 and scroll_view.region.height > 0:
            assert scroll_view.max_scroll_x == 0, f"{case.key}: {scroll_view.id}"

    if case.key == "backup-empty":
        workspace.query_one("#workspace-backup-recovery-method", RadioSet)
        assert not workspace.query_one("#workspace-backup-clear-files", Button).display
        assert not workspace.query_one("#backup-files-status").display
        assert not workspace.query_one("#backup-recovery-status").display
        assert not workspace.query_one("#backup-destination-status").display
        assert primary.disabled
        assert str(primary.label) == "Review backup"

    if case.key == "kit-warning" and terminal_size == (80, 24):
        scroll = workspace.query_one(".task-workspace", VerticalScroll)
        for selector in (
            "#kit-output-value",
            "#workspace-kit-output",
            "#kit-qr-warning",
            "#kit-advanced-panel CollapsibleTitle",
        ):
            widget = workspace.query_one(selector)
            assert _inside(scroll.content_region, widget.region), (
                f"kit-warning first viewport: {selector}"
            )


def _assert_settings_geometry(
    app: SettingsVisualApp,
    terminal_size: tuple[int, int],
    *,
    expected_theme: str,
) -> None:
    width, height = terminal_size
    viewport = Region(0, 0, width, height)
    workspace = app.query_one("#canvas-settings-workspace")
    settings_form = app.query_one("#settings-form", Vertical)
    settings_tabs = app.query_one("#settings-tabs", TabbedContent)
    active_pane = app.query_one(f"#{settings_tabs.active}", TabPane)
    tab_bar = settings_tabs.query_one("Tabs")
    save_row = app.query_one("#settings-save-row")
    footer = app.query_one(Footer)

    assert app.active_task == "settings"
    assert app.current_theme.name == expected_theme
    assert _inside(viewport, workspace.region)
    assert _inside(workspace.region, settings_form.region)
    assert _inside(settings_form.region, tab_bar.region)
    assert _inside(settings_form.region, active_pane.region)
    assert _inside(workspace.region, save_row.region)
    assert tab_bar.region.bottom <= active_pane.region.y
    assert active_pane.region.bottom <= save_row.region.y
    assert workspace.region.bottom <= footer.region.y
    assert active_pane.max_scroll_x == 0
    assert not app.query_one("#task-action-bar").display

    for selector in (
        "#settings-tabs",
        "#setting-row-render_style",
        "#setting-row-page_size",
    ):
        widget = app.query_one(selector)
        assert _inside(settings_form.region, widget.region), f"settings first viewport: {selector}"

    for scroll_view in workspace.query(ScrollView):
        if scroll_view.region.width > 0 and scroll_view.region.height > 0:
            assert scroll_view.max_scroll_x == 0, f"settings: {scroll_view.id}"


def _assert_review_geometry(
    app: ProductionVisualApp,
    review_case: ReviewSnapshotCase,
    terminal_size: tuple[int, int],
) -> None:
    body, actions = _assert_modal_geometry(app, "review", terminal_size)
    screen = app.screen
    labels = list(screen.query(".review-fact-label").results(Static))
    values = list(screen.query(".review-fact-value").results(Static))

    assert tuple(str(label.content) for label in labels) == review_case.expected_fact_labels
    assert len(values) == len(labels)
    assert set(review_case.expected_fact_values) <= {str(value.content) for value in values}
    for widget in (*labels, *values):
        assert _inside(body.region, widget.region), (
            f"{review_case.key}: review decision outside first viewport: {widget.content}"
        )

    for button_id in ("review-close", "review-execute"):
        assert _inside(actions.region, screen.query_one(f"#{button_id}", Button).region)


def _assert_result_geometry(
    app: ProductionVisualApp,
    result_case: ResultSnapshotCase,
) -> None:
    body, actions = _assert_modal_geometry(app, "result", result_case.terminal_size)
    screen = app.screen

    for widget_id in result_case.expected_first_view_ids:
        widget = screen.query_one(f"#{widget_id}")
        assert _inside(body.region, widget.region), (
            f"{result_case.key}: {widget_id} must be visible without scrolling"
        )

    for button_id in result_case.expected_action_ids:
        button = screen.query_one(f"#{button_id}", Button)
        owner = actions if button_id in {"result-close", "result-return"} else body
        assert _inside(owner.region, button.region), f"{result_case.key}: {button_id}"

    if result_case.result.ok:
        assert screen.query_one("#result-outcome")
    else:
        assert screen.query_one("#result-remediation")
        if result_case.reviewed_workflow_case_key is not None:
            assert _inside(
                body.region,
                screen.query_one("#result-reviewed-destination").region,
            )
        if result_case.result.output_paths:
            assert str(screen.query_one("#result-output-title", Static).content) == (
                "Partial files may remain"
            )

    for scroll_view in screen.query(ScrollView):
        if scroll_view.region.width > 0 and scroll_view.region.height > 0:
            assert scroll_view.max_scroll_x == 0, f"{result_case.key}: {scroll_view.id}"


def _assert_modal_geometry(
    app: ProductionVisualApp,
    prefix: str,
    terminal_size: tuple[int, int],
) -> tuple[VerticalScroll, Widget]:
    width, height = terminal_size
    screen = app.screen
    modal = screen.query_one(f"#{prefix}-modal")
    body = screen.query_one(f"#{prefix}-body", VerticalScroll)
    actions = screen.query_one(f"#{prefix}-actions")

    viewport = Region(0, 0, width, height)
    assert _inside(viewport, modal.region)
    assert _inside(modal.region, body.region)
    assert _inside(modal.region, actions.region)
    assert body.region.bottom <= actions.region.y
    assert body.max_scroll_x == 0

    action_buttons = list(actions.query(Button))
    assert action_buttons
    for button in action_buttons:
        assert _inside(actions.region, button.region)
        assert len(str(button.label)) <= button.region.width
    return body, actions


def _expected_snapshot_names() -> tuple[str, ...]:
    workflow_names = tuple(
        f"app-{case.key}-{width}x{height}.svg"
        for case in PRODUCTION_SNAPSHOT_CASES
        for width, height in TARGET_SIZES
    )
    settings_names = tuple(f"app-settings-{width}x{height}.svg" for width, height in TARGET_SIZES)
    light_names = (
        f"app-light-{LIGHT_WORKFLOW_CASE.key}-120x32.svg",
        "app-light-settings-120x32.svg",
    )
    review_names = tuple(f"app-{case.key}-120x32.svg" for case in REVIEW_SNAPSHOT_CASES)
    result_names = tuple(
        f"app-{case.key}-{case.terminal_size[0]}x{case.terminal_size[1]}.svg"
        for case in RESULT_SNAPSHOT_CASES
    )
    help_names = tuple(
        f"app-help-{task.replace('_', '-')}-{width}x{height}.svg"
        for task, _case_key, (width, height) in HELP_SNAPSHOT_CASES
    ) + ("app-help-settings-120x32.svg",)
    return (
        *workflow_names,
        *settings_names,
        *light_names,
        *review_names,
        *result_names,
        *help_names,
        "app-settings-advanced-120x32.svg",
        "app-settings-advanced-scrolled-80x24.svg",
        "app-command-palette-restore-120x32.svg",
    )


def _inside(outer: Region, inner: Region) -> bool:
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and inner.x + inner.width <= outer.x + outer.width
        and inner.y + inner.height <= outer.y + outer.height
    )


def _overlaps(first: Region, second: Region) -> bool:
    return (
        first.x < second.x + second.width
        and second.x < first.x + first.width
        and first.y < second.y + second.height
        and second.y < first.y + first.height
    )
