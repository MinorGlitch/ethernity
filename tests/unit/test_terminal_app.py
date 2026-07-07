from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from rich.text import Text
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Header,
    Input,
    OptionList,
    RadioSet,
    RichLog,
    Select,
    Static,
    Switch,
)

from ethernity.app.application import EthernityApp
from ethernity.app.input_parsers import parse_threshold_count
from ethernity.app.screens.file_picker import FilePickerScreen
from ethernity.app.screens.help import HelpScreen
from ethernity.app.task_catalog import TASK_TITLES, review_label
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.presentation.builder import build_task_presentation
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.settings import SettingsTaskState
from ethernity.version import get_ethernity_version


async def _type_text(pilot, value: str) -> None:
    for character in value:
        await pilot.press("space" if character == " " else character)


async def _choose_picker_paths(app: EthernityApp, pilot, *paths: Path) -> None:
    assert isinstance(app.screen, FilePickerScreen)
    picker = app.screen
    picker.set_selected_paths(paths)
    await pilot.click("#file-picker-choose")
    await pilot.pause()


async def _save_picker_name(app: EthernityApp, pilot, value: str) -> None:
    assert isinstance(app.screen, FilePickerScreen)
    field = app.screen.query_one("#file-picker-name", Input)
    field.value = ""
    field.focus()
    await _type_text(pilot, value)
    await pilot.press("enter")
    await pilot.pause()


def _static_text(app: EthernityApp, selector: str) -> str:
    return str(app.screen.query_one(selector, Static).content)


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
    for table in workspace.query(DataTable):
        lines.append(_data_table_text(table))
    for option_list in workspace.query(OptionList):
        lines.append(_option_list_text_from_widget(option_list))
    return "\n".join(line for line in lines if line)


def _data_table_text(table: DataTable) -> str:
    lines: list[str] = []
    for row in table.ordered_rows:
        cells = table.get_row(row.key)
        rendered = [cell.plain if isinstance(cell, Text) else str(cell) for cell in cells]
        lines.append(" ".join(rendered))
    return "\n".join(lines)


def _preview_text(app: EthernityApp) -> str:
    return "\n".join(
        (
            _option_list_text(app, "#preview-items"),
            _option_list_text(app, "#preview-issues"),
            _static_text(app, "#preview-result"),
        )
    )


def _review_text(app: EthernityApp) -> str:
    modal = app.screen.query_one("#review-modal")
    return "\n".join(str(static.content) for static in modal.query(Static))


def _button_label(app: EthernityApp, selector: str) -> str:
    return str(app.screen.query_one(selector, Button).label)


def _option_list_text(app: EthernityApp, selector: str) -> str:
    return _option_list_text_from_widget(app.screen.query_one(selector, OptionList))


def _option_list_text_from_widget(option_list: OptionList) -> str:
    lines: list[str] = []
    for option in option_list.options:
        prompt = option.prompt
        lines.append(prompt.plain if hasattr(prompt, "plain") else str(prompt))
    return "\n".join(lines)


def test_textual_app_switches_between_backup_and_restore() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            assert app.active_task == "backup"
            assert not list(app.screen.query(Header))
            assert _static_text(app, "#app-header-brand") == "ETHERNITY"
            assert _static_text(app, "#app-header-title") == "Paper backup and recovery"
            assert _static_text(app, "#app-header-status") == f"v{get_ethernity_version()}"
            assert _static_text(app, "#nav-title") == "Workflows"
            nav = app.query_one("#nav-list", OptionList)
            nav_text = _option_list_text(app, "#nav-list")
            assert "BACKUP" in nav_text
            assert "RECOVERY" in nav_text
            assert "MAINTENANCE" in nav_text
            assert "TOOLS" in nav_text
            assert nav.options[0].disabled
            assert nav.options[1].id == "backup"
            assert "Create backup" in _static_text(app, "#canvas-title")

            await pilot.press("2")
            await pilot.pause()

            assert app.active_task == "restore"
            assert "Restore files" in _static_text(app, "#canvas-title")
            assert "Backup to restore" in _checklist_text(app)

    asyncio.run(run())


def test_textual_app_palette_changes_shell_colors() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            workspace = app.query_one("#workspace")
            nav = app.query_one("#nav")
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
            assert "No files selected" in _checklist_text(app)
            assert not list(app.screen.query("#canvas-checklist"))
            assert not list(app.screen.query("#canvas-next-row"))
            assert not app.query_one("#backup-files-table", DataTable).display
            assert "Choose at least one file or folder" in _static_text(
                app,
                "#backup-files-table-empty",
            )
            assert not list(app.screen.query("#preview-review"))
            assert _button_label(app, "#workspace-backup-files") == "Choose files..."
            assert not list(app.screen.query("#canvas-input"))
            assert not list(app.screen.query("#canvas-passphrase"))
            assert not list(app.screen.query("#canvas-output"))
            assert _button_label(app, "#canvas-primary") == "Fix: Choose files..."
            assert app.query_one("#canvas-primary").region.width <= 32

            await pilot.click("#workspace-backup-files")
            await pilot.pause()

            assert isinstance(app.screen, FilePickerScreen)

            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("8")
            await pilot.pause()

            assert not app.screen.query_one("#canvas-task-workspaces").display
            assert not app.screen.query_one("#canvas-hero").display
            assert app.screen.query_one("#canvas-settings-workspace").display
            assert app.query_one("#settings-form").region.height > 10
            assert not app.screen.query_one("#canvas-readiness").display
            assert app.query_one("#setting-control-render_style", Select).value == (
                app.settings_state.design
            )
            assert app.query_one("#setting-control-page_size", Select).value == (
                app.settings_state.paper_size
            )
            assert "config.toml" in _static_text(app, "#setting-value-config")
            assert not list(app.screen.query("#canvas-input"))
            assert not list(app.screen.query("#canvas-passphrase"))
            assert not list(app.screen.query("#canvas-output"))
            assert not app.query_one("#task-action-bar").display

            await pilot.press("3")
            await pilot.pause()

            assert app.active_task == "add_files"
            assert app.screen.query_one("#canvas-task-workspaces").display
            assert not app.screen.query_one("#canvas-settings-workspace").display
            assert "No existing backup selected" in _static_text(app, "#add-files-backup-value")
            assert "Save updated backup documents to" in _checklist_text(app)
            assert "Required: No destination selected" in _static_text(
                app,
                "#add-files-output-status",
            )
            assert "Files to add" in _checklist_text(app)
            assert _button_label(app, "#canvas-primary") == "Fix: Choose backup folder..."

    asyncio.run(run())


