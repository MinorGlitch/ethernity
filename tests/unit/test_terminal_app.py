from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import cast

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import (
    Button,
    Collapsible,
    DirectoryTree,
    Header,
    Input,
    Label,
    MarkdownViewer,
    MaskedInput,
    OptionList,
    ProgressBar,
    RadioButton,
    RadioSet,
    RichLog,
    Select,
    SelectionList,
    Static,
    Switch,
    TabbedContent,
    TabPane,
    TextArea,
)

from ethernity.app.application import EthernityApp
from ethernity.app.help_content import HELP_MODES
from ethernity.app.input_parsers import parse_threshold_count
from ethernity.app.screens.confirm_action import ConfirmActionScreen
from ethernity.app.screens.file_picker import FilePickerScreen
from ethernity.app.screens.help import HelpScreen
from ethernity.app.screens.paste_text import PasteTextScreen
from ethernity.app.screens.task_progress import TaskProgressScreen
from ethernity.app.task_catalog import TASK_TITLES, review_label
from ethernity.app.widgets.form import FormSection
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.app.widgets.workbench import WorkbenchSteps, WorkbenchSummary
from ethernity.app.widgets.workflow.controls import KeyedRadioSet
from ethernity.app.widgets.workflow.options import OptionsEditor, QuorumEditor
from ethernity.app.widgets.workflow.paths import PathSelectionEditor
from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.app.widgets.workflow.steps import WorkflowStep, WorkflowStepStack
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.app.workspaces.workspace_controls import WorkspacePathList
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.formats.extension_mode import UpdateMode
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.file_summary import display_path
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.presentation.builder import build_task_presentation
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState
from ethernity.tasks.source_assessment import SourceAssessment
from ethernity.version import get_ethernity_version
from ethernity.workflows.shared import events
from tests.support.pilot import (
    click_when_ready,
    wait_for_condition as _wait_for_condition,
    wait_for_focus,
    wait_for_widget,
)


@pytest.fixture(autouse=True)
def _isolate_default_app_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep TUI tests deterministic and away from the user's real config file."""
    config_path = tmp_path / "default-config.toml"
    config_path.write_bytes(DEFAULT_CONFIG_PATH.read_bytes())
    from_current = SettingsTaskState.from_current.__func__

    def load_settings(
        cls: type[SettingsTaskState],
        requested_path: Path | None = None,
    ) -> SettingsTaskState:
        return from_current(cls, config_path if requested_path is None else requested_path)

    monkeypatch.setattr(SettingsTaskState, "from_current", classmethod(load_settings))


async def _type_text(pilot, value: str) -> None:
    for character in value:
        await pilot.press("space" if character == " " else character)


async def _choose_picker_paths(app: EthernityApp, pilot, *paths: Path) -> None:
    await _wait_for_condition(
        pilot,
        lambda: (
            isinstance(app.screen, FilePickerScreen)
            and bool(app.screen.query("#file-picker-selected"))
        ),
        "file picker to mount",
    )
    picker = app.screen
    assert isinstance(picker, FilePickerScreen)
    picker.set_selected_paths(paths)
    await pilot.pause()
    assert await pilot.click("#file-picker-choose")
    await _wait_for_condition(
        pilot,
        lambda: not isinstance(app.screen, FilePickerScreen),
        "file picker to close",
    )


async def _save_picker_name(app: EthernityApp, pilot, value: str) -> None:
    await _wait_for_condition(
        pilot,
        lambda: (
            isinstance(app.screen, FilePickerScreen) and bool(app.screen.query("#file-picker-name"))
        ),
        "save picker to mount",
    )
    assert isinstance(app.screen, FilePickerScreen)
    field = app.screen.query_one("#file-picker-name", Input)
    field.value = ""
    field.focus()
    await _type_text(pilot, value)
    await pilot.press("enter")
    await _wait_for_condition(
        pilot,
        lambda: not isinstance(app.screen, FilePickerScreen),
        "save picker to close",
    )


async def _save_pasted_text(app: EthernityApp, pilot, value: str) -> None:
    assert isinstance(app.screen, PasteTextScreen)
    field = app.screen.query_one("#paste-text-input", TextArea)
    field.load_text(value)
    await pilot.click("#paste-text-save")
    await pilot.pause()


async def _select_guided_radio(container, pilot, label: str) -> None:
    button = next(button for button in container.query(RadioButton) if str(button.label) == label)
    button.value = True
    await pilot.pause()


def _static_text(app: EthernityApp, selector: str) -> str:
    return str(app.screen.query_one(selector, Static).content)


def _allow_ui_source_assessment(monkeypatch: pytest.MonkeyPatch) -> None:
    def assess(request) -> SourceAssessment:
        return SourceAssessment(
            source_kind=request.source_kind,
            source_label=request.source_label,
            source_summary=request.source_summary,
            backup_identity="a340606afa811eb9",
            version_summary="2 backup documents found",
            has_updates=True,
            document_count=2,
        )

    monkeypatch.setattr(
        "ethernity.tasks.source_assessment.assess_source_request",
        assess,
    )


def _checklist_text(app: EthernityApp) -> str:
    return _workspace_text(app)


def _workspace_text(app: EthernityApp) -> str:
    workspace_id = f"#{app.active_task}-workspace"
    if app.active_task == "settings":
        workspace_id = "#settings-form"
    workspace = app.screen.query_one(workspace_id)
    lines: list[str] = []
    for static in workspace.query(Static):
        lines.append(str(static.content))
    # The summary rail owns step summaries; editors no longer duplicate them in headers.
    if app.active_task != "settings":
        for row in app.query_one(WorkbenchSummary).query(".workbench-summary-row"):
            if row.display:
                lines.extend(str(static.content) for static in row.query(Static))
    for path_list in workspace.query(SelectionList):
        lines.append(_selection_list_text(path_list))
    for path_list in workspace.query(WorkspacePathList):
        lines.append(_workspace_path_list_text(path_list))
    return "\n".join(line for line in lines if line)


def _selection_list_text(selection_list: SelectionList) -> str:
    lines: list[str] = []
    for option in selection_list.options:
        prompt = option.prompt
        lines.append(prompt.plain if isinstance(prompt, Text) else str(prompt))
    return "\n".join(lines)


def _workspace_path_list_text(path_list: WorkspacePathList) -> str:
    return "\n".join(
        option.prompt.plain if isinstance(option.prompt, Text) else str(option.prompt)
        for option in path_list.options
    )


def _preview_text(app: EthernityApp) -> str:
    state = app._current_state()
    validation = state.validate_task()
    preview = state.preview()
    lines: list[str] = []
    if not validation.ready and validation.issues:
        lines.append(f"Next required action\n{validation.issues[0].message}")
    for item in preview.items:
        lines.append(item.label)
        if item.detail:
            lines.append(item.detail)
    for issue in (
        *validation.issues,
        *[warning for warning in preview.warnings if warning.code != "FINAL_REVIEW_REQUIRED"],
    ):
        lines.append(issue.message)
    result = getattr(app, "_last_execution_result", None)
    if result is not None:
        lines.append(result.message)
        lines.extend(str(path) for path in result.output_paths)
    return "\n".join(lines)


def _review_text(app: EthernityApp) -> str:
    body = app.screen.query_one("#review-body")
    return "\n".join(str(block.content) for block in body.query(Static) if str(block.content))


def _result_text(app: EthernityApp) -> str:
    modal = app.screen.query_one("#result-modal")
    lines = [str(static.content) for static in modal.query(Static)]
    for option_list in modal.query(OptionList):
        lines.extend(str(option.prompt) for option in option_list.options)
    for log in modal.query(RichLog):
        lines.append(_rich_log_text(log))
    return "\n".join(lines)


def _assert_success_result_modal_layout(app: EthernityApp) -> None:
    modal = app.screen.query_one("#result-modal")
    body = modal.query_one("#result-body")
    actions = modal.query_one("#result-actions")

    assert body.styles.overflow_y == "auto"
    assert body.region.y + body.region.height <= actions.region.y
    assert actions.region.y + actions.region.height <= modal.region.y + modal.region.height
    assert not list(modal.query(MarkdownViewer))
    assert not list(modal.query("#result-log"))
    assert list(modal.query("#result-output"))


def _rich_log_text(log: RichLog) -> str:
    return "\n".join(line.text.strip() for line in log.lines if line.text.strip())


def _help_markdown_text(app: EthernityApp) -> str:
    return app.screen.query_one("#help-body", MarkdownViewer).document.source


def _button_label(app: EthernityApp, selector: str) -> str:
    return str(app.screen.query_one(selector, Button).label)


def _assert_buttons_are_spaced(container) -> None:
    buttons = [
        button for button in container.query(Button) if button.display and button.region.width > 0
    ]
    assert buttons
    for button in buttons:
        assert button.region.height == (1 if button.screen.size.height < 28 else 3)
        assert len(str(button.label)) <= button.region.width
    for previous, current in zip(buttons, buttons[1:], strict=False):
        assert current.region.y == previous.region.y
        assert current.region.x >= previous.region.x + previous.region.width + 1


def _assert_modal_action_buttons_are_spaced(app: EthernityApp) -> None:
    _assert_buttons_are_spaced(app.screen.query_one(".modal-action-row"))


def test_textual_app_switches_between_backup_and_restore() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            assert app.active_task == "backup"
            assert not list(app.screen.query(Header))
            assert _static_text(app, "#app-header-brand") == "ETHERNITY"
            assert _static_text(app, "#app-header-title") == "Paper backup & recovery"
            assert _static_text(app, "#app-header-status") == f"v{get_ethernity_version()}"
            assert not list(app.query("#nav-drawer, #nav-strip"))
            assert app.query_one("#nav-create", Button).has_class("active-task")
            assert not app.query_one("#nav-restore", Button).has_class("active-task")
            assert "Choose files to back up" in _static_text(app, "#canvas-title")

            await pilot.press("2")
            await pilot.pause()

            assert app.active_task == "restore"
            assert "Restore files" in _static_text(app, "#canvas-title")
            assert app.query_one("#workflow-restore-source-body", SourceChooser).display
            assert app.query_one("#nav-restore", Button).has_class("active-task")
            assert not app.query_one("#nav-create", Button).has_class("active-task")

    asyncio.run(run())


def test_textual_app_nav_highlight_does_not_switch_workflow() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.press("ctrl+b", "right")
            await pilot.pause()

            assert app.active_task == "backup"
            assert "Choose files to back up" in _static_text(app, "#canvas-title")

            await pilot.press("enter")
            await pilot.pause()

            assert app.active_task == "restore"
            assert "Restore files" in _static_text(app, "#canvas-title")

    asyncio.run(run())


def test_textual_app_numeric_workflow_switch_moves_focus_out_of_hidden_workspace() -> None:
    async def run() -> None:
        app = EthernityApp(backup_state=BackupTaskState(input_paths=[Path("secrets.txt")]))
        async with app.run_test(size=(100, 30)) as pilot:
            app.query_one("#workspace-backup-files", Button).focus()
            await pilot.pause()

            await pilot.press("2")
            await pilot.pause()

            assert app.active_task == "restore"
            source_load = app.query_one(
                "#workflow-restore-source-body-load",
                Button,
            )
            assert app.screen.focused is source_load
            assert app.screen.focused.region.width > 0

            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, FilePickerScreen)
            assert _static_text(app, "#file-picker-title") == "Load backup documents"

    asyncio.run(run())


def test_textual_app_palette_changes_shell_colors() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            workspace = app.screen
            nav = app.query_one("#nav-menu")
            workspace_before = workspace.styles.background
            nav_before = nav.styles.background

            app.theme = "textual-light"
            await pilot.pause(0.05)

            assert app.current_theme.name == "textual-light"
            assert workspace.styles.background != workspace_before
            assert nav.styles.background != nav_before

    asyncio.run(run())


