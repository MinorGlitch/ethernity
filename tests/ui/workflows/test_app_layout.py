from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import (
    Button,
    Label,
    RadioButton,
    Select,
    SelectionList,
    Static,
)

from ethernity.app.application import EthernityApp
from ethernity.app.screens.file_picker import FilePickerScreen
from ethernity.app.screens.paste_text import PasteTextScreen
from ethernity.app.task_catalog import TASK_TITLES, review_label
from ethernity.app.widgets.form import FormSection
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.app.widgets.workbench import WorkbenchSteps, WorkbenchSummary
from ethernity.app.widgets.workflow.controls import KeyedRadioSet
from ethernity.app.widgets.workflow.options import OptionsEditor
from ethernity.app.widgets.workflow.paths import PathSelectionEditor
from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.app.widgets.workflow.steps import WorkflowStep, WorkflowStepStack
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.app.workspaces.workspace_controls import WorkspacePathList
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.presentation.builder import build_task_presentation
from tests.support import workflows as workflow_support
from tests.support.app import run_app_test
from tests.support.pilot import (
    wait_for_condition as _wait_for_condition,
)

pytestmark = pytest.mark.usefixtures("isolated_app_settings")


def test_textual_app_numeric_workflow_switch_moves_focus_out_of_hidden_workspace() -> None:
    async def run() -> None:
        app = EthernityApp(backup_state=BackupTaskState(input_paths=[Path("secrets.txt")]))
        async with run_app_test(app, size=(100, 30)) as pilot:
            app.query_one("#workspace-backup-files", Button).focus()
            await pilot.pause()

            await pilot.press("2")

            assert app.active_task == "restore"
            source_load = app.query_one(
                "#workflow-restore-source-body-load",
                Button,
            )
            assert app.screen.focused is source_load
            assert app.screen.focused.region.width > 0

            await pilot.press("enter")

            assert isinstance(app.screen, FilePickerScreen)
            assert (
                workflow_support.static_text(app, "#file-picker-title") == "Load backup documents"
            )

    asyncio.run(run())


def test_textual_app_workspace_shows_real_flow_controls() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            workflow_support.assert_absent_controls(
                app,
                (
                    "#canvas-checklist",
                    "#canvas-next-row",
                    "#preview",
                    "#preview-panel",
                    "#canvas-input",
                    "#canvas-passphrase",
                    "#canvas-output",
                    "#canvas-footer-hints",
                ),
            )
            assert "No files selected" in workflow_support.checklist_text(app)
            assert not app.query_one("#backup-files-list", WorkspacePathList).display
            assert (
                workflow_support.static_text(app, "#backup-files-list-empty")
                == "No files selected."
            )
            assert not app.query_one("#backup-files-value").display
            assert not app.query_one("#backup-files-panel").display
            assert (
                workflow_support.button_label(app, "#workspace-backup-files") == "Choose files..."
            )
            assert workflow_support.button_label(app, "#canvas-primary") == "Continue >"
            assert not app.query_one("#canvas-primary", Button).disabled
            assert app.query_one("#canvas-primary", Button).region.height == 3
            assert app.query_one("#canvas-primary").region.width <= 32
            assert not app.query_one("#workspace-backup-clear-files", Button).display

            await pilot.click("#workspace-backup-files")
            await pilot.pause()

            assert isinstance(app.screen, FilePickerScreen)

            await pilot.press("escape")
            await pilot.press("7")

            assert not app.screen.query_one("#canvas-task-workspaces").display
            assert not app.screen.query_one("#canvas-hero").display
            assert app.screen.query_one("#canvas-settings-workspace").display
            assert app.query_one("#settings-form").region.height > 10
            assert not list(app.screen.query("#canvas-readiness"))
            assert app.query_one("#setting-control-render_style", Select).value == (
                app.settings_state.design
            )
            assert app.query_one("#setting-control-page_size", Select).value == (
                app.settings_state.paper_size
            )
            assert "config.toml" in workflow_support.static_text(app, "#setting-value-config")
            assert not app.query_one("#task-action-bar").display

            await pilot.press("3")

            assert app.active_task == "add_files"
            assert app.screen.query_one("#canvas-task-workspaces").display
            assert not app.screen.query_one("#canvas-settings-workspace").display
            assert workflow_support.button_label(app, "#workflow-add_files-source-body-load") == (
                "Load backup documents..."
            )
            assert not app.query_one(WorkbenchSummary).display
            assert app.query_one(
                "#workflow-add_files-source-body",
                SourceChooser,
            ).display
            assert workflow_support.button_label(app, "#canvas-primary") == "Continue >"

    asyncio.run(run())