def test_textual_app_modals_open_centered() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("p")
            await pilot.pause()
            edit_region = app.screen.query_one("#edit-field-modal").region
            assert edit_region.x > 0
            assert edit_region.y > 0

            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("i")
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
            assert review_region.x > 0
            assert review_region.y > 0

    asyncio.run(run())


def test_textual_app_workspace_buttons_do_not_overlap_primary_action() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            for task_key in ("1", "2", "3", "4", "5", "6", "7"):
                await pilot.press(task_key)
                await pilot.pause()

                action_bar = app.query_one("#task-action-bar").region
                active_workspace = app.screen.query_one(f"#{app.active_task}-workspace")
                visible_workspace = active_workspace.query_one(".task-workspace").region
                for button in app.screen.query(Button):
                    if button.id is None or not button.id.startswith("workspace-"):
                        continue
                    if not button.display:
                        continue
                    if not button.region.overlaps(visible_workspace):
                        continue
                    assert not button.region.overlaps(action_bar)

    asyncio.run(run())


def test_textual_app_workspaces_are_grouped_into_sections() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            expected_sections = {
                "backup": 5,
                "restore": 5,
                "add_files": 6,
                "rebuild": 6,
                "replace_recovery_docs": 6,
                "kit": 4,
                "doctor": 1,
            }
            for task_key in ("1", "2", "3", "4", "5", "6", "7"):
                await pilot.press(task_key)
                await pilot.pause()

                workspace = app.screen.query_one(f"#{app.active_task}-workspace")
                scroll = workspace.query_one(".task-workspace")
                sections = list(scroll.query(".workspace-section"))

                assert len(sections) == expected_sections[app.active_task]
                assert all(child.has_class("workspace-section") for child in scroll.children)
                assert all(section.region.height > 0 for section in sections)

    asyncio.run(run())


def test_textual_app_workspace_buttons_match_presentation_actions() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            for task_key in ("1", "2", "3", "4", "5", "6", "7"):
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

                assert rendered_button_ids == presented_action_ids

    asyncio.run(run())