def test_textual_app_workspace_shows_real_flow_controls() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            _assert_absent_controls(
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
            assert "No files selected" in _checklist_text(app)
            assert not app.query_one("#backup-files-list", WorkspacePathList).display
            assert _static_text(app, "#backup-files-list-empty") == "No files selected."
            assert not app.query_one("#backup-files-value").display
            assert not app.query_one("#backup-files-panel").display
            assert _button_label(app, "#workspace-backup-files") == "Choose files..."
            assert _button_label(app, "#canvas-primary") == "Continue >"
            assert not app.query_one("#canvas-primary", Button).disabled
            assert app.query_one("#canvas-primary", Button).region.height == 3
            assert app.query_one("#canvas-primary").region.width <= 32
            assert not app.query_one("#workspace-backup-clear-files", Button).display

            await pilot.click("#workspace-backup-files")
            await pilot.pause()

            assert isinstance(app.screen, FilePickerScreen)

            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("7")
            await pilot.pause()

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
            assert "config.toml" in _static_text(app, "#setting-value-config")
            assert not app.query_one("#task-action-bar").display

            await pilot.press("3")
            await pilot.pause()

            assert app.active_task == "add_files"
            assert app.screen.query_one("#canvas-task-workspaces").display
            assert not app.screen.query_one("#canvas-settings-workspace").display
            assert _button_label(app, "#workflow-add_files-source-body-load") == (
                "Load backup documents..."
            )
            assert not app.query_one(WorkbenchSummary).display
            assert app.query_one(
                "#workflow-add_files-source-body",
                SourceChooser,
            ).display
            assert _button_label(app, "#canvas-primary") == "Continue >"

    asyncio.run(run())


def test_textual_app_blocked_workflows_show_inline_summary_and_fix_action() -> None:
    expected = {
        "1": (
            "backup",
            "Review backup",
            "#workspace-backup-files",
            "Choose at least one file or folder",
        ),
        "2": (
            "restore",
            review_label("restore"),
            "#workflow-restore-source-body-load",
            "Choose backup documents.",
        ),
        "3": (
            "add_files",
            review_label("add_files"),
            "#workflow-add_files-source-body-load",
            "Choose backup documents, recovery text, or exported payloads.",
        ),
        "4": (
            "rebuild",
            review_label("rebuild"),
            "#workflow-rebuild-source-body-load",
            "Choose a backup folder or scanned pages.",
        ),
        "5": (
            "replace_recovery_docs",
            review_label("replace_recovery_docs"),
            "#workflow-replace_recovery_docs-source-body-source-load",
            "Choose backup documents.",
        ),
    }

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            for key, (
                active_task,
                _review_label,
                focus_selector,
                blocker,
            ) in expected.items():
                await pilot.press(key)
                await pilot.pause()

                assert app.active_task == active_task
                assert _button_label(app, "#canvas-primary") == "Continue >"
                assert not list(app.screen.query("#canvas-footer-hints"))
                assert blocker in _preview_text(app)
                assert not list(app.screen.query("#preview-issues"))

                await pilot.press("ctrl+r")
                await pilot.pause()

                assert not list(app.screen.query("#review-modal"))
                assert app.screen.focused is app.query_one(focus_selector)
                if app.active_task in app.workflow_ui_states:
                    assert blocker in _workspace_text(app)

    asyncio.run(run())


def test_textual_app_editors_and_review_open_centered() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await app.action_edit_passphrase()
            await pilot.pause()
            edit_region = app.screen.query_one("#edit-field-modal").region
            assert edit_region.x > 0
            assert edit_region.y > 0

            await pilot.press("escape")
            await pilot.pause()
            await app.action_edit_primary()
            await pilot.pause()
            picker_region = app.screen.query_one("#file-picker-modal").region
            assert picker_region.x > 0
            assert picker_region.y > 0

            await pilot.press("escape")
            await pilot.pause()
            app.backup_state.input_paths = [Path("README.md")]
            app.backup_state.output_dir = Path("backup-out")
            app.refresh_task_view()
            await pilot.press("ctrl+r")
            await pilot.pause()
            review_region = app.screen.query_one("#review-modal").region
            assert review_region.x == (120 - review_region.width) // 2
            assert review_region.y == 0
            assert review_region.width == 100
            assert review_region.height == 31

    asyncio.run(run())


def test_textual_app_workspace_buttons_keep_gaps_and_clear_primary_action() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            for task_key in ("1", "2", "3", "4", "5", "6"):
                await pilot.press(task_key)
                await pilot.pause()

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
        async with app.run_test(size=(96, 32)) as pilot:
            await app.action_edit_passphrase()
            await pilot.pause()
            _assert_modal_action_buttons_are_spaced(app)

            await pilot.press("escape")
            await pilot.pause()
            await app.push_screen(
                PasteTextScreen(
                    title="Paste recovery text",
                    prompt="Paste recovery text",
                )
            )
            await pilot.pause()
            _assert_modal_action_buttons_are_spaced(app)

            await pilot.press("escape")
            await pilot.pause()
            await app.action_edit_primary()
            await pilot.pause()
            _assert_modal_action_buttons_are_spaced(app)

            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            _assert_modal_action_buttons_are_spaced(app)

            await pilot.press("escape")
            await pilot.pause()
            app.backup_state.input_paths = [Path("README.md")]
            app.backup_state.output_dir = Path("backup-out")
            app.refresh_task_view()
            await pilot.press("ctrl+r")
            await pilot.pause()
            _assert_modal_action_buttons_are_spaced(app)

    asyncio.run(run())


def test_textual_app_field_controls_use_available_wide_space() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(200, 48)) as pilot:
            for task_key in ("1", "2", "3", "4", "5", "6"):
                await pilot.press(task_key)
                await pilot.pause()

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
            await pilot.pause()
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
        async with app.run_test(size=(80, 24)) as pilot:
            workspace = app.query_one("#workspace").region
            await pilot.press("ctrl+b")
            await pilot.pause()
            assert app.screen.focused is app.query_one("#nav-create", Button)
            assert not app._nav_menu_open
            await pilot.click("#nav-manage")
            await pilot.pause()
            assert app.query_one("#workspace").region == workspace
            await pilot.press("down", "enter")
            await pilot.pause()
            assert app.active_task == "rebuild"
            assert not app._nav_menu_open
            assert app.query_one("#canvas-task-workspaces").has_focus_within

    asyncio.run(run())


def test_textual_app_workspaces_are_grouped_into_sections() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            expected_steps = {
                "restore": 4,
                "add_files": 4,
                "rebuild": 3,
                "replace_recovery_docs": 4,
            }
            for task_key in ("1", "2", "3", "4", "5", "6"):
                await pilot.press(task_key)
                await pilot.pause()

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
        async with app.run_test(size=(120, 48)) as pilot:
            for task_key in ("1", "2", "3", "4", "5", "6"):
                await pilot.press(task_key)
                await pilot.pause()

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
        async with app.run_test(size=(120, 48)) as pilot:
            for task_key in ("1", "2", "3", "4", "5", "6"):
                await pilot.press(task_key)
                await pilot.pause()

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
        async with app.run_test(size=(120, 48)) as pilot:
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
                await pilot.pause()
                assert app.query_one(selector, UnlockEditor).selected_method is None

            await pilot.press("5")
            await pilot.pause()
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


def test_textual_app_replacement_recovery_choice_uses_inline_quorum() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("5")
            mode = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-mode",
                OptionsEditor,
            )
            await _select_guided_radio(
                mode,
                pilot,
                "Custom quorum",
            )

            quorum = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum",
                QuorumEditor,
            )
            assert quorum.display
            assert app.replace_recovery_docs_state.recovery_threshold == 2
            assert app.replace_recovery_docs_state.recovery_document_count == 3

            await _select_guided_radio(
                mode,
                pilot,
                "3 sheets; any 2 can restore (recommended)",
            )
            assert app.replace_recovery_docs_state.recovery_threshold == 2
            assert app.replace_recovery_docs_state.recovery_document_count == 3

    asyncio.run(run())


def test_textual_app_empty_path_lists_use_empty_states_instead_of_placeholder_rows() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("3")
            await pilot.pause()
            editor = app.query_one("#workflow-add_files-files-body", PathSelectionEditor)
            path_list = editor.query_one(SelectionList)
            empty = editor.query_one(".guided-empty", Static)

            assert not path_list.display
            assert empty.display
            assert not path_list.options
            assert "No files or folders selected" in str(empty.content)

    asyncio.run(run())


def test_textual_app_command_palette_commands_are_workflow_aware(tmp_path) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            backup_commands = {command.title for command in app.get_system_commands(app.screen)}

            assert {
                "Help for this screen",
                "Set output folder",
                "Go to first problem",
                "Add backup files",
                "Quit Ethernity",
            } <= backup_commands
            assert not {"Keys", "Maximize", "Screenshot", "Quit"} & backup_commands
            assert "Open output folder" not in backup_commands
            assert not list(app.screen.query("#canvas-footer-hints"))

            output_dir = tmp_path / "backup-output"
            app._last_execution_result = TaskExecutionResult(
                status="succeeded",
                message="Created",
                output_paths=(output_dir / "backup.pdf", output_dir / "index.json"),
            )
            commands_after_success = {
                command.title for command in app.get_system_commands(app.screen)
            }

            assert "Open output folder" in commands_after_success

            await pilot.press("2")
            await pilot.pause()
            restore_commands = {command.title for command in app.get_system_commands(app.screen)}

            assert {
                "Change unlock method",
                "Paste recovery text",
                "Load backup payload",
                "Load backup pages",
                "Set latest fingerprint",
                "Set restore folder",
            } <= restore_commands

            await pilot.press("3")
            await pilot.pause()
            add_files_commands = {command.title for command in app.get_system_commands(app.screen)}

            assert {
                "Set update output folder",
                "Paste recovery text",
                "Load backup payload",
                "Load backup documents",
                "Add or replace files",
            } <= add_files_commands
            assert "Set backup folder" not in add_files_commands
            assert {"Change unlock method", "Set latest fingerprint"} <= add_files_commands

            await pilot.press("5")
            await pilot.pause()
            replacement_commands = {
                command.title for command in app.get_system_commands(app.screen)
            }

            assert {
                "Load existing backup",
                "Paste recovery text",
                "Set latest fingerprint",
                "Load backup payload",
            } <= replacement_commands

            await pilot.press("6")
            await pilot.pause()
            kit_commands = {command.title for command in app.get_system_commands(app.screen)}

            assert "Set PDF output" in kit_commands

            await pilot.press("7")
            await pilot.pause()
            settings_commands = {command.title for command in app.get_system_commands(app.screen)}

            assert {"Reset current section", "Reset all settings"} <= settings_commands

    asyncio.run(run())


def test_textual_app_keeps_pristine_backup_neutral_then_shows_selected_file_summary() -> None:
    async def run() -> None:
        app = EthernityApp(settings_state=SettingsTaskState.from_current(DEFAULT_CONFIG_PATH))
        async with app.run_test(size=(120, 48)) as pilot:
            assert not app.query_one("#backup-files-value").display
            assert not app.query_one("#backup-files-panel").display
            assert not app.query_one("#backup-destination-status").display
            assert _static_text(app, "#backup-output-value") == ("backup-<id>")
            assert "Choose at least one file or folder to back up" in _preview_text(app)

            await app.action_edit_primary()
            await _choose_picker_paths(app, pilot, Path("README.md"))

            await _wait_for_condition(
                pilot,
                lambda: app.backup_state.current_estimate() is not None,
                "backup file and page estimate",
            )
            assert "1 file" in _static_text(app, "#backup-files-value")
            assert app.query_one("#backup-files-panel").display
            assert "KiB" in _static_text(app, "#backup-files-value")
            assert "About" in _static_text(app, "#backup-output-summary")
            assert not app.query_one("#backup-destination-status").display
            assert _static_text(app, "#backup-output-value") == ("backup-<id>")
            assert _button_label(app, "#canvas-primary") == "Continue >"
            await pilot.press("ctrl+r")
            await pilot.pause()
            review_text = _review_text(app)
            assert "Create backup documents in backup-<id>" in review_text
            assert "backup-<id>" in review_text
            assert "no output path is selected" not in review_text
            await pilot.click("#review-close")
            await pilot.pause()

            await app.action_edit_output()
            await _save_picker_name(app, pilot, "backup-out")

            assert "1 file" in _static_text(
                app,
                "#backup-files-value",
            )
            assert not app.query_one("#backup-destination-status").display
            assert _button_label(app, "#canvas-primary") == "Continue >"
            assert not list(app.screen.query("#canvas-footer-hints"))

    asyncio.run(run())


def test_textual_app_restore_loaded_without_destination_stays_blocked_inline() -> None:
    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
            )
        )
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("2")
            await pilot.pause()

            assert app.query_one("#workflow-restore-source-body", SourceChooser).display
            assert "Passphrase set" in _workspace_text(app)
            assert app.query_one("#workflow-restore-destination-body-action", Button).label == (
                "Choose restore folder..."
            )
            assert not app.query_one(WorkbenchSummary).display
            assert _button_label(app, "#canvas-primary") == "Continue >"
            assert "Choose where recovered files will be written." in _preview_text(app)
            assert not list(app.screen.query("#preview"))

            await pilot.press("ctrl+r")
            await pilot.pause()

            assert not list(app.screen.query("#review-modal"))
            assert "Error: Choose where recovered files will be written." in _workspace_text(app)
            assert app.screen.focused is app.query_one(
                "#workflow-restore-destination-body-action",
                Button,
            )

    asyncio.run(run())


def test_textual_app_common_terminal_sizes_keep_workspaces_readable() -> None:
    async def run() -> None:
        for size in ((160, 48), (140, 36), (120, 36), (96, 30), (80, 30)):
            app = EthernityApp()
            async with app.run_test(size=size) as pilot:
                workspace = app.query_one("#workspace").region

                assert workspace.width == min(size[0], 140)
                assert workspace.x == (size[0] - workspace.width) // 2
                assert workspace.width >= (24 if size[0] <= 80 else 36)
                assert workspace.x + workspace.width <= size[0]
                assert not list(app.screen.query("#preview"))

                for task_key in ("1", "2", "3", "4", "5", "6"):
                    await pilot.press(task_key)
                    await pilot.pause()

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


def test_textual_app_help_is_contextual_and_concise() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("?")
            await pilot.pause()

            assert isinstance(app.screen, HelpScreen)
            assert _static_text(app, "#help-title") == "Create backup"
            help_text = _help_markdown_text(app)
            assert "## Create backup" not in help_text
            assert "Encrypt files and folders" in _static_text(app, "#help-intro")
            assert help_text.count("### ") == 4
            assert "Enter or Space opens a dropdown" in help_text
            assert "new backup-<id> folder inside the selected destination" in help_text
            assert "Existing backups stay unchanged" in help_text
            assert "Store recovery sheets in separate places" in help_text
            assert "Scan at least one printed QR code" in help_text
            assert "Ctrl+R: Review" in _static_text(app, "#help-shortcuts")
            assert not list(app.screen.query("#help-mode-index"))

            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()

            assert isinstance(app.screen, HelpScreen)
            assert _static_text(app, "#help-title") == "Restore files"
            help_text = _help_markdown_text(app)
            assert "## Restore files" not in help_text
            assert "Load the backup documents" in help_text
            assert "passphrase, recovery sheets, or recovery payload files" in help_text
            assert "Latest means the newest valid update in the documents you loaded" in help_text
            assert "cannot check for newer copies elsewhere" in help_text
            assert "Keep signature verification on" in help_text
            assert "Use an empty folder" in help_text

            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("7")
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()

            assert isinstance(app.screen, HelpScreen)
            assert _static_text(app, "#help-title") == "Settings"
            help_text = _help_markdown_text(app)
            assert _static_text(app, "#help-intro") == (
                "Set defaults for future workflows. Changes save immediately."
            )
            assert "Create backup uses a folder named for the backup ID" in help_text
            assert "Ctrl+R" not in _static_text(app, "#help-shortcuts")

    asyncio.run(run())