def test_textual_app_workspace_buttons_keep_gaps_and_clear_primary_action() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
            for task_key in ("1", "2", "3", "4", "5", "6"):
                await pilot.press(task_key)

                action_bar = app.query_one("#task-action-bar").region
                active_workspace = app.screen.query_one(f"#{app.active_task}-workspace")
                for row in active_workspace.query(".workspace-button-row"):
                    buttons = [
                        button
                        for button in row.query(Button)
                        if button.display and button.region.width > 0
                    ]
                    for previous, current in zip(buttons, buttons[1:], strict=False):
                        assert current.region.y == previous.region.y
                        assert current.region.x >= previous.region.right + 1
                visible_workspace = active_workspace.query_one(".task-workspace").region
                for button in app.screen.query(Button):
                    if button.id is None or not button.id.startswith("workspace-"):
                        continue
                    if not button.display:
                        continue
                    if not button.region.overlaps(visible_workspace):
                        continue
                    assert not button.region.overlaps(action_bar)
                    assert button.region.width < visible_workspace.width - 4

    asyncio.run(run())


def test_textual_app_modal_action_rows_keep_visible_gaps() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(96, 32)) as pilot:
            await app.action_edit_passphrase()
            await pilot.pause()
            workflow_support.assert_modal_action_buttons_are_spaced(app)

            await pilot.press("escape")
            await app.push_screen(
                PasteTextScreen(
                    title="Paste recovery text",
                    prompt="Paste recovery text",
                )
            )
            await pilot.pause()
            workflow_support.assert_modal_action_buttons_are_spaced(app)

            await pilot.press("escape")
            await app.action_edit_primary()
            await pilot.pause()
            workflow_support.assert_modal_action_buttons_are_spaced(app)

            await pilot.press("escape")
            await pilot.press("?")
            workflow_support.assert_modal_action_buttons_are_spaced(app)

            await pilot.press("escape")
            app.backup_state.input_paths = [Path("README.md")]
            app.backup_state.output_dir = Path("backup-out")
            app.refresh_task_view()
            await pilot.press("ctrl+r")
            workflow_support.assert_modal_action_buttons_are_spaced(app)

    asyncio.run(run())


def test_textual_app_field_controls_use_available_wide_space() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(200, 48)) as pilot:
            for task_key in ("1", "2", "3", "4", "5", "6"):
                await pilot.press(task_key)

                active_workspace = app.screen.query_one(f"#{app.active_task}-workspace")
                visible_workspace = active_workspace.query_one(".task-workspace").region
                for button in active_workspace.query(".workspace-field-row Button"):
                    if not button.display or not button.region.overlaps(visible_workspace):
                        continue
                    right_gap = (
                        visible_workspace.x
                        + visible_workspace.width
                        - (button.region.x + button.region.width)
                    )
                    assert 0 <= right_gap <= 4

            await pilot.press("7")
            form = app.query_one(SettingsForm)
            for group in ("Printing", "Advanced"):
                form.show_group(group)
                await pilot.pause()
                for control in form.active_pane.query(".setting-select, .setting-input"):
                    if isinstance(control, Select):
                        assert control.region.width >= 38
                        assert control.region.right <= form.active_pane.content_region.right
                    else:
                        assert control.region.width == 12

    asyncio.run(run())


def test_textual_app_top_navigation_keeps_workspace_geometry() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            workspace = app.query_one("#workspace").region
            await pilot.press("ctrl+b")
            assert app.screen.focused is app.query_one("#nav-create", Button)
            assert not app._nav_menu_open
            await pilot.click("#nav-manage")
            await pilot.pause()
            assert app.query_one("#workspace").region == workspace
            await pilot.press("down", "enter")
            assert app.active_task == "rebuild"
            assert not app._nav_menu_open
            assert app.query_one("#canvas-task-workspaces").has_focus_within

    asyncio.run(run())


