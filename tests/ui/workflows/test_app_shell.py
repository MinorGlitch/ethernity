from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest
from textual.widgets import (
    Button,
    DirectoryTree,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    SelectionList,
    Switch,
    TabbedContent,
    TabPane,
)

from ethernity.app.application import EthernityApp
from ethernity.app.help_content import HELP_MODES
from ethernity.app.screens.file_picker import FilePickerScreen
from ethernity.app.screens.help import HelpScreen
from ethernity.app.task_catalog import review_label
from ethernity.app.widgets.workbench import WorkbenchSummary
from ethernity.app.widgets.workflow.options import OptionsEditor, QuorumEditor
from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState
from ethernity.version import get_ethernity_version
from tests.support import workflows as workflow_support
from tests.support.app import run_app_test
from tests.support.pilot import (
    wait_for_condition as _wait_for_condition,
)

pytestmark = pytest.mark.usefixtures("isolated_app_settings")


def test_textual_app_switches_between_backup_and_restore() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
            assert app.active_task == "backup"
            assert not list(app.screen.query(Header))
            assert workflow_support.static_text(app, "#app-header-brand") == "ETHERNITY"
            assert (
                workflow_support.static_text(app, "#app-header-title") == "Paper backup & recovery"
            )
            assert (
                workflow_support.static_text(app, "#app-header-status")
                == f"v{get_ethernity_version()}"
            )
            assert not list(app.query("#nav-drawer, #nav-strip"))
            assert app.query_one("#nav-create", Button).has_class("active-task")
            assert not app.query_one("#nav-restore", Button).has_class("active-task")
            assert "Choose files to back up" in workflow_support.static_text(app, "#canvas-title")

            await pilot.press("2")

            assert app.active_task == "restore"
            assert "Restore files" in workflow_support.static_text(app, "#canvas-title")
            assert app.query_one("#workflow-restore-source-body", SourceChooser).display
            assert app.query_one("#nav-restore", Button).has_class("active-task")
            assert not app.query_one("#nav-create", Button).has_class("active-task")

    asyncio.run(run())


def test_textual_app_nav_highlight_does_not_switch_workflow() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(160, 48)) as pilot:
            await pilot.press("ctrl+b", "right")

            assert app.active_task == "backup"
            assert "Choose files to back up" in workflow_support.static_text(app, "#canvas-title")

            await pilot.press("enter")

            assert app.active_task == "restore"
            assert "Restore files" in workflow_support.static_text(app, "#canvas-title")

    asyncio.run(run())


def test_textual_app_palette_changes_shell_colors() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
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
        async with run_app_test(app, size=(120, 48)) as pilot:
            for key, (
                active_task,
                _review_label,
                focus_selector,
                blocker,
            ) in expected.items():
                await pilot.press(key)

                assert app.active_task == active_task
                assert workflow_support.button_label(app, "#canvas-primary") == "Continue >"
                assert not list(app.screen.query("#canvas-footer-hints"))
                assert blocker in workflow_support.preview_text(app)
                assert not list(app.screen.query("#preview-issues"))

                await pilot.press("ctrl+r")

                assert not list(app.screen.query("#review-modal"))
                assert app.screen.focused is app.query_one(focus_selector)
                if app.active_task in app.workflow_ui_states:
                    assert blocker in workflow_support.workspace_text(app)

    asyncio.run(run())