def test_textual_app_all_help_modes_stay_focused_and_plain() -> None:
    disallowed_help_phrases = (
        "Use it when",
        "Do not use it when",
        "Common mistakes",
        "Simply",
        "Seamless",
        "Powerful",
        "This allows",
        "This ensures",
        "starting a new backup set",
        "You need the data back",
        "Leaving the output folder unset",
        "Recovery papers",
        "threshold/count",
        "payload documents",
        "PDF path",
        "Update destination",
        "Rebuild destination",
        "No backup input",
        "Use supplied latest version",
        "Enter expected fingerprint...",
        "Restore defaults",
        "Restore all defaults",
    )
    for mode in HELP_MODES:
        assert mode.summary
        assert len(mode.sections) == 3
        assert mode.shortcuts
        help_text = "\n".join(
            (
                mode.summary,
                *(section.title for section in mode.sections),
                *(section.body for section in mode.sections),
                *(note for section in mode.sections for note in section.notes),
                *(shortcut.label for shortcut in mode.shortcuts),
            )
        )
        assert all(section.body for section in mode.sections)
        assert all(len(section.notes) <= 2 for section in mode.sections)
        assert all(shortcut.keys and shortcut.label for shortcut in mode.shortcuts)
        for phrase in disallowed_help_phrases:
            assert phrase not in help_text


def test_file_picker_deselects_paths_and_can_go_up() -> None:
    class PickerEvent:
        def __init__(self, path: Path) -> None:
            self.path = path
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await app.action_edit_primary()
            await pilot.pause()

            assert isinstance(app.screen, FilePickerScreen)
            picker = app.screen
            picker.set_selected_paths((Path("README.md"), Path("docs")))
            selected = picker.query_one("#file-picker-selected", SelectionList)
            selected.highlighted = 0
            selected.focus()

            await pilot.press("enter")
            await pilot.pause()

            assert picker._selected_paths == (Path("docs"),)

            tree_event = PickerEvent(Path("docs"))
            picker.on_directory_tree_directory_selected(
                cast(DirectoryTree.DirectorySelected, tree_event)
            )

            assert tree_event.stopped
            assert picker._selected_paths == (Path("docs"),)

            tree = picker.query_one("#file-picker-tree", DirectoryTree)
            root_before = Path(tree.path)

            await pilot.click("#file-picker-up")
            await pilot.pause()

            assert Path(tree.path) == root_before.parent
            assert picker.query_one("#file-picker-location", Input).value == str(root_before.parent)

    asyncio.run(run())


def test_textual_app_diagnostics_are_on_demand_and_redacted(tmp_path) -> None:
    async def run() -> None:
        input_path = tmp_path / "secrets.txt"
        input_path.write_text("hello backup internals", encoding="utf-8")
        settings = SettingsTaskState.from_current()
        settings.set_setting_value("ui_show_internals", True)
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[input_path],
                output_dir=tmp_path / "backup-out",
                passphrase="super secret",
            ),
            settings_state=settings,
        )
        async with app.run_test(size=(120, 32)) as pilot:
            command_titles = {command.title for command in app.get_system_commands(app.screen)}
            assert "Show backup diagnostics" in command_titles
            internals_button = app.query_one("#canvas-internals", Button)
            primary_button = app.query_one("#canvas-primary", Button)
            assert internals_button.display
            assert internals_button.region.x < primary_button.region.x
            assert _button_label(app, "#canvas-internals") == "Diagnostics"

            await pilot.click("#canvas-internals")
            await pilot.pause()

            assert _static_text(app, "#diagnostics-title") == "Backup diagnostics"
            tabs = app.screen.query_one("#diagnostics-tabs", TabbedContent)
            assert tabs.active == "diagnostics-tab-0"
            assert len(list(app.screen.query(TabPane))) == 9
            first_log = app.screen.query_one("#diagnostics-log-0", RichLog)
            assert app.screen.focused is first_log
            assert "Passphrase" in _rich_log_text(first_log)
            assert "super secret" not in _rich_log_text(first_log)

            tabs.active = "diagnostics-tab-1"
            await _wait_for_condition(
                pilot,
                lambda: bool(_rich_log_text(app.screen.query_one("#diagnostics-log-1", RichLog))),
                "manifest diagnostics to render",
            )

            manifest_log = app.screen.query_one("#diagnostics-log-1", RichLog)
            assert app.screen.focused is manifest_log
            assert manifest_log.highlight
            assert "created_at" in _rich_log_text(manifest_log)
            assert "<masked bytes=" in _rich_log_text(manifest_log)

            tabs.active = "diagnostics-tab-2"
            await _wait_for_condition(
                pilot,
                lambda: bool(_rich_log_text(app.screen.query_one("#diagnostics-log-2", RichLog))),
                "backup document diagnostics to render",
            )

            metadata_log = app.screen.query_one("#diagnostics-log-2", RichLog)
            assert app.screen.focused is metadata_log
            assert "manifest_cbor_bytes" in _rich_log_text(metadata_log)
            assert '"cbor"' in _rich_log_text(metadata_log)
            assert '"seed": "<masked bytes=' in _rich_log_text(metadata_log)
            close_button = app.screen.query_one("#diagnostics-close", Button)
            assert str(close_button.label) == "Close"
            assert close_button.variant == "default"

            assert str(app.screen.query_one("#diagnostics-reveal-label", Label).content) == (
                "Show sensitive values"
            )
            switch = app.screen.query_one("#diagnostics-reveal", Switch)
            switch.toggle()
            await _wait_for_condition(
                pilot,
                lambda: "super secret" in _rich_log_text(first_log),
                "revealed diagnostics to render",
            )

            assert switch.value
            assert "super secret" in _rich_log_text(first_log)
            assert '"seed": "<masked bytes=' not in _rich_log_text(metadata_log)
            assert "00000000" not in _rich_log_text(metadata_log)

    asyncio.run(run())


def test_textual_app_hides_internals_button_when_config_option_is_off(tmp_path) -> None:
    async def run() -> None:
        input_path = tmp_path / "secrets.txt"
        input_path.write_text("hello backup internals", encoding="utf-8")
        settings = SettingsTaskState.from_current()
        settings.set_setting_value("ui_show_internals", False)
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[input_path],
                output_dir=tmp_path / "backup-out",
            ),
            settings_state=settings,
        )
        async with app.run_test(size=(120, 32)):
            command_titles = {command.title for command in app.get_system_commands(app.screen)}

            assert "Show backup diagnostics" not in command_titles
            assert not app.query_one("#canvas-internals", Button).display

    asyncio.run(run())


def test_textual_app_hides_diagnostics_until_backup_files_exist() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)):
            command_titles = {command.title for command in app.get_system_commands(app.screen)}

            assert "Show backup diagnostics" not in command_titles
            assert not list(app.screen.query("#preview-diagnostics"))

    asyncio.run(run())


def test_textual_app_supports_hjkl_and_arrow_navigation() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(160, 32)) as pilot:
            await pilot.pause()
            await pilot.press("h", "l")
            await pilot.pause()
            assert app.active_task == "backup"
            assert app.screen.focused is app.query_one("#nav-restore", Button)
            await pilot.press("enter")
            await pilot.pause()
            assert app.active_task == "restore"
            await pilot.press("h", "right", "down")
            await pilot.pause()
            assert app._nav_menu_open
            await pilot.press("j", "k", "enter")
            await pilot.pause()
            assert app.active_task == "add_files"
            await pilot.press("h", "left", "enter")
            await pilot.pause()
            assert app.active_task == "restore"
            await pilot.press("h", "left", "enter")
            await pilot.pause()
            assert app.active_task == "backup"
            assert app.screen.focused is app.query_one("#workspace-backup-files", Button)

    asyncio.run(run())


def test_textual_app_hjkl_leave_closed_selects_without_opening_them() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.press("6")
            await pilot.pause()

            select = app.query_one("#workspace-kit-variant-select", Select)
            select.focus()
            await pilot.press("j")
            await pilot.pause()

            assert not select.expanded
            assert app.screen.focused is app.query_one("#workspace-kit-paper", Select)
            await pilot.press("k")
            assert app.screen.focused is select
            assert not select.expanded

    asyncio.run(run())


def test_textual_app_switches_to_kit_and_settings() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("6")
            await pilot.pause()

            assert app.active_task == "kit"
            assert "Create offline recovery kit" in _static_text(app, "#canvas-title")
            assert "Built-in kit" not in _checklist_text(app)
            assert "recovery_kit_qr.pdf" in _checklist_text(app)
            assert "Kit type" in _checklist_text(app)
            assert "Save as" in _checklist_text(app)
            assert app.query_one("#workspace-kit-chunk-size", Button).display
            assert app.query_one("#workspace-kit-variant-select", Select).value == "lean"

            await pilot.press("7")
            await pilot.pause()

            assert app.active_task == "settings"
            assert _static_text(app, "#canvas-title") == ""
            assert app.query_one("#setting-control-render_style", Select).value == (
                app.settings_state.design
            )

    asyncio.run(run())


def test_textual_app_switches_to_maintenance_tasks() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("3")
            await pilot.pause()

            assert app.active_task == "add_files"
            assert "Add files to backup" in _static_text(app, "#canvas-title")
            assert app.query_one("#workflow-add_files-source-body", SourceChooser).display

            await pilot.press("4")
            await pilot.pause()

            assert app.active_task == "rebuild"
            assert "Rebuild backup" in _static_text(app, "#canvas-title")
            assert app.query_one("#workflow-rebuild-source-body", SourceChooser).display

            await pilot.press("5")
            await pilot.pause()

            assert app.active_task == "replace_recovery_docs"
            assert "Create replacement recovery sheets" in _static_text(app, "#canvas-title")
            assert app.query_one(
                "#workflow-replace_recovery_docs-source-body-source", SourceChooser
            ).display

    asyncio.run(run())


def test_textual_app_canvas_rows_edit_secondary_choices() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            assert "Store recovery sheets separately" in _static_text(
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
            await pilot.pause()

            assert app.backup_state.recovery_method == "single_phrase"
            assert "Warning: One recovery phrase" in _static_text(
                app,
                "#backup-recovery-status",
            )
            assert "Keep the recovery phrase separate" in _static_text(
                app,
                "#backup-recovery-help",
            )
            assert "One recovery phrase is a single secret" in _preview_text(app)

            app._apply_backup_recovery("3/5")
            await pilot.pause()

            assert app.backup_state.recovery_method == "custom_shards"
            assert "Warning: 5 recovery sheets; any 3 required" in _static_text(
                app,
                "#backup-recovery-status",
            )
            assert "Store recovery sheets separately" in _static_text(
                app,
                "#backup-recovery-help",
            )
            assert "A custom quorum changes how many sheets you need" in _preview_text(app)

            await pilot.press("6")
            await pilot.pause()
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


def test_textual_app_splits_backup_files_and_folders() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await app.action_edit_primary()
            await _choose_picker_paths(app, pilot, Path("README.md"), Path("docs"))

            assert [str(path) for path in app.backup_state.input_paths] == ["README.md"]
            assert [str(path) for path in app.backup_state.input_dirs] == ["docs"]

    asyncio.run(run())


def test_textual_app_unlock_recovery_documents_are_real_picker() -> None:
    async def run() -> None:
        app = EthernityApp(restore_state=RestoreTaskState(source_paths=[Path("scan.pdf")]))
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("2")
            await pilot.click("#canvas-primary")
            unlock_methods = app.query_one(
                "#workflow-restore-unlock-body-methods",
                RadioSet,
            )
            unlock_methods.focus()
            await pilot.press("right", "space")
            await pilot.pause()
            await _choose_picker_paths(app, pilot, Path("recovery.pdf"))

            assert [str(path) for path in app.restore_state.recovery_documents] == ["recovery.pdf"]
            assert app.restore_state.passphrase is None
            assert not app.restore_state.recovery_payload_files
            assert "recovery.pdf" in _workspace_text(app)

    asyncio.run(run())


def test_textual_app_unlock_input_lists_show_selected_recovery_inputs() -> None:
    async def run() -> None:
        cases = (
            (
                EthernityApp(
                    add_files_state=AddFilesTaskState(recovery_documents=[Path("add-sheet.pdf")])
                ),
                "3",
                "#workflow-add_files-unlock-body-unlock",
                "recovery_documents",
                "add-sheet.pdf",
            ),
            (
                EthernityApp(
                    rebuild_state=RebuildTaskState(
                        recovery_payload_files=[Path("rebuild-payloads.txt")]
                    )
                ),
                "4",
                "#workflow-rebuild-unlock-body-unlock",
                "recovery_payloads",
                "rebuild-payloads.txt",
            ),
            (
                EthernityApp(
                    replace_recovery_docs_state=ReplaceRecoveryDocsTaskState(
                        recovery_documents=[Path("replace-sheet.pdf")]
                    )
                ),
                "5",
                "#workflow-replace_recovery_docs-unlock-body",
                "recovery_documents",
                "replace-sheet.pdf",
            ),
        )
        for app, key, editor_selector, expected_method, expected_text in cases:
            async with app.run_test(size=(120, 48)) as pilot:
                await pilot.press(key)
                await pilot.pause()

                editor = app.query_one(editor_selector, UnlockEditor)
                assert editor.selected_method == expected_method
                assert expected_text in str(editor.query_one(".guided-detail", Static).content)

        restore_app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                recovery_payload_files=[Path("restore-payloads.txt")],
            )
        )
        async with restore_app.run_test(size=(120, 48)) as pilot:
            await pilot.press("2")
            await pilot.click("#canvas-primary")
            await pilot.pause()

            assert "restore-payloads.txt" in _workspace_text(restore_app)

    asyncio.run(run())


