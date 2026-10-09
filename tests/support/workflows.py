from __future__ import annotations

from pathlib import Path

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import (
    Button,
    Input,
    MarkdownViewer,
    MaskedInput,
    OptionList,
    RadioButton,
    RichLog,
    SelectionList,
    Static,
    TextArea,
)

from ethernity.app.application import EthernityApp
from ethernity.app.screens.file_picker import FilePickerScreen
from ethernity.app.screens.paste_text import PasteTextScreen
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.app.widgets.workbench import WorkbenchSummary
from ethernity.app.workspaces.workspace_controls import WorkspacePathList
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.settings import SettingsTaskState
from ethernity.tasks.source_assessment import SourceAssessment
from tests.support.app import run_app_test
from tests.support.pilot import (
    click_when_ready,
    wait_for_condition as _wait_for_condition,
    wait_for_focus,
    wait_for_widget,
)


async def type_text(pilot, value: str) -> None:
    for character in value:
        await pilot.press("space" if character == " " else character)


async def choose_picker_paths(app: EthernityApp, pilot, *paths: Path) -> None:
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


async def save_picker_name(app: EthernityApp, pilot, value: str) -> None:
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
    await type_text(pilot, value)
    await pilot.press("enter")
    await _wait_for_condition(
        pilot,
        lambda: not isinstance(app.screen, FilePickerScreen),
        "save picker to close",
    )


async def save_pasted_text(app: EthernityApp, pilot, value: str) -> None:
    assert isinstance(app.screen, PasteTextScreen)
    field = app.screen.query_one("#paste-text-input", TextArea)
    field.load_text(value)
    await pilot.click("#paste-text-save")
    await pilot.pause()


async def select_guided_radio(container, pilot, label: str) -> None:
    button = next(button for button in container.query(RadioButton) if str(button.label) == label)
    button.value = True
    await pilot.pause()


def static_text(app: EthernityApp, selector: str) -> str:
    return str(app.screen.query_one(selector, Static).content)


def allow_ui_source_assessment(monkeypatch: pytest.MonkeyPatch) -> None:
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


def checklist_text(app: EthernityApp) -> str:
    return workspace_text(app)


def workspace_text(app: EthernityApp) -> str:
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
        lines.append(selection_list_text(path_list))
    for path_list in workspace.query(WorkspacePathList):
        lines.append(workspace_path_list_text(path_list))
    return "\n".join(line for line in lines if line)


def selection_list_text(selection_list: SelectionList) -> str:
    lines: list[str] = []
    for option in selection_list.options:
        prompt = option.prompt
        lines.append(prompt.plain if isinstance(prompt, Text) else str(prompt))
    return "\n".join(lines)


def workspace_path_list_text(path_list: WorkspacePathList) -> str:
    return "\n".join(
        option.prompt.plain if isinstance(option.prompt, Text) else str(option.prompt)
        for option in path_list.options
    )


def preview_text(app: EthernityApp) -> str:
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


def read_review_text(app: EthernityApp) -> str:
    body = app.screen.query_one("#review-body")
    return "\n".join(str(block.content) for block in body.query(Static) if str(block.content))


def read_result_text(app: EthernityApp) -> str:
    modal = app.screen.query_one("#result-modal")
    lines = [str(static.content) for static in modal.query(Static)]
    for option_list in modal.query(OptionList):
        lines.extend(str(option.prompt) for option in option_list.options)
    for log in modal.query(RichLog):
        lines.append(rich_log_text(log))
    return "\n".join(lines)


def assert_success_result_modal_layout(app: EthernityApp) -> None:
    modal = app.screen.query_one("#result-modal")
    body = modal.query_one("#result-body")
    actions = modal.query_one("#result-actions")

    assert body.styles.overflow_y == "auto"
    assert body.region.y + body.region.height <= actions.region.y
    assert actions.region.y + actions.region.height <= modal.region.y + modal.region.height
    assert not list(modal.query(MarkdownViewer))
    assert not list(modal.query("#result-log"))
    assert list(modal.query("#result-output"))


def rich_log_text(log: RichLog) -> str:
    return "\n".join(line.text.strip() for line in log.lines if line.text.strip())


def help_markdown_text(app: EthernityApp) -> str:
    return app.screen.query_one("#help-body", MarkdownViewer).document.source


def button_label(app: EthernityApp, selector: str) -> str:
    return str(app.screen.query_one(selector, Button).label)


def assert_buttons_are_spaced(container) -> None:
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


def assert_modal_action_buttons_are_spaced(app: EthernityApp) -> None:
    assert_buttons_are_spaced(app.screen.query_one(".modal-action-row"))