def test_textual_app_workspace_controls_have_event_paths() -> None:
    handled_select_ids = {
        "workspace-kit-variant-select",
        "workspace-backup-passphrase-words",
        "workspace-backup-signing-key-mode",
        "workspace-restore-auth-policy",
        "workspace-restore-auth-material",
        "workspace-rebuild-auth-material",
        "workspace-add-files-unlock-policy",
        "workspace-add-files-recovery-docs",
        "workspace-add-files-signing-key-mode",
        "workspace-replace-passphrase-select",
        "workspace-replace-signing-key-select",
    }
    handled_radio_ids = {
        "workspace-backup-recovery-method",
        "workspace-restore-target-method",
        "workspace-replace-recovery-method",
        "workspace-restore-unlock-method",
        "workspace-add-files-unlock-method",
        "workspace-rebuild-unlock-method",
        "workspace-replace-unlock-method",
    }

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            for task_key in ("1", "2", "3", "4", "5", "6", "7"):
                await pilot.press(task_key)
                await pilot.pause()

                active_workspace = app.screen.query_one(f"#{app.active_task}-workspace")
                rendered_select_ids = {
                    select.id
                    for select in active_workspace.query(Select)
                    if select.id is not None and select.id.startswith("workspace-")
                }
                rendered_radio_ids = {
                    radio_set.id
                    for radio_set in active_workspace.query(RadioSet)
                    if radio_set.id is not None and radio_set.id.startswith("workspace-")
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


def test_textual_app_shows_requirement_status_inline_and_in_summary() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            assert "Required: No files selected yet" in _static_text(
                app,
                "#backup-files-status",
            )
            assert "Required: No output folder selected" in _static_text(
                app,
                "#backup-destination-status",
            )
            assert "Choose at least one file or folder to back up" in _preview_text(app)

            await pilot.press("i")
            await _choose_picker_paths(app, pilot, Path("README.md"))

            assert "Complete: 1 path(s) selected" in _static_text(
                app,
                "#backup-files-status",
            )
            assert "Required: No output folder selected" in _static_text(
                app,
                "#backup-destination-status",
            )
            assert "Choose where backup documents will be saved" in _preview_text(app)

            await pilot.press("o")
            await _save_picker_name(app, pilot, "backup-out")

            assert "Complete: 1 path(s) selected" in _static_text(
                app,
                "#backup-files-status",
            )
            assert "Complete:" in _static_text(app, "#backup-destination-status")
            assert _button_label(app, "#canvas-primary") == "Review backup"

    asyncio.run(run())


def test_textual_app_common_terminal_sizes_keep_workspaces_readable() -> None:
    async def run() -> None:
        for size in ((160, 48), (120, 36), (96, 30)):
            app = EthernityApp()
            async with app.run_test(size=size) as pilot:
                nav = app.query_one("#nav").region
                workspace = app.query_one("#workspace").region
                preview = app.query_one("#preview").region

                assert nav.x + nav.width <= workspace.x
                assert workspace.x + workspace.width <= preview.x
                assert workspace.width >= 36
                assert preview.width >= 28

                for task_key in ("1", "2", "3", "4", "5", "6", "7"):
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
                        assert (
                            not button.region.overlaps(action_bar) or button.id == "canvas-primary"
                        )
                        assert len(str(button.label)) <= button.region.width

    asyncio.run(run())


def test_textual_app_help_is_contextual_to_current_workflow() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("?")
            await pilot.pause()

            assert isinstance(app.screen, HelpScreen)
            assert _static_text(app, "#help-title") == "Create backup help"
            assert "Make a new printable paper backup" in _static_text(app, "#help-description")
            assert "starting a new backup set" in _static_text(app, "#help-use-when")
            assert "only want to add files" in _static_text(app, "#help-avoid-when")
            assert "Files to back up" in _static_text(app, "#help-needs")
            assert not list(app.screen.query("#help-mode-index"))

            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()

            assert isinstance(app.screen, HelpScreen)
            assert _static_text(app, "#help-title") == "Restore files help"
            assert "Recover original files" in _static_text(app, "#help-description")
            assert "You need the data back" in _static_text(app, "#help-use-when")
            assert "print a fresh copy" in _static_text(app, "#help-avoid-when")

    asyncio.run(run())


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
            await pilot.press("i")
            await pilot.pause()

            assert isinstance(app.screen, FilePickerScreen)
            picker = app.screen
            picker.set_selected_paths((Path("README.md"), Path("docs")))
            selected = picker.query_one("#file-picker-selected", OptionList)
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
            assert str(picker.query_one("#file-picker-location", Static).content) == str(
                root_before.parent
            )

    asyncio.run(run())


def test_textual_app_diagnostics_are_on_demand_and_redacted(tmp_path) -> None:
    async def run() -> None:
        input_path = tmp_path / "secrets.txt"
        input_path.write_text("hello backup internals", encoding="utf-8")
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[input_path],
                output_dir=tmp_path / "backup-out",
                passphrase="super secret",
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            assert app.query_one("#preview-diagnostics", Button).display

            await pilot.click("#preview-diagnostics")
            await pilot.pause()

            assert _static_text(app, "#diagnostics-title") == "Backup internals"
            assert app.screen.query_one("#diagnostics-internals", RichLog)
            close_button = app.screen.query_one("#diagnostics-close", Button)
            assert str(close_button.label) == "Close"
            assert close_button.variant == "default"

            switch = app.screen.query_one("#diagnostics-reveal", Switch)
            switch.toggle()
            await pilot.pause()

            assert switch.value

    asyncio.run(run())


def test_textual_app_hides_diagnostics_until_backup_files_exist() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)):
            button = app.query_one("#preview-diagnostics", Button)

            assert not button.display
            assert button.disabled

    asyncio.run(run())


def test_textual_app_supports_hjkl_and_arrow_navigation() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("j")
            await pilot.pause()
            assert app.active_task == "restore"

            await pilot.press("down")
            await pilot.pause()
            assert app.active_task == "add_files"

            await pilot.press("up")
            await pilot.pause()
            assert app.active_task == "restore"

            await pilot.press("k")
            await pilot.pause()
            assert app.active_task == "backup"

            await pilot.press("h")
            await pilot.pause()
            assert app.screen.focused is app.query_one("#nav-list", OptionList)

            await pilot.press("l")
            await pilot.pause()
            assert app.screen.focused is app.query_one("#workspace-backup-files", Button)

    asyncio.run(run())


def test_textual_app_switches_to_kit_and_doctor() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("6")
            await pilot.pause()

            assert app.active_task == "kit"
            assert "Create recovery kit PDF" in _static_text(app, "#canvas-title")
            assert "Built-in kit" not in _checklist_text(app)
            assert "recovery_kit_qr.pdf" in _checklist_text(app)

            await pilot.press("7")
            await pilot.pause()

            assert app.active_task == "doctor"
            assert "Setup check" in _static_text(app, "#canvas-title")
            assert "Python runtime" in _checklist_text(app)

            await pilot.press("8")
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
            assert "Files to add" in _checklist_text(app)

            await pilot.press("4")
            await pilot.pause()

            assert app.active_task == "rebuild"
            assert "Rebuild backup" in _static_text(app, "#canvas-title")
            assert "No backup loaded yet" in _checklist_text(app)

            await pilot.press("5")
            await pilot.pause()

            assert app.active_task == "replace_recovery_docs"
            assert "Create replacement recovery sheets" in _static_text(app, "#canvas-title")
            assert "New recovery method" in _checklist_text(app)

    asyncio.run(run())


def test_textual_app_canvas_rows_edit_secondary_choices() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.click("#workspace-backup-recovery-single_phrase")
            await pilot.pause()

            assert app.backup_state.recovery_method == "single_phrase"

            await pilot.press("6")
            await pilot.pause()
            app.query_one("#workspace-kit-paper", Select).value = "LETTER"
            await pilot.pause()
            app.query_one("#workspace-kit-design", Select).value = "forge"
            await pilot.pause()

            assert app.kit_state.paper_size == "LETTER"
            assert app.kit_state.design == "forge"

            await pilot.press("3")
            await pilot.pause()
            await pilot.click("#workspace-add-files-source")
            await _choose_picker_paths(app, pilot, Path("docs"))

            assert [str(path) for path in app.add_files_state.source_paths] == ["docs"]
            assert not app.add_files_state.allow_stale_head
            await pilot.click("#workspace-add-files-freshness")
            await pilot.pause()
            assert app.add_files_state.allow_stale_head

    asyncio.run(run())