def test_textual_app_restore_source_modes_are_real_pickers() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("2")
            source = app.query_one("#workflow-restore-source-body", SourceChooser)
            assert not source.query(RadioSet)
            await pilot.click("#workflow-restore-source-body-load")
            await pilot.pause()
            assert isinstance(app.screen, FilePickerScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not app.restore_state.source_paths
            assert app.restore_state.recovery_text is None

            await pilot.click("#workflow-restore-source-body-secondary-0")
            await pilot.pause()
            assert isinstance(app.screen, PasteTextScreen)
            await _save_pasted_text(app, pilot, "pasted recovery text")

            assert app.restore_state.recovery_text == "pasted recovery text"
            assert app.restore_state.recovery_text_file is None
            assert not app.restore_state.source_paths
            assert app.restore_state.payloads_file is None
            assert "Pasted text, 1 non-empty line" in _checklist_text(app)

            await pilot.click("#workflow-restore-source-body-secondary-1")
            await pilot.pause()
            await _choose_picker_paths(app, pilot, Path("payloads.json"))

            assert app.restore_state.payloads_file == Path("payloads.json")
            assert app.restore_state.recovery_text is None
            assert app.restore_state.recovery_text_file is None
            assert not app.restore_state.source_paths
            assert "payloads.json" in _checklist_text(app)

    asyncio.run(run())


def test_textual_app_restore_expected_head_fingerprint_is_real_control() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("2")
            assert app.query_one("#restore-verification-section", FormSection).display
            app.query_one("#workspace-restore-expected-head", Button).focus()
            await pilot.pause()
            await pilot.press("enter")
            app.screen.query_one("#edit-field-input", Input).value = "ab" * 32
            await pilot.press("enter")
            await pilot.pause()

            assert app.restore_state.expected_head_doc_hash == "ab" * 32
            assert app.restore_state.to_recovery_request().expected_head_doc_hash == "ab" * 32
            assert "Latest fingerprint" in _preview_text(app)
            assert "Provided" in _preview_text(app)

            source_load = app.query_one(
                "#workflow-restore-source-body-load",
                Button,
            )
            source_load.focus()
            await pilot.press("enter")
            await _choose_picker_paths(app, pilot, Path("scan.pdf"))

            assert app.restore_state.expected_head_doc_hash is None

    asyncio.run(run())


def test_textual_app_expected_fingerprint_is_real_freshness_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_ui_source_assessment(monkeypatch)

    async def run() -> None:
        app = EthernityApp(
            add_files_state=AddFilesTaskState(
                source_paths=[Path("scan.pdf")],
                input_paths=[Path("new.txt")],
                passphrase="secret",
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("3")
            await pilot.press("ctrl+r")
            await pilot.pause()
            assert app.add_files_state.expected_head_doc_hash is None

            app.query_one("#workspace-add-files-fingerprint", Button).focus()
            await pilot.press("enter")
            app.screen.query_one("#edit-field-input", Input).value = "bc" * 32
            await pilot.press("enter")
            await pilot.pause()

            assert app.add_files_state.expected_head_doc_hash == "bc" * 32
            assert "Latest fingerprint provided" in _workspace_text(app)

    asyncio.run(run())


def test_textual_app_fingerprint_actions_match_configured_sources() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("3")
            await pilot.pause()
            assert app.query_one("#workspace-add-files-fingerprint", Button).display

            await pilot.press("4")
            await pilot.pause()
            assert not app.query_one("#workspace-rebuild-fingerprint", Button).display

            await pilot.press("5")
            await pilot.pause()
            assert not app.query_one("#workspace-replace-fingerprint", Button).display

    asyncio.run(run())


def test_textual_app_restore_target_fingerprint_is_real_control() -> None:
    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
            )
        )
        request = app.restore_state.source_assessment_request()
        assert request is not None
        app.restore_state.store_source_assessment(
            request,
            SourceAssessment(
                source_kind=request.source_kind,
                source_label=request.source_label,
                source_summary=request.source_summary,
                backup_identity="a340606afa811eb9",
                version_summary="2 backup documents found",
                has_updates=True,
                document_count=2,
            ),
        )
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("2")
            await pilot.pause()
            await pilot.click(app.query_one(WorkbenchSteps).button_for("target"))
            await pilot.pause()
            target = app.query_one("#workflow-restore-target-body-choices", RadioSet)
            target.focus()
            await wait_for_focus(pilot, target)
            await pilot.press("right", "right", "space")
            await click_when_ready(pilot, "#edit-field-cancel")
            await click_when_ready(pilot, "#workspace-restore-target-fingerprint")
            field = await wait_for_widget(pilot, "#edit-field-input")
            assert isinstance(field, Input)
            field.value = "cd" * 32
            await pilot.press("enter")
            await _wait_for_condition(
                pilot,
                lambda: app.restore_state.extension_doc_hash == "cd" * 32,
                "restore fingerprint to reach task state",
            )

            assert app.restore_state.target == "specific_update"
            assert app.restore_state.extension_index is None
            assert app.restore_state.extension_doc_hash == "cd" * 32
            selected = [str(button.label) for button in target.query(RadioButton) if button.value]
            assert selected == ["Specific version or update"]
            assert "Version matching fingerprint" in _preview_text(app)

    asyncio.run(run())


def test_textual_app_restore_auth_policy_control_is_real() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("2")
            await pilot.pause()

            assert "only when the original has no signatures" in str(
                app.query_one("#workspace-restore-auth-policy", Select).tooltip
            )
            app.query_one("#workspace-restore-auth-policy", Select).value = "allow-unsigned"
            await _wait_for_condition(
                pilot, lambda: app.restore_state.allow_unsigned, "unsigned recovery to be enabled"
            )

            assert app.restore_state.allow_unsigned
            assert app.restore_state.to_recovery_request().allow_unsigned
            assert "Unsigned legacy backups allowed" in _preview_text(app)
            assert not app.query("#restore-authentication-help, #restore-authentication-status")
            assert "signatures will not be required" in _preview_text(app)

            app.query_one("#workspace-restore-auth-policy", Select).value = "require-signed"
            await _wait_for_condition(
                pilot,
                lambda: not app.restore_state.allow_unsigned,
                "signed recovery to be required",
            )

            assert not app.restore_state.allow_unsigned
            assert not app.query("#workspace-restore-resource-policy")

    asyncio.run(run())


def test_textual_app_restore_signature_source_control_is_real() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("2")
            await pilot.pause()

            app.query_one("#workspace-restore-signature-source", Select).value = "text"
            await pilot.pause()
            await _choose_picker_paths(app, pilot, Path("auth.txt"))

            assert app.restore_state.auth_text_file == Path("auth.txt")
            assert app.restore_state.auth_payloads_file is None
            assert app.restore_state.to_recovery_request().auth_text_file == Path("auth.txt")
            assert "Signature text: auth.txt" in _preview_text(app)

            app.query_one("#workspace-restore-signature-source", Select).value = "payloads"
            await pilot.pause()
            await _choose_picker_paths(app, pilot, Path("auth-payloads.json"))

            assert app.restore_state.auth_text_file is None
            assert app.restore_state.auth_payloads_file == Path("auth-payloads.json")
            assert app.restore_state.to_recovery_request().auth_payloads_file == Path(
                "auth-payloads.json"
            )

            app.query_one("#workspace-restore-signature-source", Select).value = "auto"
            await pilot.pause()

            assert app.restore_state.auth_text_file is None
            assert app.restore_state.auth_payloads_file is None

    asyncio.run(run())


def test_textual_app_edit_add_files_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_ui_source_assessment(monkeypatch)

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("3")
            await pilot.click("#workflow-add_files-source-body-load")
            await _choose_picker_paths(app, pilot, Path("scan.pdf"))
            await app.action_edit_primary()
            await _choose_picker_paths(app, pilot, Path("README.md"))
            unlock = app.query_one("#workflow-add_files-unlock-body-unlock", UnlockEditor)
            await _select_guided_radio(unlock, pilot, "Passphrase")
            unlock.query_one(Input).focus()
            await _type_text(pilot, "secret")
            await pilot.press("enter")
            await pilot.pause()
            app.query_one("#workspace-add-files-freshness", Button).focus()
            await pilot.press("enter")
            destination = app.query_one("#workflow-add_files-output-body-value", Input)
            destination.focus()
            await _type_text(pilot, "update-out")
            await pilot.press("enter")
            await pilot.pause()

            assert app.add_files_state.validate_task().ready
            assert app.add_files_state.source_paths == [Path("scan.pdf")]
            assert app.add_files_state.passphrase == "secret"
            assert app.add_files_state.output_dir == Path("update-out")
            assert app.add_files_state.allow_stale_head
            workspace = _checklist_text(app)
            assert "README.md" in workspace
            assert destination.value == "update-out"
            assert "Newest loaded version accepted" in workspace
            assert "Destination" in _preview_text(app)

    asyncio.run(run())


@pytest.mark.portability
def test_textual_app_edit_rebuild_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_ui_source_assessment(monkeypatch)

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("4")
            await pilot.pause()

            await pilot.click("#workflow-rebuild-source-body-load")
            await _choose_picker_paths(app, pilot, Path("docs"))
            unlock = app.query_one("#workflow-rebuild-unlock-body-unlock")
            await _select_guided_radio(unlock, pilot, "Passphrase")
            unlock.query_one(Input).focus()
            await _type_text(pilot, "secret")
            await pilot.press("enter")
            await pilot.pause()
            app.query_one("#workspace-rebuild-freshness", Button).focus()
            await pilot.press("enter")
            destination = app.query_one("#workflow-rebuild-output-body-destination-value", Input)
            destination.focus()
            await _type_text(pilot, "rebuilt")
            await pilot.press("enter")
            await pilot.pause()

            assert app.rebuild_state.validate_task().ready
            assert app.rebuild_state.passphrase == "secret"
            assert app.rebuild_state.output_dir == Path("rebuilt")
            workspace = _checklist_text(app)
            assert "docs" in workspace
            assert destination.value == "rebuilt"
            assert (
                app.query_one("#workflow-rebuild-unlock-body-unlock", UnlockEditor).selected_method
                == "passphrase"
            )
            assert "Print options" not in workspace
            assert app.query_one("#workspace-rebuild-paper", Select).value == "A4"
            assert app.query_one("#workspace-rebuild-design", Select).value == "sentinel"
            assert "Existing backup files" in _preview_text(app)
            assert "Left unchanged" in _preview_text(app)

            assert "harder to scan" in str(
                app.query_one("#workspace-rebuild-qr-chunk-size", Button).tooltip
            )

            await app._select_workbench_step("output")
            await wait_for_focus(pilot, destination)
            assert app.query_one("#rebuild-qr-section", FormSection).display
            density = app.query_one("#workspace-rebuild-qr-chunk-size", Button)
            density.focus()
            await wait_for_focus(pilot, density)
            await pilot.press("enter")
            await _enter_edit_field(app, pilot, "384", plain_input=True)

            assert app.rebuild_state.qr_chunk_size == 384
            assert app.rebuild_state.to_rebuild_request().qr_chunk_size == 384
            assert "Warning:" in _static_text(app, "#rebuild-qr-notice")
            assert "Custom QR density can change page count" in _preview_text(app)

    asyncio.run(run())


def test_textual_app_rebuild_signature_source_control_is_real() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("4")
            await pilot.pause()

            assert app.query_one("#rebuild-verification-section", FormSection).display
            app.query_one("#workspace-rebuild-signature-source", Select).value = "payloads"
            await pilot.pause()
            await _choose_picker_paths(app, pilot, Path("auth-payloads.json"))

            assert app.rebuild_state.auth_text_file is None
            assert app.rebuild_state.auth_payloads_file == Path("auth-payloads.json")
            assert app.rebuild_state.to_rebuild_request().auth_payloads_file == Path(
                "auth-payloads.json"
            )
            assert "Signature payload: auth-payloads.json" in _preview_text(app)

            app.query_one("#workspace-rebuild-signature-source", Select).value = "auto"
            await _wait_for_condition(
                pilot,
                lambda: app.rebuild_state.auth_payloads_file is None,
                "automatic rebuild authentication selection",
            )

            assert app.rebuild_state.auth_text_file is None
            assert app.rebuild_state.auth_payloads_file is None

    asyncio.run(run())


def test_textual_app_edit_replace_recovery_docs_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_ui_source_assessment(monkeypatch)

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("5")
            await pilot.click("#workflow-replace_recovery_docs-source-body-source-load")
            await _choose_picker_paths(app, pilot, Path("README.md"))
            app.query_one("#workspace-replace-freshness", Button).focus()
            await pilot.press("enter")
            unlock = app.query_one("#workflow-replace_recovery_docs-unlock-body")
            await _select_guided_radio(unlock, pilot, "Passphrase")
            unlock.query_one(Input).focus()
            await _type_text(pilot, "secret")
            await pilot.press("enter")
            await pilot.pause()
            destination = app.query_one(
                "#workflow-replace_recovery_docs-output-body-destination-value", Input
            )
            destination.focus()
            await _type_text(pilot, "replacement-docs")
            await pilot.press("enter")
            await pilot.pause()

            assert app.replace_recovery_docs_state.validate_task().ready
            assert app.replace_recovery_docs_state.passphrase == "secret"
            assert app.replace_recovery_docs_state.output_dir == Path("replacement-docs")
            assert app.replace_recovery_docs_state.allow_stale_head
            workspace = _checklist_text(app)
            assert "README.md" in workspace
            assert "Latest loaded version accepted" in workspace
            assert "These scans may not contain the latest backup version" in _preview_text(app)
            quorum = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum", QuorumEditor
            )
            assert quorum.values == (2, 3)
            assert destination.value == "replacement-docs"
            assert "Print options" not in workspace
            assert app.query_one("#workspace-replace-paper", Select).value == "A4"
            assert app.query_one("#workspace-replace-design", Select).value == "sentinel"
            assert "Existing backup files" in _preview_text(app)
            assert "Left unchanged" in _preview_text(app)

    asyncio.run(run())