def test_textual_app_replacement_recovery_choice_uses_inline_quorum() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(100, 30)) as pilot:
            await pilot.press("5")
            mode = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-mode",
                OptionsEditor,
            )
            await workflow_support.select_guided_radio(
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

            await workflow_support.select_guided_radio(
                mode,
                pilot,
                "3 sheets; any 2 can restore (recommended)",
            )
            assert app.replace_recovery_docs_state.recovery_threshold == 2
            assert app.replace_recovery_docs_state.recovery_document_count == 3

    asyncio.run(run())


def test_textual_app_command_palette_commands_are_workflow_aware(tmp_path) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
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
            kit_commands = {command.title for command in app.get_system_commands(app.screen)}

            assert "Set PDF output" in kit_commands

            await pilot.press("7")
            settings_commands = {command.title for command in app.get_system_commands(app.screen)}

            assert {"Reset current section", "Reset all settings"} <= settings_commands

    asyncio.run(run())


def test_textual_app_keeps_pristine_backup_neutral_then_shows_selected_file_summary() -> None:
    async def run() -> None:
        app = EthernityApp(settings_state=SettingsTaskState.from_current(DEFAULT_CONFIG_PATH))
        async with run_app_test(app, size=(120, 48)) as pilot:
            assert not app.query_one("#backup-files-value").display
            assert not app.query_one("#backup-files-panel").display
            assert not app.query_one("#backup-destination-status").display
            assert workflow_support.static_text(app, "#backup-output-value") == ("backup-<id>")
            assert "Choose at least one file or folder to back up" in workflow_support.preview_text(
                app
            )

            await app.action_edit_primary()
            await workflow_support.choose_picker_paths(app, pilot, Path("README.md"))

            await _wait_for_condition(
                pilot,
                lambda: app.backup_state.current_estimate() is not None,
                "backup file and page estimate",
            )
            assert "1 file" in workflow_support.static_text(app, "#backup-files-value")
            assert app.query_one("#backup-files-panel").display
            assert "KiB" in workflow_support.static_text(app, "#backup-files-value")
            assert "About" in workflow_support.static_text(app, "#backup-output-summary")
            assert not app.query_one("#backup-destination-status").display
            assert workflow_support.static_text(app, "#backup-output-value") == ("backup-<id>")
            assert workflow_support.button_label(app, "#canvas-primary") == "Continue >"
            await pilot.press("ctrl+r")
            review_text = workflow_support.read_review_text(app)
            assert "Create backup documents in backup-<id>" in review_text
            assert "backup-<id>" in review_text
            assert "no output path is selected" not in review_text
            await pilot.click("#review-close")
            await pilot.pause()

            await app.action_edit_output()
            await workflow_support.save_picker_name(app, pilot, "backup-out")

            assert "1 file" in workflow_support.static_text(
                app,
                "#backup-files-value",
            )
            assert not app.query_one("#backup-destination-status").display
            assert workflow_support.button_label(app, "#canvas-primary") == "Continue >"
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
        async with run_app_test(app, size=(120, 48)) as pilot:
            await pilot.press("2")

            assert app.query_one("#workflow-restore-source-body", SourceChooser).display
            assert "Passphrase set" in workflow_support.workspace_text(app)
            assert app.query_one("#workflow-restore-destination-body-action", Button).label == (
                "Choose restore folder..."
            )
            assert not app.query_one(WorkbenchSummary).display
            assert workflow_support.button_label(app, "#canvas-primary") == "Continue >"
            assert "Choose where recovered files will be written." in workflow_support.preview_text(
                app
            )
            assert not list(app.screen.query("#preview"))

            await pilot.press("ctrl+r")

            assert not list(app.screen.query("#review-modal"))
            assert (
                "Error: Choose where recovered files will be written."
                in workflow_support.workspace_text(app)
            )
            assert app.screen.focused is app.query_one(
                "#workflow-restore-destination-body-action",
                Button,
            )

    asyncio.run(run())


def test_textual_app_help_is_contextual_and_concise() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("?")

            assert isinstance(app.screen, HelpScreen)
            assert workflow_support.static_text(app, "#help-title") == "Create backup"
            help_text = workflow_support.help_markdown_text(app)
            assert "## Create backup" not in help_text
            assert "Encrypt files and folders" in workflow_support.static_text(app, "#help-intro")
            assert help_text.count("### ") == 4
            assert "Enter or Space opens a dropdown" in help_text
            assert "new backup-<id> folder inside the selected destination" in help_text
            assert "Existing backups stay unchanged" in help_text
            assert "Store recovery sheets in separate places" in help_text
            assert "Scan at least one printed QR code" in help_text
            assert "Ctrl+R: Review" in workflow_support.static_text(app, "#help-shortcuts")
            assert not list(app.screen.query("#help-mode-index"))

            await pilot.press("escape")
            await pilot.press("2")
            await pilot.press("?")

            assert isinstance(app.screen, HelpScreen)
            assert workflow_support.static_text(app, "#help-title") == "Restore files"
            help_text = workflow_support.help_markdown_text(app)
            assert "## Restore files" not in help_text
            assert "Load the backup documents" in help_text
            assert "passphrase, recovery sheets, or recovery payload files" in help_text
            assert "Latest means the newest valid update in the documents you loaded" in help_text
            assert "cannot check for newer copies elsewhere" in help_text
            assert "Keep signature verification on" in help_text
            assert "Use an empty folder" in help_text

            await pilot.press("escape")
            await pilot.press("7")
            await pilot.press("?")

            assert isinstance(app.screen, HelpScreen)
            assert workflow_support.static_text(app, "#help-title") == "Settings"
            help_text = workflow_support.help_markdown_text(app)
            assert workflow_support.static_text(app, "#help-intro") == (
                "Set defaults for future workflows. Changes save immediately."
            )
            assert "Create backup uses a folder named for the backup ID" in help_text
            assert "Ctrl+R" not in workflow_support.static_text(app, "#help-shortcuts")

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
        async with run_app_test(app, size=(120, 32)) as pilot:
            await app.action_edit_primary()
            await pilot.pause()

            assert isinstance(app.screen, FilePickerScreen)
            picker = app.screen
            picker.set_selected_paths((Path("README.md"), Path("docs")))
            selected = picker.query_one("#file-picker-selected", SelectionList)
            selected.highlighted = 0
            selected.focus()

            await pilot.press("enter")

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
        async with run_app_test(app, size=(120, 32)) as pilot:
            command_titles = {command.title for command in app.get_system_commands(app.screen)}
            assert "Show backup diagnostics" in command_titles
            internals_button = app.query_one("#canvas-internals", Button)
            primary_button = app.query_one("#canvas-primary", Button)
            assert internals_button.display
            assert internals_button.region.x < primary_button.region.x
            assert workflow_support.button_label(app, "#canvas-internals") == "Diagnostics"

            await pilot.click("#canvas-internals")
            await pilot.pause()

            assert workflow_support.static_text(app, "#diagnostics-title") == "Backup diagnostics"
            tabs = app.screen.query_one("#diagnostics-tabs", TabbedContent)
            assert tabs.active == "diagnostics-tab-0"
            assert len(list(app.screen.query(TabPane))) == 9
            first_log = app.screen.query_one("#diagnostics-log-0", RichLog)
            assert app.screen.focused is first_log
            assert "Passphrase" in workflow_support.rich_log_text(first_log)
            assert "super secret" not in workflow_support.rich_log_text(first_log)

            tabs.active = "diagnostics-tab-1"
            await _wait_for_condition(
                pilot,
                lambda: bool(
                    workflow_support.rich_log_text(
                        app.screen.query_one("#diagnostics-log-1", RichLog)
                    )
                ),
                "manifest diagnostics to render",
            )

            manifest_log = app.screen.query_one("#diagnostics-log-1", RichLog)
            assert app.screen.focused is manifest_log
            assert manifest_log.highlight
            assert "created_at" in workflow_support.rich_log_text(manifest_log)
            assert "<masked bytes=" in workflow_support.rich_log_text(manifest_log)

            tabs.active = "diagnostics-tab-2"
            await _wait_for_condition(
                pilot,
                lambda: bool(
                    workflow_support.rich_log_text(
                        app.screen.query_one("#diagnostics-log-2", RichLog)
                    )
                ),
                "backup document diagnostics to render",
            )

            metadata_log = app.screen.query_one("#diagnostics-log-2", RichLog)
            assert app.screen.focused is metadata_log
            assert "manifest_cbor_bytes" in workflow_support.rich_log_text(metadata_log)
            assert '"cbor"' in workflow_support.rich_log_text(metadata_log)
            assert '"seed": "<masked bytes=' in workflow_support.rich_log_text(metadata_log)
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
                lambda: "super secret" in workflow_support.rich_log_text(first_log),
                "revealed diagnostics to render",
            )

            assert switch.value
            assert "super secret" in workflow_support.rich_log_text(first_log)
            assert '"seed": "<masked bytes=' not in workflow_support.rich_log_text(metadata_log)
            assert "00000000" not in workflow_support.rich_log_text(metadata_log)

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
        async with run_app_test(app, size=(120, 32)):
            command_titles = {command.title for command in app.get_system_commands(app.screen)}

            assert "Show backup diagnostics" not in command_titles
            assert not app.query_one("#canvas-internals", Button).display

    asyncio.run(run())