def test_textual_app_splits_backup_files_and_folders() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("i")
            await _choose_picker_paths(app, pilot, Path("README.md"), Path("docs"))

            assert [str(path) for path in app.backup_state.input_paths] == ["README.md"]
            assert [str(path) for path in app.backup_state.input_dirs] == ["docs"]

    asyncio.run(run())


def test_textual_app_unlock_recovery_documents_are_real_picker() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("2")
            await pilot.click("#workspace-restore-unlock-recovery_documents")
            await pilot.pause()
            await _choose_picker_paths(app, pilot, Path("recovery.pdf"))

            assert [str(path) for path in app.restore_state.recovery_documents] == ["recovery.pdf"]
            assert app.restore_state.passphrase is None
            assert not app.restore_state.recovery_payload_files

    asyncio.run(run())


def test_textual_app_restore_source_modes_are_real_pickers() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("2")
            await pilot.click("#workspace-restore-recovery-text")
            await _choose_picker_paths(app, pilot, Path("recovery.txt"))

            assert app.restore_state.recovery_text_file == Path("recovery.txt")
            assert not app.restore_state.source_paths
            assert app.restore_state.payloads_file is None
            assert "Recovery text" in _checklist_text(app)

            await pilot.click("#workspace-restore-payloads")
            await _choose_picker_paths(app, pilot, Path("payloads.json"))

            assert app.restore_state.payloads_file == Path("payloads.json")
            assert app.restore_state.recovery_text_file is None
            assert not app.restore_state.source_paths
            assert "Payload files" in _checklist_text(app)

    asyncio.run(run())


def test_textual_app_restore_expected_head_fingerprint_is_real_control() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("2")
            await pilot.click("#workspace-restore-expected-head")
            await _type_text(pilot, "head123")
            await pilot.press("enter")
            await pilot.pause()

            assert app.restore_state.expected_head_doc_hash == "head123"
            assert app.restore_state.to_recover_args().expected_head_doc_hash == "head123"
            assert "Expected latest backup fingerprint provided" in _preview_text(app)

            await pilot.click("#workspace-restore-source")
            await _choose_picker_paths(app, pilot, Path("scan.pdf"))

            assert app.restore_state.expected_head_doc_hash is None

    asyncio.run(run())


def test_textual_app_expected_fingerprint_is_real_freshness_path() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("3")
            await pilot.click("#workspace-add-files-source")
            await _choose_picker_paths(app, pilot, Path("scan.pdf"))

            assert not app.add_files_state.allow_stale_head
            assert app.add_files_state.expected_head_doc_hash is None

            await pilot.click("#workspace-add-files-fingerprint")
            await _type_text(pilot, "abc123")
            await pilot.press("enter")
            await pilot.pause()

            assert app.add_files_state.expected_head_doc_hash == "abc123"
            assert not app.add_files_state.allow_stale_head
            assert "Expected latest backup fingerprint provided" in _checklist_text(app)

    asyncio.run(run())


def test_textual_app_restore_target_fingerprint_is_real_control() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("2")
            await pilot.pause()
            await pilot.click("#workspace-restore-target-fingerprint")
            await pilot.pause()
            await _type_text(pilot, "feedface")
            await pilot.press("enter")
            await pilot.pause()

            assert app.restore_state.target == "specific_update"
            assert app.restore_state.extension_index is None
            assert app.restore_state.extension_doc_hash == "feedface"
            assert "Specific version/update by fingerprint" in _checklist_text(app)

    asyncio.run(run())


def test_textual_app_restore_auth_policy_control_is_real() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("2")
            await pilot.pause()

            app.query_one("#workspace-restore-auth-policy", Select).value = "allow-unsigned"
            await pilot.pause()

            assert app.restore_state.allow_unsigned
            assert app.restore_state.to_recover_args().allow_unsigned
            assert "Allow unsigned legacy recovery" in _preview_text(app)

            app.query_one("#workspace-restore-auth-policy", Select).value = "require-signed"
            await pilot.pause()

            assert not app.restore_state.allow_unsigned

    asyncio.run(run())


def test_textual_app_restore_auth_material_control_is_real() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("2")
            await pilot.pause()

            app.query_one("#workspace-restore-auth-material", Select).value = "text"
            await pilot.pause()
            await _choose_picker_paths(app, pilot, Path("auth.txt"))

            assert app.restore_state.auth_text_file == Path("auth.txt")
            assert app.restore_state.auth_payloads_file is None
            assert app.restore_state.to_recover_args().auth_fallback_file == "auth.txt"
            assert "Trust text: auth.txt" in _preview_text(app)

            app.query_one("#workspace-restore-auth-material", Select).value = "payloads"
            await pilot.pause()
            await _choose_picker_paths(app, pilot, Path("auth-payloads.json"))

            assert app.restore_state.auth_text_file is None
            assert app.restore_state.auth_payloads_file == Path("auth-payloads.json")
            assert app.restore_state.to_recover_args().auth_payloads_file == "auth-payloads.json"

            app.query_one("#workspace-restore-auth-material", Select).value = "auto"
            await pilot.pause()

            assert app.restore_state.auth_text_file is None
            assert app.restore_state.auth_payloads_file is None

    asyncio.run(run())