def test_textual_app_replace_recovery_signing_key_controls_are_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_ui_source_assessment(monkeypatch)
    state = ReplaceRecoveryDocsTaskState(
        source_paths=[Path("backup.pdf")],
        passphrase="secret",
        allow_stale_head=True,
    )
    state.assess_source()

    async def run() -> None:
        app = EthernityApp(replace_recovery_docs_state=state)
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("5")
            await app._select_workbench_step("recovery")
            await pilot.pause()
            assert app.query_one("#replace-signing-section", FormSection).display
            await pilot.pause()

            signing_warning = (
                "No separate signing-key recovery sheets will be created. The replacement "
                "documents remain signed."
            )
            assert not app.query("#replace-signing-key-status")
            assert signing_warning in _preview_text(app)
            assert app.query_one("#replace-signing-notice").display
            assert not app.replace_recovery_docs_state.create_signing_key_recovery

            app.query_one("#workspace-replace-signing-key-select", Select).value = "same"
            await _wait_for_condition(
                pilot,
                lambda: app.replace_recovery_docs_state.create_signing_key_recovery,
                "signing-key recovery selection",
            )

            assert app.replace_recovery_docs_state.create_signing_key_recovery
            assert app.replace_recovery_docs_state.signing_key_recovery_threshold is None
            assert app.replace_recovery_docs_state.signing_key_recovery_count is None
            request = app.replace_recovery_docs_state.to_replacement_recovery_request()
            assert request.create_signing_key_shards
            assert signing_warning not in _preview_text(app)
            assert not app.query_one("#replace-signing-notice").display

            app.query_one("#workspace-replace-signing-key-select", Select).value = "custom"
            await _wait_for_condition(
                pilot,
                lambda: bool(app.screen.query("#edit-field-input")),
                "custom signing-key quorum editor",
            )
            field = app.screen.query_one("#edit-field-input", Input)
            assert not isinstance(field, MaskedInput)
            field.value = ""
            field.focus()
            await _type_text(pilot, "3/5")
            await pilot.press("enter")
            await pilot.pause()

            assert app.replace_recovery_docs_state.signing_key_recovery_threshold == 3
            assert app.replace_recovery_docs_state.signing_key_recovery_count == 5
            args = app.replace_recovery_docs_state.to_replacement_recovery_request()
            assert args.signing_key_shard_threshold == 3
            assert args.signing_key_shard_count == 5
            assert app.query_one("#workspace-replace-signing-key-select", Select).value == "custom"

            app.query_one("#workspace-replace-signing-key-select", Select).value = "off"
            await _wait_for_condition(
                pilot,
                lambda: not app.replace_recovery_docs_state.create_signing_key_recovery,
                "disabled signing-key recovery selection",
            )

            assert not app.replace_recovery_docs_state.create_signing_key_recovery
            assert app.replace_recovery_docs_state.signing_key_recovery_threshold is None
            assert app.replace_recovery_docs_state.signing_key_recovery_count is None
            request = app.replace_recovery_docs_state.to_replacement_recovery_request()
            assert not request.create_signing_key_shards

    asyncio.run(run())


@pytest.mark.portability
def test_textual_app_replace_recovery_passphrase_replacement_count_is_real() -> None:
    async def run() -> None:
        app = EthernityApp(
            replace_recovery_docs_state=ReplaceRecoveryDocsTaskState(
                recovery_payload_files=[Path("recovery-payloads.txt")]
            )
        )
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("5")
            await pilot.pause()

            app.query_one("#workspace-replace-passphrase-select", Select).value = "replace"
            await wait_for_widget(pilot, "#edit-field-input")
            field = app.screen.query_one("#edit-field-input", Input)
            assert not isinstance(field, MaskedInput)
            field.value = ""
            field.focus()
            await _type_text(pilot, "2")
            await pilot.press("enter")
            await pilot.pause()

            state = app.replace_recovery_docs_state
            assert state.create_passphrase_recovery
            assert state.passphrase_replacement_count == 2
            assert state.to_replacement_recovery_request().passphrase_replacement_count == 2
            assert app.query_one("#workspace-replace-passphrase-select", Select).value == "replace"
            replacement = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-passphrase",
                OptionsEditor,
            )
            assert "Sheets to replace: 2 sheets" in str(
                replacement.query_one(".guided-detail", Static).content
            )

    asyncio.run(run())


def test_textual_app_replace_recovery_signing_key_payloads_are_real_picker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_ui_source_assessment(monkeypatch)
    state = ReplaceRecoveryDocsTaskState(
        source_paths=[Path("backup.pdf")],
        passphrase="secret",
        allow_stale_head=True,
    )
    state.assess_source()

    async def run() -> None:
        app = EthernityApp(replace_recovery_docs_state=state)
        async with app.run_test(size=(120, 72)) as pilot:
            await pilot.press("5")
            await app._select_workbench_step("recovery")
            await pilot.pause()
            assert app.query_one("#replace-signing-section", FormSection).display
            app.query_one("#workspace-replace-signing-key-select", Select).value = "replace"
            await pilot.pause()
            count = app.screen.query_one("#edit-field-input", Input)
            count.value = ""
            count.focus()
            await _type_text(pilot, "1")
            await pilot.press("enter")
            await pilot.pause()

            app.query_one("#workspace-replace-signing-key-payloads", Button).focus()
            await pilot.press("enter")
            await _choose_picker_paths(app, pilot, Path("signing-payloads.txt"))

            assert app.replace_recovery_docs_state.signing_key_recovery_payload_files == [
                Path("signing-payloads.txt")
            ]
            args = app.replace_recovery_docs_state.to_replacement_recovery_request()
            assert args.signing_key_shard_payload_files == (Path("signing-payloads.txt"),)
            assert "1 key payload file" in _checklist_text(app)

            assert app.replace_recovery_docs_state.signing_key_replacement_count == 1
            args = app.replace_recovery_docs_state.to_replacement_recovery_request()
            assert args.create_signing_key_shards
            assert args.signing_key_replacement_count == 1
            assert "1 replacement sheet" in _checklist_text(app)

    asyncio.run(run())


def test_textual_app_custom_quorum_updates_do_not_trip_assignment_validation() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            app._apply_backup_recovery("4/5")
            app._apply_replace_recovery_set("4/5")

            assert app.backup_state.shard_threshold == 4
            assert app.backup_state.shard_count == 5
            assert app.replace_recovery_docs_state.recovery_threshold == 4
            assert app.replace_recovery_docs_state.recovery_document_count == 5

            # Task shortcuts must leave the numeric editor before consuming a digit.
            await pilot.press("ctrl+b", "5")
            await pilot.pause()
            assert app.active_task == "replace_recovery_docs"

            quorum = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum",
                QuorumEditor,
            )
            assert quorum.values == (4, 5)
            assert str(quorum.query_one(".guided-summary", Static).content) == (
                "Create 5 sheets; any 4 can restore"
            )
            assert "A custom quorum changes how many sheets you need to restore" in _preview_text(
                app
            )

    asyncio.run(run())


def test_textual_app_quorum_parser_rejects_counts_above_shamir_limit() -> None:
    assert parse_threshold_count("2/255") == (2, 255)
    assert parse_threshold_count("2/256") is None
    assert parse_threshold_count("256/256") is None


@pytest.mark.portability
def test_textual_app_backup_advanced_controls_are_real(tmp_path) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(140, 72)) as pilot:
            await pilot.pause()

            assert not app.backup_state.validate_task().ready
            assert _button_label(app, "#canvas-primary") == "Continue >"

            await pilot.click(app.query_one(WorkbenchSteps).button_for("recovery"))

            assert "harder to scan" in str(
                app.query_one("#workspace-backup-qr-chunk-size", Button).tooltip
            )

            words_select = app.query_one("#workspace-backup-passphrase-words", Select)
            words_select.value = "18"
            await _wait_for_condition(
                pilot, lambda: app.backup_state.passphrase_words == 18, "phrase length selection"
            )

            assert app.backup_state.passphrase_words == 18
            assert app.backup_state.passphrase is None

            await pilot.click("#workspace-backup-passphrase")
            await pilot.pause()
            await _enter_edit_field(app, pilot, "manual secret", plain_input=False)

            assert app.backup_state.passphrase == "manual secret"
            assert app.backup_state.passphrase_words is None

            words_select.value = "24"
            await _wait_for_condition(
                pilot,
                lambda: (
                    app.backup_state.passphrase is None and app.backup_state.passphrase_words == 24
                ),
                "generated phrase to replace the manual phrase",
            )

            assert app.backup_state.passphrase is None
            assert app.backup_state.passphrase_words == 24

            app.query_one("#workspace-backup-signing-key-mode", Select).value = "sharded"
            await click_when_ready(pilot, "#workspace-backup-signing-key-shards")
            await _enter_edit_field(app, pilot, "3/5", plain_input=True)

            assert app.backup_state.signing_key_mode == "sharded"
            assert app.backup_state.signing_key_shard_threshold == 3
            assert app.backup_state.signing_key_shard_count == 5
            assert "5 key sheets; any 3 can recover the key" in _workspace_text(app)

            await app._select_workbench_step("files")
            await pilot.pause()
            await pilot.click("#workspace-backup-base-dir")
            await pilot.pause()
            await _choose_picker_paths(app, pilot, tmp_path)

            assert app.backup_state.base_dir == tmp_path
            assert display_path(tmp_path) in _workspace_text(app)

            await app._select_workbench_step("print")
            await pilot.pause()
            await pilot.click("#workspace-backup-qr-chunk-size")
            await pilot.pause()
            await _enter_edit_field(app, pilot, "384", plain_input=False)

            assert app.backup_state.qr_chunk_size == 384
            assert app.backup_state.to_backup_request().qr_chunk_size == 384
            assert "Warning:" in _static_text(app, "#backup-qr-notice")
            assert "384 bytes" in _workspace_text(app)
            assert "Custom QR density can change page count" in _preview_text(app)

    asyncio.run(run())


@pytest.mark.portability
def test_update_mode_choice_uses_keyboard_and_existing_series_is_read_only() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("3")
            await app._select_workbench_step("files")
            await pilot.pause()
            choice = app.query_one("#workspace-add-files-update-mode", Select)
            assert choice.value == "cumulative"
            choice.focus()
            await wait_for_focus(pilot, choice)
            await pilot.press("enter", "down", "enter")
            await _wait_for_condition(
                pilot,
                lambda: app.add_files_state.update_mode == UpdateMode.INCREMENTAL,
                "incremental update mode selection",
            )
            assert app.add_files_state.to_add_files_request().update_mode == UpdateMode.INCREMENTAL

            app.add_files_state.source_paths = [Path("existing-series.pdf")]
            app.add_files_state.update_mode = None
            request = app.add_files_state.source_assessment_request()
            assert request is not None
            app.add_files_state.store_source_assessment(
                request,
                SourceAssessment(
                    source_kind="scanned_pages",
                    source_label="Backup",
                    source_summary="Loaded",
                    has_updates=True,
                ),
            )
            app.refresh_task_view()
            await pilot.pause()
            assert not app.query_one("#add-files-update-mode-choice").display
            assert app.query_one("#add-files-update-mode-summary").display
            assert app.add_files_state.to_add_files_request().update_mode is None

    asyncio.run(run())


def test_textual_app_add_files_advanced_controls_are_real(tmp_path) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(140, 72)) as pilot:
            await pilot.press("3")
            await pilot.pause()

            assert "harder to scan" in str(
                app.query_one("#workspace-add-files-qr-chunk-size", Button).tooltip
            )

            await app._select_workbench_step("files")
            await pilot.pause()
            base_dir = app.query_one("#workspace-add-files-base-dir", Button)
            base_dir.focus()
            await pilot.wait_for_scheduled_animations()
            assert await pilot.click(base_dir)
            await _choose_picker_paths(app, pilot, tmp_path)

            assert app.add_files_state.base_dir == tmp_path
            assert display_path(tmp_path) in _workspace_text(app)

            await app._select_workbench_step("output")
            await pilot.pause()
            await pilot.click("#workspace-add-files-qr-chunk-size")
            await pilot.pause()
            await _enter_edit_field(app, pilot, "384", plain_input=False)

            assert app.add_files_state.qr_chunk_size == 384
            assert app.add_files_state.to_add_files_request().qr_chunk_size == 384
            assert "384 bytes" in _workspace_text(app)
            assert "Custom QR density can change page count" in _preview_text(app)

            app.query_one("#workspace-add-files-signature-source", Select).value = "payloads"
            await pilot.pause()
            await _choose_picker_paths(app, pilot, Path("auth-payloads.json"))

            assert app.add_files_state.auth_text_file is None
            assert app.add_files_state.auth_payloads_file == Path("auth-payloads.json")
            assert app.add_files_state.to_add_files_request().auth_payloads_file == (
                "auth-payloads.json"
            )
            assert "Signature payload: auth-payloads.json" in _preview_text(app)

            app.query_one("#workspace-add-files-signature-source", Select).value = "auto"
            await _wait_for_condition(
                pilot,
                lambda: app.add_files_state.auth_payloads_file is None,
                "automatic update authentication selection",
            )

            await pilot.click("#workspace-add-files-recovery-sheets")
            await pilot.pause()
            recovery_sheets = app.screen.query_one("#edit-field-input", Input)
            recovery_sheets.value = ""
            recovery_sheets.focus()
            await _type_text(pilot, "3/5")
            await pilot.press("enter")
            await pilot.pause()

            assert app.add_files_state.create_recovery_sheets
            assert app.add_files_state.recovery_threshold == 3
            assert app.add_files_state.recovery_sheet_count == 5
            assert "5 new recovery sheets, 3 needed to restore" in _workspace_text(app)

    asyncio.run(run())