def test_textual_app_hides_diagnostics_until_backup_files_exist() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)):
            command_titles = {command.title for command in app.get_system_commands(app.screen)}

            assert "Show backup diagnostics" not in command_titles
            assert not list(app.screen.query("#preview-diagnostics"))

    asyncio.run(run())


def test_textual_app_supports_hjkl_and_arrow_navigation() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(160, 32)) as pilot:
            await pilot.pause()
            await pilot.press("h", "l")
            assert app.active_task == "backup"
            assert app.screen.focused is app.query_one("#nav-restore", Button)
            await pilot.press("enter")
            assert app.active_task == "restore"
            await pilot.press("h", "right", "down")
            assert app._nav_menu_open
            await pilot.press("j", "k", "enter")
            assert app.active_task == "add_files"
            await pilot.press("h", "left", "enter")
            assert app.active_task == "restore"
            await pilot.press("h", "left", "enter")
            assert app.active_task == "backup"
            assert app.screen.focused is app.query_one("#workspace-backup-files", Button)

    asyncio.run(run())


def test_textual_app_hjkl_leave_closed_selects_without_opening_them() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(160, 48)) as pilot:
            await pilot.press("6")

            select = app.query_one("#workspace-kit-variant-select", Select)
            select.focus()
            await pilot.press("j")

            assert not select.expanded
            assert app.screen.focused is app.query_one("#workspace-kit-paper", Select)
            await pilot.press("k")
            assert app.screen.focused is select
            assert not select.expanded

    asyncio.run(run())