def test_textual_app_edit_add_files_state() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("3")
            await pilot.press("i")
            await _choose_picker_paths(app, pilot, Path("README.md"))
            await pilot.press("o")
            await _choose_picker_paths(app, pilot, Path("docs"))
            await pilot.press("p")
            await _type_text(pilot, "secret")
            await pilot.press("enter")
            await pilot.pause()

            assert app.add_files_state.validate_task().ready
            workspace = _checklist_text(app)
            assert "README.md" in workspace
            assert "docs" in workspace
            assert "Save updated backup documents to" in workspace
            assert "Updates will be saved in docs" in workspace
            assert "Output location" in _preview_text(app)
            assert "Updates will be saved in docs" in _preview_text(app)

    asyncio.run(run())


def test_textual_app_edit_rebuild_state() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("4")
            await pilot.press("i")
            await _choose_picker_paths(app, pilot, Path("docs"))
            await pilot.press("o")
            await _save_picker_name(app, pilot, "rebuilt")
            await pilot.press("p")
            await _type_text(pilot, "secret")
            await pilot.press("enter")
            await pilot.pause()

            assert app.rebuild_state.validate_task().ready
            workspace = _checklist_text(app)
            assert "docs" in workspace
            assert "rebuilt" in workspace
            assert "Rebuild options" in workspace
            assert "Print options" in workspace
            assert "Existing backup files are not deleted or modified." in _static_text(
                app,
                "#rebuild-safety-value",
            )
            assert "Existing files" in _preview_text(app)
            assert "Existing backup files are not deleted or modified." in _preview_text(app)
            assert not app.query_one("#rebuild-advanced-auth-row").display
            assert not app.query_one("#rebuild-advanced-qr-row").display

            app.query_one("#rebuild-advanced-toggle", Button).focus()
            await pilot.press("enter")
            await pilot.pause()

            assert app.query_one("#rebuild-advanced-auth-row").display
            assert app.query_one("#rebuild-advanced-qr-row").display

            app.query_one("#workspace-rebuild-qr-chunk-size", Button).focus()
            await pilot.press("enter")
            qr_chunk = app.screen.query_one("#edit-field-input", Input)
            qr_chunk.value = ""
            qr_chunk.focus()
            await _type_text(pilot, "384")
            await pilot.press("enter")
            await pilot.pause()

            assert app.rebuild_state.qr_chunk_size == 384
            assert app.rebuild_state.to_compact_args().qr_chunk_size == 384

    asyncio.run(run())


def test_textual_app_rebuild_auth_material_control_is_real() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("4")
            await pilot.pause()

            app.query_one("#rebuild-advanced-toggle", Button).focus()
            await pilot.press("enter")
            await pilot.pause()

            app.query_one("#workspace-rebuild-auth-material", Select).value = "payloads"
            await pilot.pause()
            await _choose_picker_paths(app, pilot, Path("auth-payloads.json"))

            assert app.rebuild_state.auth_text_file is None
            assert app.rebuild_state.auth_payloads_file == Path("auth-payloads.json")
            assert app.rebuild_state.to_compact_args().auth_payloads_file == "auth-payloads.json"
            assert "Trust payload files: auth-payloads.json" in _preview_text(app)

            app.query_one("#workspace-rebuild-auth-material", Select).value = "auto"
            await pilot.pause()

            assert app.rebuild_state.auth_text_file is None
            assert app.rebuild_state.auth_payloads_file is None

    asyncio.run(run())


def test_textual_app_edit_replace_recovery_docs_state() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("5")
            await pilot.press("i")
            await _choose_picker_paths(app, pilot, Path("README.md"))
            await pilot.press("p")
            await _type_text(pilot, "secret")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.click("#workspace-replace-freshness")
            await pilot.pause()
            await pilot.press("o")
            await _save_picker_name(app, pilot, "replacement-docs")

            assert app.replace_recovery_docs_state.validate_task().ready
            assert app.replace_recovery_docs_state.allow_stale_head
            workspace = _checklist_text(app)
            assert "README.md" in workspace
            assert "3 new recovery sheets; any 2 can restore" in workspace
            assert "Save replacement sheets to" in workspace
            assert "Print options" in workspace
            assert "Existing backup files are not deleted or modified." in _static_text(
                app,
                "#replace-safety-value",
            )
            assert "Existing files" in _preview_text(app)
            assert "Existing backup files are not deleted or modified." in _preview_text(app)

    asyncio.run(run())


def test_textual_app_replace_recovery_signing_key_controls_are_real() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.press("5")
            await pilot.pause()

            assert "Signature" in _checklist_text(app)
            assert "Warning: signing-key recovery sheets will not be created" in _static_text(
                app,
                "#replace-signing-key-status",
            )
            assert not app.replace_recovery_docs_state.mint_signing_key_recovery

            app.query_one("#workspace-replace-signing-key-select", Select).value = "same"
            await pilot.pause()

            assert app.replace_recovery_docs_state.mint_signing_key_recovery
            assert app.replace_recovery_docs_state.signing_key_recovery_threshold is None
            assert app.replace_recovery_docs_state.signing_key_recovery_count is None
            assert app.replace_recovery_docs_state.to_mint_args().mint_signing_key_shards

            app.query_one("#workspace-replace-signing-key-select", Select).value = "custom"
            await pilot.pause()
            field = app.screen.query_one("#edit-field-input", Input)
            field.value = ""
            field.focus()
            await _type_text(pilot, "3/5")
            await pilot.press("enter")
            await pilot.pause()

            assert app.replace_recovery_docs_state.signing_key_recovery_threshold == 3
            assert app.replace_recovery_docs_state.signing_key_recovery_count == 5
            args = app.replace_recovery_docs_state.to_mint_args()
            assert args.signing_key_shard_threshold == 3
            assert args.signing_key_shard_count == 5
            assert app.query_one("#workspace-replace-signing-key-select", Select).value == "custom"

            app.query_one("#workspace-replace-signing-key-select", Select).value = "off"
            await pilot.pause()

            assert not app.replace_recovery_docs_state.mint_signing_key_recovery
            assert app.replace_recovery_docs_state.signing_key_recovery_threshold is None
            assert app.replace_recovery_docs_state.signing_key_recovery_count is None
            assert not app.replace_recovery_docs_state.to_mint_args().mint_signing_key_shards

    asyncio.run(run())


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
            await pilot.pause()
            field = app.screen.query_one("#edit-field-input", Input)
            field.value = ""
            field.focus()
            await _type_text(pilot, "2")
            await pilot.press("enter")
            await pilot.pause()

            state = app.replace_recovery_docs_state
            assert state.mint_passphrase_recovery
            assert state.passphrase_replacement_count == 2
            assert state.to_mint_args().passphrase_replacement_count == 2
            assert app.query_one("#workspace-replace-passphrase-select", Select).value == "replace"
            assert "Replace 2 existing sheet(s)" in _checklist_text(app)

    asyncio.run(run())