def test_textual_app_edit_kit_output() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("6")
            await app.action_edit_output()
            await _save_picker_name(app, pilot, "kit.pdf")

            assert app.kit_state.output_path.name == "kit.pdf"
            assert "kit.pdf" in _checklist_text(app)

    asyncio.run(run())


def test_textual_app_edit_kit_qr_chunk_size() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("6")
            await pilot.pause()
            app.query_one("#workspace-kit-chunk-size", Button).focus()
            await pilot.press("enter")
            await _type_text(pilot, "512")
            await pilot.press("enter")
            await pilot.pause()

            assert app.kit_state.chunk_size == 512
            assert "512 bytes" in _checklist_text(app)
            assert "512" in _preview_text(app)
            assert "Custom sizing can change page count" in _preview_text(app)

    asyncio.run(run())


def test_textual_app_edit_settings_state(tmp_path) -> None:
    async def run() -> None:
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            Path("src/ethernity/resources/config/config.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        app = EthernityApp(settings_state=SettingsTaskState.from_current(config_path))
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("7")
            app.query_one("#setting-control-render_style", Select).value = "forge"
            await pilot.pause()
            app.query_one("#setting-control-page_size", Select).value = "LETTER"
            await pilot.pause()
            await app.action_edit_output()
            await _save_picker_name(app, pilot, "backup-out")
            app.query_one(SettingsForm).show_group("Advanced")
            await pilot.pause()
            qr_chunk = app.query_one("#setting-control-qr_chunk_size", Input)
            assert isinstance(qr_chunk, MaskedInput)
            qr_chunk.value = ""
            qr_chunk.focus()
            await _type_text(pilot, "1024")
            await pilot.press("enter")

            assert app.settings_state.validate_task().ready
            assert app.settings_state.design == "forge"
            assert app.settings_state.paper_size == "LETTER"
            assert app.settings_state.backup_output_dir is not None
            assert app.settings_state.backup_output_dir.name == "backup-out"
            assert app.settings_state.setting_value("qr_chunk_size") == 1024
            assert config_path.exists()
            saved = SettingsTaskState.from_current(config_path)
            assert saved.design == "forge"
            assert saved.paper_size == "LETTER"
            assert saved.backup_output_dir is not None
            assert saved.backup_output_dir.name == "backup-out"
            assert saved.setting_value("qr_chunk_size") == 1024

    asyncio.run(run())


def test_textual_app_settings_categories_show_advanced_and_config_actions(tmp_path) -> None:
    async def run() -> None:
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            Path("src/ethernity/resources/config/config.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        app = EthernityApp(settings_state=SettingsTaskState.from_current(config_path))
        async with app.run_test(size=(120, 72)) as pilot:
            await pilot.press("7")
            await pilot.pause()

            assert _button_label(app, "#settings-reset-section") == "Reset section"
            assert _button_label(app, "#settings-reset-all") == "Reset all settings"
            assert _button_label(app, "#settings-copy-config") == "Copy path"
            assert _button_label(app, "#settings-open-config") == "Open folder"
            settings_form = app.query_one(SettingsForm)
            assert settings_form.active_group == "Printing"
            save_status = app.query_one("#settings-save-status", Static)
            assert save_status.display
            assert save_status.region.height == 3
            assert str(save_status.content) == "Saved"
            assert settings_form.query_one("#settings-heading").region.y < save_status.region.y
            assert save_status.region.x > settings_form.region.x + settings_form.region.width // 2

            settings_form.show_group("Config file")
            await pilot.pause()
            app.query_one("#settings-copy-config", Button).focus()
            await _wait_for_condition(
                pilot,
                lambda: (
                    settings_form.active_group == "Config file"
                    and app.query_one("#settings-copy-config", Button).region.width > 0
                    and app.query_one("#settings-open-config", Button).region.width > 0
                ),
                "config settings pane layout",
            )

            assert settings_form.active_group == "Config file"
            _assert_buttons_are_spaced(app.query_one("#setting-row-config .inline-action-group"))
            copy_path = app.query_one("#settings-copy-config", Button).region
            open_folder = app.query_one("#settings-open-config", Button).region
            assert copy_path.x + copy_path.width < open_folder.x
            assert _static_text(app, "#settings-save-status") == "Saved"
            assert (
                _static_text(app, "#settings-recovery-summary")
                == "3 recovery sheets; any 2 required"
            )
            assert not app.query_one("#setting-help-backup_signing_key_mode").display
            signing_key_options = app.query_one(
                "#setting-control-backup_signing_key_mode",
                Select,
            )._options
            assert ("Use built-in default (Embedded)", "__none__") in signing_key_options
            compression_options = app.query_one(
                "#setting-control-backup_payload_codec",
                Select,
            )._options
            qr_encoding_options = app.query_one(
                "#setting-control-backup_qr_payload_codec",
                Select,
            )._options
            assert ("Automatic (recommended)", "auto") in compression_options
            assert ("Raw (recommended)", "raw") in qr_encoding_options

            app.query_one(SettingsForm).show_group("Advanced")
            await pilot.pause()
            app.query_one("#setting-control-qr_chunk_size", Input).focus()
            await _wait_for_condition(
                pilot,
                lambda: "More bytes" in _static_text(app, "#settings-focus-help"),
                "advanced settings focus help",
            )

            assert settings_form.active_group == "Advanced"
            assert app.query_one("#setting-row-qr_chunk_size").display
            assert not app.query_one("#setting-help-qr_chunk_size").display
            assert _button_label(app, "#settings-reset-section") == "Reset section"
            assert "More bytes can reduce page count" in _static_text(app, "#settings-focus-help")

    asyncio.run(run())


def test_textual_app_settings_middle_truncates_long_config_path(tmp_path) -> None:
    async def run() -> None:
        config_dir = tmp_path / "one" / "two" / "three" / "four" / "five" / "six"
        config_dir.mkdir(parents=True)
        config_path = config_dir / "config.toml"
        config_path.write_text(
            Path("src/ethernity/resources/config/config.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        app = EthernityApp(settings_state=SettingsTaskState.from_current(config_path))
        async with app.run_test(size=(96, 40)) as pilot:
            await pilot.press("7")
            await pilot.pause()

            rendered_path = _static_text(app, "#setting-value-config")

            assert "..." in rendered_path
            assert rendered_path.endswith(str(Path("six/config.toml")))
            assert rendered_path != str(config_path)
            assert len(rendered_path) <= 56

    asyncio.run(run())


def test_textual_app_workflow_path_fields_middle_truncate_long_paths(tmp_path) -> None:
    long_root = (
        tmp_path
        / "very-long-project-folder"
        / "nested-backup-documents"
        / "paper-recovery-session"
        / "final-destination"
    )
    backup_output = long_root / "backup-output-folder"
    restore_output = long_root / "restored-files-folder"
    kit_output = long_root / "offline-recovery-kit.pdf"

    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[long_root / "secrets.txt"],
                base_dir=long_root,
                output_dir=backup_output,
            ),
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
                output_path=restore_output,
            ),
            kit_state=PrintKitTaskState(output_path=kit_output),
        )
        async with app.run_test(size=(96, 40)) as pilot:
            backup_output_value = _static_text(app, "#backup-output-value")
            backup_base_dir = _static_text(app, "#backup-base-dir-value")
            assert "..." in backup_output_value
            assert "..." in backup_base_dir
            assert str(backup_output) not in backup_output_value
            assert str(long_root) not in backup_base_dir
            assert backup_output_value.endswith(str(Path("backup-output-folder") / "backup-<id>"))
            assert backup_base_dir.endswith("final-destination")

            await pilot.press("2")
            await pilot.pause()

            restore_value = app.query_one("#workflow-restore-destination-body-value", Input)
            assert restore_value.value == str(restore_output)

            await pilot.press("6")
            await pilot.pause()

            kit_value = _static_text(app, "#kit-output-value")
            assert "..." in kit_value
            assert str(kit_output) not in kit_value
            assert kit_value.endswith("offline-recovery-kit.pdf")

    asyncio.run(run())


def test_textual_app_settings_restores_section_and_all_defaults(tmp_path) -> None:
    async def run() -> None:
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            Path("src/ethernity/resources/config/config.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        app = EthernityApp(settings_state=SettingsTaskState.from_current(config_path))
        async with app.run_test(size=(120, 72)) as pilot:
            await pilot.press("7")

            app.query_one("#setting-control-render_style", Select).value = "forge"
            await pilot.pause()
            app.query_one("#setting-control-page_size", Select).value = "LETTER"
            await _wait_for_condition(
                pilot,
                lambda: (
                    app.settings_state.design == "forge"
                    and app.settings_state.paper_size == "LETTER"
                ),
                "printing settings to be applied",
            )

            assert app.settings_state.design == "forge"
            assert app.settings_state.paper_size == "LETTER"
            assert _static_text(app, "#setting-marker-render_style") == "Custom"
            assert _static_text(app, "#setting-marker-page_size") == "Custom"

            app.query_one("#settings-reset-section", Button).focus()
            await pilot.press("enter")
            await pilot.pause()

            assert app.settings_state.design == "sentinel"
            assert app.settings_state.paper_size == "A4"
            assert _static_text(app, "#setting-marker-render_style") == ""
            assert _static_text(app, "#setting-marker-page_size") == ""

            app.query_one("#setting-control-render_style", Select).value = "forge"
            await pilot.pause()
            app.query_one(SettingsForm).show_group("Advanced")
            await pilot.pause()
            qr_chunk = app.query_one("#setting-control-qr_chunk_size", Input)
            qr_chunk.value = ""
            qr_chunk.focus()
            await _type_text(pilot, "1024")
            await pilot.press("enter")
            await pilot.pause()

            assert app.settings_state.design == "forge"
            assert app.settings_state.setting_value("qr_chunk_size") == 1024
            assert _static_text(app, "#setting-marker-qr_chunk_size") == "Custom"
            assert "A custom QR size changes page count and scan reliability" in _preview_text(app)

            await _open_reset_all(app, pilot)

            assert isinstance(app.screen, ConfirmActionScreen)
            assert app.settings_state.design == "forge"
            assert app.settings_state.setting_value("qr_chunk_size") == 1024
            await pilot.click("#confirm-action-cancel")
            await pilot.pause()

            await _open_reset_all(app, pilot)
            assert isinstance(app.screen, ConfirmActionScreen)
            await pilot.click("#confirm-action-confirm")
            await pilot.pause()

            _assert_default_settings_saved(app, config_path)

    asyncio.run(run())


def _assert_default_settings_saved(app: EthernityApp, config_path: Path) -> None:
    assert app.settings_state.design == "sentinel"
    assert app.settings_state.setting_value("qr_chunk_size") == 512
    assert _static_text(app, "#setting-marker-render_style") == ""
    assert _static_text(app, "#setting-marker-qr_chunk_size") == ""
    assert app.settings_state.validate_task().ready
    saved = SettingsTaskState.from_current(config_path)
    assert saved.design == "sentinel"
    assert saved.setting_value("qr_chunk_size") == 512


def test_textual_app_settings_restores_focused_section_from_command_action(tmp_path) -> None:
    async def run() -> None:
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            Path("src/ethernity/resources/config/config.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        settings = SettingsTaskState.from_current(config_path)
        settings.set_setting_value("qr_chunk_size", 1024)
        app = EthernityApp(settings_state=settings)
        async with app.run_test(size=(120, 72)) as pilot:
            await pilot.press("7")
            await pilot.pause()

            app.query_one("#setting-control-render_style", Select).value = "forge"
            await pilot.pause()
            app.query_one("#setting-control-page_size", Select).value = "LETTER"
            await pilot.pause()

            assert app.settings_state.design == "forge"
            assert app.settings_state.paper_size == "LETTER"
            assert app.settings_state.setting_value("qr_chunk_size") == 1024

            app.query_one("#setting-control-render_style", Select).focus()
            await pilot.pause()
            command = next(
                command
                for command in app._workflow_system_commands()
                if command.title == "Reset current section"
            )
            command.callback()
            await pilot.pause()

            assert app.settings_state.design == "sentinel"
            assert app.settings_state.paper_size == "A4"
            assert app.settings_state.setting_value("qr_chunk_size") == 1024
            assert _static_text(app, "#setting-marker-render_style") == ""
            assert _static_text(app, "#setting-marker-qr_chunk_size") == "Custom"

    asyncio.run(run())


def test_textual_app_edit_restore_fields_updates_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_ui_source_assessment(monkeypatch)

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("2")
            await app.action_edit_primary()
            await _choose_picker_paths(app, pilot, Path("README.md"))
            await app.action_edit_passphrase()
            await _type_text(pilot, "demo passphrase")
            await pilot.press("enter")
            await pilot.pause()
            await app.action_edit_output()
            await _save_picker_name(app, pilot, "recovered")

            assert app.restore_state.validate_task().ready
            sections = _checklist_text(app)
            preview = _preview_text(app)
            assert "README.md" in sections
            assert "Passphrase" in preview

    asyncio.run(run())


def test_textual_app_edit_and_clear_backup_state() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await app.action_edit_primary()
            await _choose_picker_paths(app, pilot, Path("README.md"))
            await app.action_edit_output()
            await _save_picker_name(app, pilot, "backup-out")

            assert app.backup_state.validate_task().ready
            workspace = _checklist_text(app)
            assert "README.md" in workspace
            assert "backup-out" in workspace

            await pilot.press("c")
            await pilot.pause()

            assert app.backup_state.validate_task().ready
            assert "README.md" in _checklist_text(app)

            app.action_clear_task()
            await pilot.pause()

            assert not app.backup_state.validate_task().ready
            assert "No files selected" in _checklist_text(app)

    asyncio.run(run())


def test_textual_app_file_sections_can_clear_selected_paths() -> None:
    async def run() -> None:
        backup_app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("README.md")],
                output_dir=Path("backup-out"),
            )
        )
        async with backup_app.run_test(size=(120, 32)) as pilot:
            assert "README.md" in _checklist_text(backup_app)

            assert not backup_app.query_one("#backup-files-panel", Collapsible).collapsed
            await pilot.click("#workspace-backup-clear-files")
            await pilot.pause()

            assert backup_app.backup_state.input_paths == []
            assert backup_app.backup_state.input_dirs == []
            assert "No files selected" in _checklist_text(backup_app)

        add_app = EthernityApp(
            add_files_state=AddFilesTaskState(
                source_paths=[Path("docs")],
                output_dir=Path("update-out"),
                allow_stale_head=True,
                input_paths=[Path("new.txt")],
                passphrase="secret",
            )
        )
        async with add_app.run_test(size=(120, 32)) as pilot:
            await pilot.press("3")
            await pilot.pause()
            assert "new.txt" in _checklist_text(add_app)
            assert _button_label(add_app, "#workspace-add-files-clear-files") == "Clear all"

            await pilot.click(add_app.query_one(WorkbenchSteps).button_for("files"))
            add_app.query_one("#workspace-add-files-clear-files", Button).focus()
            await pilot.press("enter")
            await pilot.pause()

            assert add_app.add_files_state.input_paths == []
            assert add_app.add_files_state.input_dirs == []
            assert "No files or folders selected" in _checklist_text(add_app)

    asyncio.run(run())