def test_textual_app_splits_backup_files_and_folders() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await app.action_edit_primary()
            await workflow_support.choose_picker_paths(app, pilot, Path("README.md"), Path("docs"))

            assert [str(path) for path in app.backup_state.input_paths] == ["README.md"]
            assert [str(path) for path in app.backup_state.input_dirs] == ["docs"]

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
        async with run_app_test(app, size=(96, 40)) as pilot:
            backup_output_value = workflow_support.static_text(app, "#backup-output-value")
            backup_base_dir = workflow_support.static_text(app, "#backup-base-dir-value")
            assert "..." in backup_output_value
            assert "..." in backup_base_dir
            assert str(backup_output) not in backup_output_value
            assert str(long_root) not in backup_base_dir
            assert backup_output_value.endswith(str(Path("backup-output-folder") / "backup-<id>"))
            assert backup_base_dir.endswith("final-destination")

            await pilot.press("2")

            restore_value = app.query_one("#workflow-restore-destination-body-value", Input)
            assert restore_value.value == str(restore_output)

            await pilot.press("6")

            kit_value = workflow_support.static_text(app, "#kit-output-value")
            assert "..." in kit_value
            assert str(kit_output) not in kit_value
            assert kit_value.endswith("offline-recovery-kit.pdf")

    asyncio.run(run())