def test_textual_app_replace_recovery_signing_key_payloads_are_real_picker() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 72)) as pilot:
            await pilot.press("5")
            app.query_one("#workspace-replace-signing-key-payloads", Button).focus()
            await pilot.press("enter")
            await _choose_picker_paths(app, pilot, Path("signing-payloads.txt"))

            assert app.replace_recovery_docs_state.signing_key_recovery_payload_files == [
                Path("signing-payloads.txt")
            ]
            args = app.replace_recovery_docs_state.to_mint_args()
            assert args.signing_key_shard_payloads_file == ["signing-payloads.txt"]
            assert "1 signing-key payload file(s)" in _checklist_text(app)

            app.query_one("#workspace-replace-signing-key-select", Select).value = "replace"
            await pilot.pause()
            count = app.screen.query_one("#edit-field-input", Input)
            count.value = ""
            count.focus()
            await _type_text(pilot, "1")
            await pilot.press("enter")
            await pilot.pause()

            assert app.replace_recovery_docs_state.signing_key_replacement_count == 1
            args = app.replace_recovery_docs_state.to_mint_args()
            assert args.mint_signing_key_shards
            assert args.signing_key_replacement_count == 1
            assert "1 replacement sheet(s)" in _checklist_text(app)

    asyncio.run(run())


def test_textual_app_custom_quorum_updates_do_not_trip_assignment_validation() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)):
            app._apply_backup_recovery("4/5")
            app._apply_replace_recovery_set("4/5")

            assert app.backup_state.shard_threshold == 4
            assert app.backup_state.shard_count == 5
            assert app.replace_recovery_docs_state.recovery_threshold == 4
            assert app.replace_recovery_docs_state.recovery_document_count == 5

    asyncio.run(run())


def test_textual_app_quorum_parser_rejects_counts_above_shamir_limit() -> None:
    assert parse_threshold_count("2/255") == (2, 255)
    assert parse_threshold_count("2/256") is None
    assert parse_threshold_count("256/256") is None


def test_textual_app_backup_advanced_controls_are_real(tmp_path) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(140, 72)) as pilot:
            await pilot.pause()

            assert "Advanced: using saved defaults" in _static_text(
                app,
                "#backup-advanced-summary",
            )
            assert not app.query_one("#backup-advanced-passphrase-row").display
            assert not app.query_one("#backup-advanced-qr-row").display

            app.query_one("#backup-advanced-toggle", Button).focus()
            await pilot.press("enter")
            await pilot.pause()

            assert app.query_one("#backup-advanced-passphrase-row").display
            assert app.query_one("#backup-advanced-qr-row").display
            assert _button_label(app, "#backup-advanced-toggle") == "Hide advanced"

            words_select = app.query_one("#workspace-backup-passphrase-words", Select)
            words_select.value = "18"
            await pilot.pause()

            assert app.backup_state.passphrase_words == 18
            assert app.backup_state.passphrase is None

            await pilot.click("#workspace-backup-passphrase")
            await pilot.pause()
            passphrase = app.screen.query_one("#edit-field-input", Input)
            passphrase.value = ""
            passphrase.focus()
            await _type_text(pilot, "manual secret")
            await pilot.press("enter")
            await pilot.pause()

            assert app.backup_state.passphrase == "manual secret"
            assert app.backup_state.passphrase_words is None

            words_select.value = "24"
            await pilot.pause()

            assert app.backup_state.passphrase is None
            assert app.backup_state.passphrase_words == 24

            app.query_one("#workspace-backup-signing-key-mode", Select).value = "sharded"
            await pilot.pause()
            await pilot.click("#workspace-backup-signing-key-shards")
            await pilot.pause()
            shards = app.screen.query_one("#edit-field-input", Input)
            shards.value = ""
            shards.focus()
            await _type_text(pilot, "3/5")
            await pilot.press("enter")
            await pilot.pause()

            assert app.backup_state.signing_key_mode == "sharded"
            assert app.backup_state.signing_key_shard_threshold == 3
            assert app.backup_state.signing_key_shard_count == 5
            assert "Sharded, any 3 of 5" in _workspace_text(app)

            await pilot.click("#workspace-backup-base-dir")
            await pilot.pause()
            await _choose_picker_paths(app, pilot, tmp_path)

            assert app.backup_state.base_dir == tmp_path
            assert str(tmp_path) in _workspace_text(app)

            await pilot.click("#workspace-backup-qr-chunk-size")
            await pilot.pause()
            qr_chunk = app.screen.query_one("#edit-field-input", Input)
            qr_chunk.value = ""
            qr_chunk.focus()
            await _type_text(pilot, "384")
            await pilot.press("enter")
            await pilot.pause()

            assert app.backup_state.qr_chunk_size == 384
            assert app.backup_state.to_backup_args().qr_chunk_size == 384
            assert "384 bytes" in _workspace_text(app)

    asyncio.run(run())