def test_textual_app_workspaces_are_grouped_into_sections() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
            expected_steps = {
                "restore": 4,
                "add_files": 4,
                "rebuild": 3,
                "replace_recovery_docs": 4,
            }
            for task_key in ("1", "2", "3", "4", "5", "6"):
                await pilot.press(task_key)

                workspace = app.screen.query_one(f"#{app.active_task}-workspace")
                scroll = workspace.query_one(".task-workspace")
                sections = list(scroll.query(FormSection))
                if app.active_task in expected_steps:
                    stack = scroll.query_one(WorkflowStepStack)
                    steps = list(stack.query(WorkflowStep))
                    assert len(steps) == expected_steps[app.active_task]
                    assert sum(step.display for step in steps) == 1
                    assert not stack.query(".workflow-step-heading")
                    assert sum(body.display for body in stack.query(".guided-step-body")) >= 1
                else:
                    assert sections
                    visible_sections = [section for section in sections if section.region.height]
                    assert visible_sections
                    expected_labels = (
                        {"Paper size", "Save to"}
                        if app.active_task == "backup"
                        else {"Save as", "Kit type", "Paper size", "Print design"}
                    )
                    labels = {str(label.content) for label in scroll.query(Label).results(Label)}
                    assert expected_labels <= labels

    asyncio.run(run())


def test_textual_app_workspace_buttons_match_presentation_actions() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
            for task_key in ("1", "2", "3", "4", "5", "6"):
                await pilot.press(task_key)

                state = app._current_state()
                validation = state.validate_task()
                presentation = build_task_presentation(
                    task_key=app.active_task,
                    title=TASK_TITLES[app.active_task],
                    state=state,
                    validation=validation,
                    preview=state.preview(),
                    primary_label=review_label(app.active_task),
                    diagnostics_available=False,
                )
                active_workspace = app.screen.query_one(f"#{app.active_task}-workspace")
                rendered_button_ids = {
                    button.id
                    for button in active_workspace.query(Button)
                    if button.id is not None and button.id.startswith("workspace-")
                }
                presented_action_ids = {
                    action.key
                    for group in presentation.workspace_groups
                    for action in group.actions
                }

                if app.active_task not in app.workflow_ui_states:
                    assert rendered_button_ids == presented_action_ids

    asyncio.run(run())


def test_textual_app_workspace_controls_have_event_paths() -> None:
    handled_select_ids = {
        "workspace-kit-variant-select",
        "workspace-backup-passphrase-words",
        "workspace-backup-signing-key-mode",
        "workspace-backup-paper-size",
        "workspace-restore-auth-policy",
        "workspace-restore-signature-source",
        "workspace-add-files-signature-source",
        "workspace-add-files-update-mode",
        "workspace-rebuild-signature-source",
        "workspace-replace-passphrase-select",
        "workspace-replace-signing-key-select",
    }
    handled_radio_ids = {"workspace-backup-recovery-method"}

    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
            for task_key in ("1", "2", "3", "4", "5", "6"):
                await pilot.press(task_key)

                active_workspace = app.screen.query_one(f"#{app.active_task}-workspace")
                rendered_select_ids = {
                    select.id
                    for select in active_workspace.query(Select)
                    if select.id is not None and select.id.startswith("workspace-")
                }
                rendered_radio_ids = {
                    radio.id
                    for radio in active_workspace.query(KeyedRadioSet)
                    if radio.id is not None and radio.id.startswith("workspace-")
                }

                unhandled_selects = {
                    select_id
                    for select_id in rendered_select_ids
                    if select_id not in handled_select_ids
                    and not select_id.endswith(("-paper", "-design"))
                }
                assert unhandled_selects == set()
                assert rendered_radio_ids <= handled_radio_ids

    asyncio.run(run())


def test_textual_app_radios_show_effective_defaults_without_fake_selections() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
            backup = app.query_one(
                "#workspace-backup-recovery-method",
                KeyedRadioSet,
            )
            assert backup.selected_key == "recommended_shards"

            for task_key, selector in (
                ("3", "#workflow-add_files-unlock-body-unlock"),
                ("4", "#workflow-rebuild-unlock-body-unlock"),
                ("5", "#workflow-replace_recovery_docs-unlock-body"),
            ):
                await pilot.press(task_key)
                assert app.query_one(selector, UnlockEditor).selected_method is None

            await pilot.press("5")
            recovery_mode = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-mode",
                OptionsEditor,
            )
            selected = [
                str(button.label)
                for button in recovery_mode.query(RadioButton)
                if button.value and str(button.label)
            ]
            assert selected == ["3 sheets; any 2 can restore (recommended)"]
            assert app.query_one("#workspace-replace-signing-key-select", Select).value == "off"

    asyncio.run(run())