def assert_default_settings_saved(app: EthernityApp, config_path: Path) -> None:
    assert app.settings_state.design == "sentinel"
    assert app.settings_state.setting_value("qr_chunk_size") == 512
    assert static_text(app, "#setting-marker-render_style") == ""
    assert static_text(app, "#setting-marker-qr_chunk_size") == ""
    assert app.settings_state.validate_task().ready
    saved = SettingsTaskState.from_current(config_path)
    assert saved.design == "sentinel"
    assert saved.setting_value("qr_chunk_size") == 512


async def exercise_add_files_review() -> None:
    add_app = EthernityApp(
        add_files_state=AddFilesTaskState(
            source_paths=[Path("docs")],
            output_dir=Path("update-out"),
            allow_stale_head=True,
            input_paths=[Path("new.txt")],
            passphrase="secret",
        )
    )
    async with run_app_test(add_app, size=(120, 32)) as pilot:
        await pilot.press("3")
        await pilot.press("ctrl+r")

        review_text = read_review_text(add_app)
        assert "Add files to update-out" in review_text
        assert "Changes" in review_text
        assert "1 file, replacing matching paths" in review_text
        assert "new.txt" in review_text
        assert "Source version\nNewest loaded version accepted" in review_text
        assert "New update documents are written to the selected output folder" in review_text
        assert "Recovery sheets\nNo new recovery sheets" in review_text
        assert button_label(add_app, "#review-execute") == "Create update"

        await click_when_ready(pilot, "#review-execute")
        await wait_for_widget(pilot, "#result-close")

        result_text = read_result_text(add_app)
        assert "Fake update complete" in result_text
        assert_success_result_modal_layout(add_app)
        assert "Destination\nupdate-out" in result_text
        assert "Files\n2 PDFs" in result_text
        assert "\nupdate.pdf\nupdate-recovery.pdf" in result_text
        assert "Print every new PDF at actual size." in result_text


async def exercise_rebuild_review() -> None:
    rebuild_app = EthernityApp(
        rebuild_state=RebuildTaskState(
            backup_folder=Path("docs"),
            passphrase="secret",
            allow_stale_head=True,
            output_dir=Path("rebuilt"),
        )
    )
    async with run_app_test(rebuild_app, size=(120, 32)) as pilot:
        await pilot.press("4")
        await pilot.press("ctrl+r")

        review_text = read_review_text(rebuild_app)
        assert "Rebuild backup into rebuilt" in review_text
        assert "docs" in review_text
        assert "Source version\nLatest loaded version accepted" in review_text
        assert "Verification source: Loaded backup" in review_text
        assert "A new backup-<id> folder will be created inside the destination." in (review_text)
        assert "The rebuilt backup gets a new set of recovery sheets" in review_text
        assert "Existing backups stay unchanged." in review_text
        assert button_label(rebuild_app, "#review-execute") == "Rebuild backup"

        await click_when_ready(pilot, "#review-execute")
        await wait_for_widget(pilot, "#result-close")

        result_text = read_result_text(rebuild_app)
        assert "Fake rebuild complete" in result_text
        assert_success_result_modal_layout(rebuild_app)
        assert "Destination\nrebuilt" in result_text
        assert "Files\n2 PDFs" in result_text
        assert "\nmain.pdf" in result_text
        assert "Store the sheets with the matching backup version." in result_text


async def exercise_replacement_review() -> None:
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
    async with run_app_test(replace_app, size=(120, 32)) as pilot:
        await pilot.press("5")
        await pilot.press("ctrl+r")

        review_text = read_review_text(replace_app)
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
        assert button_label(replace_app, "#review-execute") == ("Create replacement sheets")

        await click_when_ready(pilot, "#review-execute")
        await wait_for_widget(pilot, "#result-close")

        result_text = read_result_text(replace_app)
        assert "Fake replacement complete" in result_text
        assert_success_result_modal_layout(replace_app)
        assert "Destination\nreplacement-docs" in result_text
        assert "Files\n2 PDFs" in result_text
        assert "Print every replacement sheet at actual size." in result_text
        assert "Store the new sheets before retiring the old set." in result_text


def assert_absent_controls(app: EthernityApp, selectors: tuple[str, ...]) -> None:
    for selector in selectors:
        assert not app.screen.query(selector), selector


async def enter_edit_field(
    app: EthernityApp, pilot: Pilot, value: str, *, plain_input: bool = False
) -> None:
    await wait_for_widget(pilot, "#edit-field-input")
    editor = app.screen
    field = editor.query_one("#edit-field-input", Input)
    if plain_input:
        assert not isinstance(field, MaskedInput)
    field.value = ""
    field.focus()
    await wait_for_focus(pilot, field)
    await type_text(pilot, value)
    await pilot.press("enter")
    await _wait_for_condition(pilot, lambda: app.screen is not editor, "field editor to close")


async def open_reset_all(app: EthernityApp, pilot: Pilot) -> None:
    app.query_one(SettingsForm).show_group("Config file")
    await pilot.pause()
    app.query_one("#settings-reset-all", Button).focus()
    await pilot.press("enter")