def test_textual_app_add_files_advanced_controls_are_real(tmp_path) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(140, 72)) as pilot:
            await pilot.press("3")
            await pilot.pause()

            assert "Advanced: using saved defaults" in _static_text(
                app,
                "#add-files-advanced-summary",
            )
            assert not app.query_one("#add-files-advanced-base-row").display
            assert not app.query_one("#add-files-advanced-recovery-row").display

            app.query_one("#add-files-advanced-toggle", Button).focus()
            await pilot.press("enter")
            await pilot.pause()

            assert app.query_one("#add-files-advanced-base-row").display
            assert app.query_one("#add-files-advanced-recovery-row").display
            assert _button_label(app, "#add-files-advanced-toggle") == "Hide advanced"

            app.query_one("#workspace-add-files-unlock-policy", Select).value = "reuse-root"
            await pilot.pause()

            assert app.add_files_state.unlock_policy == "reuse-root"

            app.query_one("#workspace-add-files-recovery-docs", Select).value = "custom"
            await pilot.pause()
            recovery = app.screen.query_one("#edit-field-input", Input)
            recovery.value = ""
            recovery.focus()
            await _type_text(pilot, "3/5")
            await pilot.press("enter")
            await pilot.pause()

            assert app.add_files_state.unlock_policy == "self-contained"
            assert app.add_files_state.recovery_document_threshold == 3
            assert app.add_files_state.recovery_document_count == 5
            assert app.query_one("#workspace-add-files-recovery-docs", Select).value == "custom"

            app.query_one("#workspace-add-files-signing-key-mode", Select).value = "custom"
            await pilot.pause()
            signing = app.screen.query_one("#edit-field-input", Input)
            signing.value = ""
            signing.focus()
            await _type_text(pilot, "2/4")
            await pilot.press("enter")
            await pilot.pause()

            assert app.add_files_state.signing_key_mode == "sharded"
            assert app.add_files_state.signing_key_recovery_threshold == 2
            assert app.add_files_state.signing_key_recovery_count == 4

            await pilot.click("#workspace-add-files-base-dir")
            await pilot.pause()
            await _choose_picker_paths(app, pilot, tmp_path)

            assert app.add_files_state.base_dir == tmp_path
            assert str(tmp_path) in _workspace_text(app)

            await pilot.click("#workspace-add-files-qr-chunk-size")
            await pilot.pause()
            qr_chunk = app.screen.query_one("#edit-field-input", Input)
            qr_chunk.value = ""
            qr_chunk.focus()
            await _type_text(pilot, "384")
            await pilot.press("enter")
            await pilot.pause()

            assert app.add_files_state.qr_chunk_size == 384
            assert app.add_files_state.to_extend_args().qr_chunk_size == 384
            assert "384 bytes" in _workspace_text(app)

            app.query_one("#workspace-add-files-recovery-docs", Select).value = "none"
            await pilot.pause()
            app.query_one("#workspace-add-files-signing-key-mode", Select).value = "default"
            await pilot.pause()

            assert app.add_files_state.recovery_document_threshold is None
            assert app.add_files_state.recovery_document_count == 0
            assert app.add_files_state.signing_key_mode is None
            assert app.add_files_state.signing_key_recovery_threshold is None
            assert app.add_files_state.signing_key_recovery_count is None

    asyncio.run(run())


def test_textual_app_edit_kit_output() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("6")
            await pilot.press("o")
            await _save_picker_name(app, pilot, "kit.pdf")

            assert app.kit_state.output_path.name == "kit.pdf"
            assert "kit.pdf" in _checklist_text(app)

    asyncio.run(run())


def test_textual_app_edit_kit_qr_chunk_size() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("6")
            await pilot.click("#workspace-kit-chunk-size")
            await _type_text(pilot, "512")
            await pilot.press("enter")
            await pilot.pause()

            assert app.kit_state.chunk_size == 512
            assert "512 bytes" in _checklist_text(app)
            assert "512" in _preview_text(app)

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
            await pilot.press("8")
            app.query_one("#setting-control-render_style", Select).value = "forge"
            await pilot.pause()
            app.query_one("#setting-control-page_size", Select).value = "LETTER"
            await pilot.pause()
            await pilot.press("o")
            await _save_picker_name(app, pilot, "backup-out")
            qr_chunk = app.query_one("#setting-control-qr_chunk_size", Input)
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