def test_textual_app_selected_file_sections_show_size_and_base_folder(tmp_path) -> None:
    async def run() -> None:
        selected_file = tmp_path / "secret.txt"
        selected_file.write_text("twelve bytes", encoding="utf-8")

        backup_app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[selected_file],
                base_dir=tmp_path,
                output_dir=tmp_path / "backup-out",
            )
        )
        async with backup_app.run_test(size=(120, 32)) as pilot:
            await _wait_for_condition(
                pilot,
                lambda: backup_app.backup_state.current_estimate() is not None,
                "backup file size estimate",
            )
            status = _static_text(backup_app, "#backup-files-value")

            assert "1 file" in status
            assert "12 bytes" in status
            assert _static_text(backup_app, "#backup-base-dir-value") == display_path(tmp_path)

        add_app = EthernityApp(
            add_files_state=AddFilesTaskState(
                source_paths=[tmp_path / "docs"],
                output_dir=tmp_path / "update-out",
                allow_stale_head=True,
                input_paths=[selected_file],
                base_dir=tmp_path,
                passphrase="secret",
            )
        )
        async with add_app.run_test(size=(120, 32)) as pilot:
            await pilot.press("3")
            await pilot.pause()
            editor = add_app.query_one(
                "#workflow-add_files-files-body",
                PathSelectionEditor,
            )
            status = str(editor.query_one(".guided-summary", Static).content)

            assert status == "1 file"
            assert "12 bytes" in _preview_text(add_app)
            assert f"base folder: {display_path(tmp_path)}" in _preview_text(add_app)

    asyncio.run(run())


def test_textual_app_blocked_review_focuses_first_requirement() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")
            await pilot.pause()

            assert not list(app.screen.query("#review-modal"))
            assert app.screen.focused is app.query_one("#workspace-backup-files", Button)
            assert "Next required action" in _preview_text(app)
            assert "Choose at least one file or folder" in _preview_text(app)

    asyncio.run(run())


@pytest.mark.portability
def test_textual_app_shows_progress_screen_while_task_runs(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    def fake_execute(self: BackupTaskState) -> TaskExecutionResult:
        started.set()
        assert release.wait(timeout=30), "Test did not release the backup worker."
        return TaskExecutionResult(
            status="succeeded",
            message="Slow backup complete.",
            output_paths=(Path("backup-out/main.pdf"),),
        )

    monkeypatch.setattr(BackupTaskState, "execute", fake_execute)

    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            assert not list(app.query("#canvas-loading"))
            await pilot.press("ctrl+r")
            await pilot.pause()
            await click_when_ready(pilot, "#review-execute")

            try:
                await _wait_for_condition(pilot, started.is_set, "worker to start")
                destination = await wait_for_widget(pilot, "#progress-destination")
                expected = str(Path("backup-out") / "backup-<id>")
                await _wait_for_condition(
                    pilot,
                    lambda: expected in str(cast(Static, destination).content),
                    "progress destination to populate",
                )

                assert started.is_set()
                assert app.running_task == "backup"
                assert isinstance(app.screen, TaskProgressScreen)
                assert app.screen.query_one("#operation-bar", ProgressBar).total is None
                assert expected in _static_text(app, "#progress-destination")
                assert not app.screen.query_one("#progress-cancel", Button).disabled
            finally:
                release.set()
            await wait_for_widget(pilot, "#result-close")

            assert app.running_task is None
            assert "Slow backup complete" in _result_text(app)
            _assert_success_result_modal_layout(app)
            assert not any(isinstance(screen, TaskProgressScreen) for screen in app.screen_stack)

    asyncio.run(run())


def test_textual_app_review_can_execute_ready_backup(monkeypatch) -> None:
    calls: list[BackupTaskState] = []
    copied_paths: list[str] = []

    def fake_execute(self: BackupTaskState) -> TaskExecutionResult:
        calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Fake backup complete.",
            output_paths=(Path("backup-out/main.pdf"),),
        )

    def fake_copy_to_clipboard(self: EthernityApp, text: str) -> None:
        copied_paths.append(text)

    monkeypatch.setattr(BackupTaskState, "execute", fake_execute)
    monkeypatch.setattr(EthernityApp, "copy_to_clipboard", fake_copy_to_clipboard)

    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")
            await pilot.pause()

            assert _static_text(app, "#review-title") == "Review backup"
            assert not list(app.screen.query("#review-status"))
            assert not list(app.screen.query("#review-summary"))
            review_text = _review_text(app)
            assert "Confirm this action" not in review_text
            assert "Create backup documents in backup-out" in review_text
            assert _button_label(app, "#review-execute") == "Create backup"
            assert "Reads" in review_text
            assert "secrets.txt" in review_text
            assert "The signing key will be embedded in the backup documents." in review_text
            assert "Store recovery sheets separately from encrypted backup documents." in (
                review_text
            )
            assert str(Path("backup-out").absolute()) in review_text
            assert "A new backup-<id> folder will be created inside the destination." in review_text
            assert "Existing backups stay unchanged." in review_text

            await click_when_ready(pilot, "#review-execute")
            await _wait_for_condition(pilot, lambda: bool(calls), "execution to start")

            assert [str(path) for path in calls[0].input_paths] == ["secrets.txt"]
            await wait_for_widget(pilot, "#result-close")

            result_text = _result_text(app)
            assert "Fake backup complete" in result_text
            _assert_success_result_modal_layout(app)
            assert "Destination\nbackup-out" in result_text
            assert "Files\n1 PDF" in result_text
            assert "\nmain.pdf" in result_text
            assert "Print every PDF at actual size." in result_text
            assert "Create and store a recovery kit if you do not already have one." not in (
                result_text
            )
            assert _button_label(app, "#result-copy-paths") == "Copy paths"
            assert _button_label(app, "#result-open-folder") == "Open folder"
            await pilot.click("#result-copy-paths")
            await pilot.pause()

            assert copied_paths == [str(Path("backup-out/main.pdf"))]

            await pilot.click("#result-close")
            await pilot.pause()
            assert "Fake backup complete." in _preview_text(app)

    asyncio.run(run())


def test_textual_app_backup_review_shows_risky_recovery_warning() -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
                recovery_method="single_phrase",
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")
            await pilot.pause()

            review_text = _review_text(app)
            assert "Warning" in review_text
            assert "One recovery phrase is a single secret" in review_text
            assert "One recovery phrase" in review_text
            assert not app.screen.query_one("#review-execute", Button).disabled

    asyncio.run(run())


def test_textual_app_backup_review_shows_custom_qr_warning() -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
                qr_chunk_size=384,
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")
            await pilot.pause()

            review_text = _review_text(app)
            assert "Warning" in review_text
            assert "Custom QR density can change page count" in review_text
            assert "QR density" in review_text
            assert "384 bytes" in review_text
            assert not app.screen.query_one("#review-execute", Button).disabled

    asyncio.run(run())


def test_textual_app_review_can_execute_print_kit(monkeypatch) -> None:
    calls: list[PrintKitTaskState] = []

    def fake_execute(self: PrintKitTaskState) -> TaskExecutionResult:
        calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Fake kit complete.",
            output_paths=(Path("kit.pdf"),),
        )

    monkeypatch.setattr(PrintKitTaskState, "execute", fake_execute)

    async def run() -> None:
        app = EthernityApp(kit_state=PrintKitTaskState(output_path=Path("kit.pdf")))
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("6")
            await pilot.pause()
            assert "kit.pdf (current folder)" in _checklist_text(app)

            await pilot.press("ctrl+r")
            await pilot.pause()

            assert not list(app.screen.query("#review-status"))
            assert not list(app.screen.query("#review-summary"))
            review_text = _review_text(app)
            assert "Confirm this action" not in review_text
            assert "Create offline recovery kit PDF at kit.pdf (current folder)" in review_text
            assert _button_label(app, "#review-execute") == "Create PDF"
            assert f"Destination\n{Path('kit.pdf').absolute()}" in review_text
            assert "No user files are read before this action runs." not in review_text
            assert (
                "Ethernity will create the PDF at the selected path. Its parent folder must be "
                "writable."
            ) in review_text
            assert "This offline recovery kit cannot authenticate" in review_text

            await click_when_ready(pilot, "#review-execute")
            await _wait_for_condition(pilot, lambda: bool(calls), "execution to start")

            assert str(calls[0].output_path) == "kit.pdf"
            await wait_for_widget(pilot, "#result-close")

            result_text = _result_text(app)
            assert "Fake kit complete" in result_text
            _assert_success_result_modal_layout(app)
            assert "Files\n1 PDF" in result_text
            assert "kit.pdf" in result_text
            assert "Print the PDF at actual size." in result_text
            assert _button_label(app, "#result-open-folder") == "Open folder"
            await pilot.click("#result-close")
            await pilot.pause()
            assert "Fake kit complete." in _preview_text(app)

    asyncio.run(run())


def test_textual_app_print_kit_review_shows_custom_qr_warning() -> None:
    async def run() -> None:
        app = EthernityApp(kit_state=PrintKitTaskState(output_path=Path("kit.pdf"), chunk_size=512))
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("6")
            await pilot.press("ctrl+r")
            await pilot.pause()

            review_text = _review_text(app)
            assert "Warning" in review_text
            assert "Custom sizing can change page count and make codes harder to scan" in (
                review_text
            )
            assert "QR sizing" in review_text
            assert not app.screen.query_one("#review-execute", Button).disabled

    asyncio.run(run())


def test_textual_app_review_shows_new_backup_inside_existing_parent(tmp_path) -> None:
    async def run() -> None:
        output_dir = tmp_path / "backup-out"
        output_dir.mkdir()
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=output_dir,
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            assert not app.query_one("#backup-destination-status").display
            assert "backup-<id>" in _static_text(app, "#backup-output-value")
            assert "Selected output folder already exists" not in _preview_text(app)

            await pilot.press("ctrl+r")
            await pilot.pause()

            review_text = _review_text(app)
            assert str(output_dir / "backup-<id>") in review_text
            assert "Existing destination:" not in review_text
            assert "may be replaced" not in review_text
            assert "Existing backups stay unchanged" in review_text

    asyncio.run(run())


def test_textual_app_print_kit_warns_before_replacing_existing_pdf(tmp_path) -> None:
    async def run() -> None:
        output_path = tmp_path / "kit.pdf"
        output_path.write_text("existing", encoding="utf-8")
        app = EthernityApp(kit_state=PrintKitTaskState(output_path=output_path))
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("6")
            await pilot.pause()

            assert "Warning: This PDF exists. Creating the kit will replace it." in _static_text(
                app, "#kit-output-notice"
            )
            assert "Selected PDF file already exists" in _preview_text(app)

            await pilot.press("ctrl+r")
            await pilot.pause()

            review_text = _review_text(app)
            assert "Warning" in review_text
            assert "Selected PDF file already exists" in review_text
            assert str(output_path) in review_text
            assert "Existing files at the destination may be replaced." in review_text
            assert not app.screen.query_one("#review-execute", Button).disabled

    asyncio.run(run())