def test_textual_app_empty_path_lists_use_empty_states_instead_of_placeholder_rows() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
            await pilot.press("3")
            editor = app.query_one("#workflow-add_files-files-body", PathSelectionEditor)
            path_list = editor.query_one(SelectionList)
            empty = editor.query_one(".guided-empty", Static)

            assert not path_list.display
            assert empty.display
            assert not path_list.options
            assert "No files or folders selected" in str(empty.content)

    asyncio.run(run())


def test_textual_app_common_terminal_sizes_keep_workspaces_readable() -> None:
    async def run() -> None:
        for size in ((160, 48), (140, 36), (120, 36), (96, 30), (80, 30)):
            app = EthernityApp()
            async with run_app_test(app, size=size) as pilot:
                workspace = app.query_one("#workspace").region

                assert workspace.width == min(size[0], 140)
                assert workspace.x == (size[0] - workspace.width) // 2
                assert workspace.width >= (24 if size[0] <= 80 else 36)
                assert workspace.x + workspace.width <= size[0]
                assert not list(app.screen.query("#preview"))

                for task_key in ("1", "2", "3", "4", "5", "6"):
                    await pilot.press(task_key)

                    action_bar = app.query_one("#task-action-bar").region
                    active_workspace = app.screen.query_one(f"#{app.active_task}-workspace")
                    visible_workspace = active_workspace.query_one(".task-workspace").region
                    buttons = [
                        *list(active_workspace.query(Button)),
                        app.query_one("#canvas-primary", Button),
                    ]
                    for button in buttons:
                        if not button.display:
                            continue
                        if button.id is None:
                            continue
                        if button.id != "canvas-primary" and not button.region.overlaps(
                            visible_workspace
                        ):
                            continue
                        if button.id == "canvas-primary":
                            assert button.region.x + button.region.width <= workspace.x + (
                                workspace.width
                            )
                        visible_button = button.region.intersection(visible_workspace)
                        assert (
                            not visible_button.overlaps(action_bar) or button.id == "canvas-primary"
                        )
                        assert len(str(button.label)) <= button.region.width

    asyncio.run(run())


def test_textual_app_canvas_rows_edit_secondary_choices() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            assert "Store recovery sheets separately" in workflow_support.static_text(
                app,
                "#backup-recovery-help",
            )

            recovery = app.query_one(
                "#workspace-backup-recovery-method",
                KeyedRadioSet,
            )
            await pilot.click(app.query_one(WorkbenchSteps).button_for("recovery"))
            recovery.focus()
            await pilot.press("right", "space")

            assert app.backup_state.recovery_method == "single_phrase"
            assert "Warning: One recovery phrase" in workflow_support.static_text(
                app,
                "#backup-recovery-status",
            )
            assert "Keep the recovery phrase separate" in workflow_support.static_text(
                app,
                "#backup-recovery-help",
            )
            assert "One recovery phrase is a single secret" in workflow_support.preview_text(app)

            app._apply_backup_recovery("3/5")
            await pilot.pause()

            assert app.backup_state.recovery_method == "custom_shards"
            assert "Warning: 5 recovery sheets; any 3 required" in workflow_support.static_text(
                app,
                "#backup-recovery-status",
            )
            assert "Store recovery sheets separately" in workflow_support.static_text(
                app,
                "#backup-recovery-help",
            )
            assert (
                "A custom quorum changes how many sheets you need"
                in workflow_support.preview_text(app)
            )

            await pilot.press("6")
            app.query_one("#workspace-kit-paper", Select).value = "LETTER"
            await _wait_for_condition(
                pilot,
                lambda: app.kit_state.paper_size == "LETTER",
                "kit paper size update",
            )
            app.query_one("#workspace-kit-design", Select).value = "forge"
            await _wait_for_condition(
                pilot,
                lambda: app.kit_state.design == "forge",
                "kit design update",
            )

            assert app.kit_state.paper_size == "LETTER"
            assert app.kit_state.design == "forge"

    asyncio.run(run())