def test_textual_app_settings_collapses_advanced_and_shows_config_actions() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 72)) as pilot:
            await pilot.press("8")
            await pilot.pause()

            assert "Advanced: using saved defaults" in _static_text(
                app,
                "#settings-advanced-summary",
            )
            assert not app.query_one("#setting-row-qr_chunk_size").display
            assert not app.query_one("#setting-help-qr_chunk_size").display
            assert _button_label(app, "#settings-reset-group-printing") == "Restore defaults"
            assert _button_label(app, "#settings-reset-all") == "Restore all defaults"
            assert _button_label(app, "#settings-copy-config") == "Copy path"
            assert _button_label(app, "#settings-open-config") == "Open folder"
            assert _static_text(app, "#settings-save-status") == "Saved just now"

            app.query_one("#settings-advanced-toggle", Button).focus()
            await pilot.press("enter")
            await pilot.pause()

            assert app.query_one("#setting-row-qr_chunk_size").display
            assert app.query_one("#setting-help-qr_chunk_size").display
            assert _button_label(app, "#settings-advanced-toggle") == "Hide advanced"
            assert "Bytes per QR code" in _static_text(app, "#setting-help-qr_chunk_size")

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
            await pilot.press("8")

            app.query_one("#setting-control-render_style", Select).value = "forge"
            await pilot.pause()
            app.query_one("#setting-control-page_size", Select).value = "LETTER"
            await pilot.pause()

            assert app.settings_state.design == "forge"
            assert app.settings_state.paper_size == "LETTER"
            assert _static_text(app, "#setting-marker-render_style") == "Changed"
            assert _static_text(app, "#setting-marker-page_size") == "Changed"

            app.query_one("#settings-reset-group-printing", Button).focus()
            await pilot.press("enter")
            await pilot.pause()

            assert app.settings_state.design == "sentinel"
            assert app.settings_state.paper_size == "A4"
            assert _static_text(app, "#setting-marker-render_style") == ""
            assert _static_text(app, "#setting-marker-page_size") == ""

            app.query_one("#setting-control-render_style", Select).value = "forge"
            await pilot.pause()
            qr_chunk = app.query_one("#setting-control-qr_chunk_size", Input)
            qr_chunk.value = ""
            qr_chunk.focus()
            await _type_text(pilot, "1024")
            await pilot.press("enter")
            await pilot.pause()

            assert app.settings_state.design == "forge"
            assert app.settings_state.setting_value("qr_chunk_size") == 1024
            assert _static_text(app, "#setting-marker-qr_chunk_size") == "Changed"

            app.query_one("#settings-reset-all", Button).focus()
            await pilot.press("enter")
            await pilot.pause()

            assert app.settings_state.design == "sentinel"
            assert app.settings_state.setting_value("qr_chunk_size") == 512
            assert _static_text(app, "#setting-marker-render_style") == ""
            assert _static_text(app, "#setting-marker-qr_chunk_size") == ""
            saved = SettingsTaskState.from_current(config_path)
            assert saved.design == "sentinel"
            assert saved.setting_value("qr_chunk_size") == 512

    asyncio.run(run())


def test_textual_app_edit_restore_fields_updates_readiness() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("2")
            await pilot.press("i")
            await _choose_picker_paths(app, pilot, Path("README.md"))
            await pilot.press("p")
            await _type_text(pilot, "demo passphrase")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("o")
            await _save_picker_name(app, pilot, "recovered")

            assert app.restore_state.validate_task().ready
            sections = _checklist_text(app)
            preview = _preview_text(app)
            assert "README.md" in sections
            assert "Passphrase provided" in preview

    asyncio.run(run())


def test_textual_app_edit_and_clear_backup_state() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("i")
            await _choose_picker_paths(app, pilot, Path("README.md"))
            await pilot.press("o")
            await _save_picker_name(app, pilot, "backup-out")

            assert app.backup_state.validate_task().ready
            workspace = _checklist_text(app)
            assert "README.md" in workspace
            assert "backup-out" in workspace

            await pilot.press("c")
            await pilot.pause()

            assert not app.backup_state.validate_task().ready
            assert "No files selected" in _checklist_text(app)

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


def test_textual_app_summary_blocker_selection_focuses_matching_field() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 48)) as pilot:
            issues = app.query_one("#preview-issues", OptionList)
            issues.focus()
            issues.highlighted = 1
            await pilot.press("enter")
            await pilot.pause()

            assert app.screen.focused is app.query_one("#workspace-backup-output", Button)

    asyncio.run(run())


def test_textual_app_review_can_execute_ready_backup(monkeypatch) -> None:
    calls: list[BackupTaskState] = []

    def fake_execute(self: BackupTaskState) -> TaskExecutionResult:
        calls.append(self)
        return TaskExecutionResult(
            ok=True,
            message="Fake backup complete.",
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
            await pilot.press("ctrl+r")
            await pilot.pause()

            assert "Ready to write files" in _static_text(app, "#review-status")
            assert _static_text(app, "#review-summary") == "All required items complete"
            assert "Complete" in _review_text(app)

            await pilot.click("#review-execute")
            for _ in range(10):
                await pilot.pause(0.1)
                if calls:
                    break

            assert [str(path) for path in calls[0].input_paths] == ["secrets.txt"]
            assert "Fake backup complete." in _preview_text(app)

    asyncio.run(run())


def test_textual_app_review_can_execute_print_kit(monkeypatch) -> None:
    calls: list[PrintKitTaskState] = []

    def fake_execute(self: PrintKitTaskState) -> TaskExecutionResult:
        calls.append(self)
        return TaskExecutionResult(
            ok=True,
            message="Fake kit complete.",
            output_paths=(Path("kit.pdf"),),
        )

    monkeypatch.setattr(PrintKitTaskState, "execute", fake_execute)

    async def run() -> None:
        app = EthernityApp(kit_state=PrintKitTaskState(output_path=Path("kit.pdf")))
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("6")
            await pilot.press("ctrl+r")
            await pilot.pause()

            assert "Ready to write files" in _static_text(app, "#review-status")
            assert _static_text(app, "#review-summary") == "All required items complete"
            assert "Complete" in _review_text(app)

            await pilot.click("#review-execute")
            for _ in range(10):
                await pilot.pause(0.1)
                if calls:
                    break

            assert str(calls[0].output_path) == "kit.pdf"
            assert "Fake kit complete." in _preview_text(app)

    asyncio.run(run())