def test_write_workflows_apply_their_destination_policy(tmp_path) -> None:
    backup_output = tmp_path / "backup-out"
    rebuild_output = tmp_path / "rebuilt"
    replacement_output = tmp_path / "replacement-docs"
    kit_output = tmp_path / "kit.pdf"
    for output_dir in (backup_output, rebuild_output, replacement_output):
        output_dir.mkdir()
    kit_output.write_text("existing", encoding="utf-8")

    states = (
        (
            BackupTaskState(input_paths=[Path("secrets.txt")], output_dir=backup_output),
            "ready",
            None,
        ),
        (
            RebuildTaskState(
                backup_folder=Path("docs"),
                passphrase="secret",
                allow_stale_head=True,
                output_dir=rebuild_output,
            ),
            "ready",
            None,
        ),
        (
            ReplaceRecoveryDocsTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
                allow_stale_head=True,
                output_dir=replacement_output,
            ),
            "blocked",
            None,
        ),
        (
            PrintKitTaskState(output_path=kit_output),
            "warning",
            "Selected PDF file already exists",
        ),
    )

    for state, expected_status, warning_text in states:
        output_section = next(
            section for section in state.validate_task().sections if section.key == "output"
        )
        assert output_section.status == expected_status
        output_warnings = [
            warning for warning in state.preview().warnings if warning.section == "output"
        ]
        if warning_text is None:
            assert not output_warnings
        else:
            assert "Existing" in output_section.summary
            assert any(warning_text in warning.message for warning in output_warnings)


def test_textual_app_restore_review_shows_destination_conflict_safety(tmp_path) -> None:
    async def run() -> None:
        restore_dir = tmp_path / "recovered"
        restore_dir.mkdir()
        (restore_dir / "existing.txt").write_text("keep me")
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
                output_path=restore_dir,
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("2")
            await pilot.pause()

            assert app.query_one("#workflow-restore-destination-body-value", Input).value == str(
                restore_dir
            )
            assert (
                "The restore folder contains files or folders; restored files with matching "
                "names may be replaced." in _preview_text(app)
            )

            await pilot.press("ctrl+r")
            await pilot.pause()

            review_text = _review_text(app)
            assert f"Destination\n{restore_dir}" in review_text
            assert (
                "The restore folder contains files or folders; restored files with matching "
                "names may be replaced." in review_text
            )

    asyncio.run(run())


def test_textual_app_review_cancel_returns_without_losing_inputs() -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")
            await pilot.pause()

            assert not list(app.screen.query("#review-status"))

            await pilot.click("#review-close")
            await pilot.pause()

            assert not list(app.screen.query("#review-modal"))
            assert [str(path) for path in app.backup_state.input_paths] == ["secrets.txt"]
            assert app.backup_state.output_dir == Path("backup-out")
            assert _button_label(app, "#canvas-primary") == "Continue >"

    asyncio.run(run())


def test_textual_app_review_can_execute_ready_restore(monkeypatch) -> None:
    calls: list[RestoreTaskState] = []

    def fake_execute(self: RestoreTaskState) -> TaskExecutionResult:
        calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Fake restore complete.",
            output_paths=(Path("recovered/secrets.txt"), Path("recovered/notes.txt")),
        )

    monkeypatch.setattr(RestoreTaskState, "execute", fake_execute)

    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
                output_path=Path("recovered"),
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("2")
            await pilot.press("ctrl+r")
            await pilot.pause()

            review_text = _review_text(app)
            assert "Recover files into recovered" in review_text
            assert "Backup source" in review_text
            assert "1 scanned page" in review_text
            assert "scan.pdf" in review_text
            assert "Signature\nTrusted signature required" in review_text
            assert "Signature check: Trusted signatures required" in review_text
            assert "Verification source: Loaded backup" in review_text
            assert "Unlock: Passphrase" in review_text
            assert _button_label(app, "#review-execute") == "Restore files"
            assert "The restore folder does not exist and will be created." in review_text

            await click_when_ready(pilot, "#review-execute")
            await _wait_for_condition(pilot, lambda: bool(calls), "execution to start")

            assert calls[0].output_path == Path("recovered")
            await wait_for_widget(pilot, "#result-close")

            result_text = _result_text(app)
            assert "Fake restore complete" in result_text
            _assert_success_result_modal_layout(app)
            assert "Destination\nrecovered" in result_text
            assert "2 restored paths" in result_text
            assert "\nsecrets.txt\nnotes.txt" in result_text
            assert "Check the restored files" in result_text
            assert "Compare same-name files in the destination" in result_text

    asyncio.run(run())


def test_textual_app_rebuild_review_shows_stale_source_warning() -> None:
    async def run() -> None:
        app = EthernityApp(
            rebuild_state=RebuildTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
                allow_stale_head=True,
                output_dir=Path("rebuilt"),
            )
        )
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("4")
            await pilot.press("ctrl+r")
            await pilot.pause()

            review_text = _review_text(app)
            assert "Warning" in review_text
            assert "The loaded documents may omit a newer backup version" in review_text
            assert "Source version\nLatest loaded version accepted" in review_text
            assert not app.screen.query_one("#review-execute", Button).disabled

    asyncio.run(run())


def test_textual_app_review_can_execute_maintenance_workflows(monkeypatch) -> None:
    add_calls: list[AddFilesTaskState] = []
    rebuild_calls: list[RebuildTaskState] = []
    replace_calls: list[ReplaceRecoveryDocsTaskState] = []

    def fake_add_files_execute(self: AddFilesTaskState) -> TaskExecutionResult:
        add_calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Fake update complete.",
            output_paths=(
                Path("update-out/update.pdf"),
                Path("update-out/update-recovery.pdf"),
            ),
        )

    def fake_rebuild_execute(self: RebuildTaskState) -> TaskExecutionResult:
        rebuild_calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Fake rebuild complete.",
            output_paths=(Path("rebuilt/main.pdf"), Path("rebuilt/recovery.pdf")),
        )

    def fake_replace_execute(self: ReplaceRecoveryDocsTaskState) -> TaskExecutionResult:
        replace_calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Fake replacement complete.",
            output_paths=(
                Path("replacement-docs/recovery.pdf"),
                Path("replacement-docs/recovery-sheet-01.pdf"),
            ),
        )

    monkeypatch.setattr(AddFilesTaskState, "execute", fake_add_files_execute)
    monkeypatch.setattr(
        AddFilesTaskState,
        "prepare_review",
        lambda _self, *, force=False: None,
    )
    monkeypatch.setattr(RebuildTaskState, "execute", fake_rebuild_execute)
    monkeypatch.setattr(ReplaceRecoveryDocsTaskState, "execute", fake_replace_execute)

    async def run() -> None:
        await _exercise_add_files_review()

        await _exercise_rebuild_review()

        await _exercise_replacement_review()

    asyncio.run(run())


async def _exercise_add_files_review() -> None:
    add_app = EthernityApp(
        add_files_state=AddFilesTaskState(
            source_paths=[Path("docs")],
            output_dir=Path("update-out"),
            allow_stale_head=True,
            input_paths=[Path("new.txt")],
            passphrase="secret",
        )
    )
    async with add_app.run_test(size=(120, 32)) as pilot:
        await pilot.press("3")
        await pilot.press("ctrl+r")
        await pilot.pause()

        review_text = _review_text(add_app)
        assert "Add files to update-out" in review_text
        assert "Changes" in review_text
        assert "1 file, replacing matching paths" in review_text
        assert "new.txt" in review_text
        assert "Source version\nNewest loaded version accepted" in review_text
        assert "New update documents are written to the selected output folder" in review_text
        assert "Recovery sheets\nNo new recovery sheets" in review_text
        assert _button_label(add_app, "#review-execute") == "Create update"

        await click_when_ready(pilot, "#review-execute")
        await wait_for_widget(pilot, "#result-close")

        result_text = _result_text(add_app)
        assert "Fake update complete" in result_text
        _assert_success_result_modal_layout(add_app)
        assert "Destination\nupdate-out" in result_text
        assert "Files\n2 PDFs" in result_text
        assert "\nupdate.pdf\nupdate-recovery.pdf" in result_text
        assert "Print every new PDF at actual size." in result_text


async def _exercise_rebuild_review() -> None:
    rebuild_app = EthernityApp(
        rebuild_state=RebuildTaskState(
            backup_folder=Path("docs"),
            passphrase="secret",
            allow_stale_head=True,
            output_dir=Path("rebuilt"),
        )
    )
    async with rebuild_app.run_test(size=(120, 32)) as pilot:
        await pilot.press("4")
        await pilot.press("ctrl+r")
        await pilot.pause()

        review_text = _review_text(rebuild_app)
        assert "Rebuild backup into rebuilt" in review_text
        assert "docs" in review_text
        assert "Source version\nLatest loaded version accepted" in review_text
        assert "Verification source: Loaded backup" in review_text
        assert "A new backup-<id> folder will be created inside the destination." in (review_text)
        assert "The rebuilt backup gets a new set of recovery sheets" in review_text
        assert "Existing backups stay unchanged." in review_text
        assert _button_label(rebuild_app, "#review-execute") == "Rebuild backup"

        await click_when_ready(pilot, "#review-execute")
        await wait_for_widget(pilot, "#result-close")

        result_text = _result_text(rebuild_app)
        assert "Fake rebuild complete" in result_text
        _assert_success_result_modal_layout(rebuild_app)
        assert "Destination\nrebuilt" in result_text
        assert "Files\n2 PDFs" in result_text
        assert "\nmain.pdf" in result_text
        assert "Store the sheets with the matching backup version." in result_text


async def _exercise_replacement_review() -> None:
    replace_app = EthernityApp(
        replace_recovery_docs_state=ReplaceRecoveryDocsTaskState(
            source_paths=[Path("scan.pdf")],
            passphrase="secret",
            allow_stale_head=True,
            output_dir=Path("replacement-docs"),
            recovery_threshold=4,
            recovery_document_count=5,
        )
    )
    async with replace_app.run_test(size=(120, 32)) as pilot:
        await pilot.press("5")
        await pilot.press("ctrl+r")
        await pilot.pause()

        review_text = _review_text(replace_app)
        assert "Create replacement recovery sheets in replacement-docs" in review_text
        assert "Warnings" in review_text
        assert "scan.pdf" in review_text
        assert "Source\n1 document input" in review_text
        assert "Ethernity will create a new folder and write the replacement PDFs" in review_text
        assert "The selected output path must not already exist." in review_text
        assert "These scans may not contain the latest backup version" in review_text
        assert "A custom quorum changes how many sheets you need" in review_text
        assert "Passphrase recovery: 5 sheets; any 4 can restore" in review_text
        assert (
            "The new recovery sheets unlock the original backup and any intact version "
            "of its update chain."
        ) in review_text
        assert "Test the new recovery sheets before retiring old sheets." in review_text
        assert "Existing sheets remain valid while the credentials stay unchanged." in (review_text)
        assert (
            "No separate signing-key recovery sheets will be created. The replacement "
            "documents remain signed."
        ) in review_text
        assert "Existing backup files: Left unchanged" in review_text
        assert _button_label(replace_app, "#review-execute") == ("Create replacement sheets")

        await click_when_ready(pilot, "#review-execute")
        await wait_for_widget(pilot, "#result-close")

        result_text = _result_text(replace_app)
        assert "Fake replacement complete" in result_text
        _assert_success_result_modal_layout(replace_app)
        assert "Destination\nreplacement-docs" in result_text
        assert "Files\n2 PDFs" in result_text
        assert "Print every replacement sheet at actual size." in result_text
        assert "Store the new sheets before retiring the old set." in result_text


def test_textual_app_execution_failure_shows_result_screen(monkeypatch) -> None:
    def fake_execute(self: BackupTaskState) -> TaskExecutionResult:
        events.emit_phase(phase="save", label="Saving output")
        raise RuntimeError("Printer path is not writable.")

    monkeypatch.setattr(BackupTaskState, "execute", fake_execute)

    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")
            await pilot.pause()
            await click_when_ready(pilot, "#review-execute")
            await wait_for_widget(pilot, "#result-close")

            result_text = _result_text(app)
            assert "Backup failed" in result_text
            assert "Printer path is not writable." in result_text
            assert not list(app.screen.query(MarkdownViewer))
            assert "Check destination" in result_text
            assert "Make sure the destination is writable" in result_text
            assert "Reviewed destination: backup-out" in result_text
            assert app.screen.query_one("#result-details-panel", Collapsible).collapsed
            assert app.screen.query_one("#result-log", RichLog)

            app.screen.query_one("#result-details-panel", Collapsible).focus()
            await pilot.press("enter")
            await pilot.pause()

            assert not app.screen.query_one("#result-details-panel", Collapsible).collapsed
            assert "RuntimeError: Printer path is not writable." in _result_text(app)
            assert _button_label(app, "#result-return") == "Edit destination"

            await click_when_ready(pilot, "#result-return")
            await wait_for_focus(pilot, app.query_one("#workspace-backup-output", Button))

            assert not list(app.screen.query("#result-modal"))
            assert not list(app.screen.query("#review-modal"))
            assert app.active_task == "backup"
            assert app.screen.focused is app.query_one("#workspace-backup-output", Button)

    asyncio.run(run())


def _assert_absent_controls(app: EthernityApp, selectors: tuple[str, ...]) -> None:
    for selector in selectors:
        assert not app.screen.query(selector), selector


async def _enter_edit_field(
    app: EthernityApp, pilot: Pilot, value: str, *, plain_input: bool = False
) -> None:
    await wait_for_widget(pilot, "#edit-field-input")
    editor = app.screen
    field = editor.query_one("#edit-field-input", Input)
    if plain_input:
        assert not isinstance(field, MaskedInput)
    field.value = ""
    field.focus()
    await _type_text(pilot, value)
    await pilot.press("enter")
    await _wait_for_condition(pilot, lambda: app.screen is not editor, "field editor to close")


async def _open_reset_all(app: EthernityApp, pilot: Pilot) -> None:
    app.query_one(SettingsForm).show_group("Config file")
    await pilot.pause()
    app.query_one("#settings-reset-all", Button).focus()
    await pilot.press("enter")
    await pilot.pause()
