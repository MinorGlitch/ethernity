from __future__ import annotations

from collections.abc import Iterable
from functools import partial
from pathlib import Path

from textual.app import ComposeResult, SystemCommand
from textual.screen import Screen
from textual.theme import Theme

from ethernity.app.app_state import (
    InitialTaskStates,
    apply_settings_defaults,
    build_initial_task_states,
)
from ethernity.app.backup_context import LoadedBackupContext
from ethernity.app.backup_estimate_controller import BackupEstimateController
from ethernity.app.bindings import APP_BINDINGS, APP_SUB_TITLE, APP_TITLE
from ethernity.app.editing.actions import TaskEditingActions
from ethernity.app.events import AppEventHandlers
from ethernity.app.execution import ReviewedTask
from ethernity.app.execution_controller import ExecutionController
from ethernity.app.mutations.actions import TaskMutationActions
from ethernity.app.navigation import NavMenu
from ethernity.app.output_paths import open_folder, single_output_folder
from ethernity.app.recovery_check_controller import RecoveryCheckController
from ethernity.app.settings_controller import SettingsController
from ethernity.app.shell import compose_app_shell
from ethernity.app.source_assessment_controller import SourceAssessmentController
from ethernity.app.task_catalog import review_label
from ethernity.app.task_view import TaskViewActions
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.app.workflow_presenter import initial_workflow_ui_states
from ethernity.app.workflow_registry import WORKFLOWS
from ethernity.security import prepare_disposable_worker_runtime
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState
from ethernity.tasks.task_types import TaskKey

_TASK_COMMAND_DESCRIPTIONS: dict[TaskKey, str] = {
    "backup": "Create paper backup documents for selected files",
    "restore": "Recover files from backup documents",
    "add_files": "Add or replace files in an existing backup",
    "rebuild": "Create a standalone backup from the loaded history",
    "replace_recovery_docs": "Create new recovery sheets for an existing backup",
    "kit": "Print the reusable offline recovery tool",
    "settings": "Change saved defaults",
}

ETHERNITY_DARK_THEME = Theme(
    name="ethernity-dark",
    primary="#E0B56D",
    secondary="#C9BA93",
    accent="#E8D7AE",
    foreground="#EAE6DA",
    background="#171918",
    surface="#20231F",
    panel="#2A2E26",
    warning="#F0A06A",
    error="#EB879B",
    success="#8CCBAD",
    variables={
        "text": "#EAE6DA",
        "text-muted": "#A7AA99",
        "text-disabled": "#74796B",
        "text-primary": "#E0B56D",
        "text-warning": "#F0A06A",
        "text-error": "#EB879B",
        "text-success": "#8CCBAD",
        "button-foreground": "#EAE6DA",
        "block-cursor-foreground": "#1C211A",
        "block-cursor-text-style": "none",
        "footer-description-foreground": "#A7AA99",
        "border": "#777B69",
        "border-blurred": "#3B3E34",
        "button-color-foreground": "#1C211A",
        "button-focus-text-style": "bold",
        "footer-background": "#20231F",
        "footer-key-foreground": "#E0B56D",
        "input-selection-background": "#E0B56D 35%",
    },
)

ETHERNITY_LIGHT_THEME = Theme(
    name="ethernity-light",
    primary="#805818",
    secondary="#74694D",
    accent="#805818",
    foreground="#2C3028",
    background="#F4F0E6",
    surface="#EAE5D9",
    panel="#DDD6C7",
    warning="#A64719",
    error="#AD2F49",
    success="#25694D",
    dark=False,
    variables={
        "text": "#2C3028",
        "text-muted": "#656959",
        "text-disabled": "#959889",
        "text-primary": "#805818",
        "text-warning": "#A64719",
        "text-error": "#AD2F49",
        "text-success": "#25694D",
        "button-foreground": "#2C3028",
        "block-cursor-foreground": "#FFFAF0",
        "block-cursor-text-style": "none",
        "footer-description-foreground": "#656959",
        "border": "#797A69",
        "border-blurred": "#CDC6B6",
        "button-color-foreground": "#FFFAF0",
        "button-focus-text-style": "bold",
        "footer-background": "#EAE5D9",
        "footer-key-foreground": "#805818",
        "input-selection-background": "#805818 25%",
    },
)


class EthernityApp(
    AppEventHandlers,
    TaskEditingActions,
    TaskMutationActions,
    TaskViewActions,
):
    """Terminal-first Ethernity application shell."""

    BINDINGS = APP_BINDINGS
    TITLE = APP_TITLE
    SUB_TITLE = APP_SUB_TITLE
    HORIZONTAL_BREAKPOINTS = [
        (0, "-ethernity-narrow"),
        (110, "-ethernity-standard"),
        (150, "-ethernity-wide"),
    ]
    VERTICAL_BREAKPOINTS = [
        (0, "-ethernity-short"),
        (28, "-ethernity-tall"),
    ]

    def __init__(
        self,
        backup_state: BackupTaskState | None = None,
        restore_state: RestoreTaskState | None = None,
        add_files_state: AddFilesTaskState | None = None,
        rebuild_state: RebuildTaskState | None = None,
        replace_recovery_docs_state: ReplaceRecoveryDocsTaskState | None = None,
        kit_state: PrintKitTaskState | None = None,
        settings_state: SettingsTaskState | None = None,
    ) -> None:
        prepare_disposable_worker_runtime()
        super().__init__()
        self.register_theme(ETHERNITY_DARK_THEME)
        self.register_theme(ETHERNITY_LIGHT_THEME)
        if self.theme == "textual-dark":
            self.theme = ETHERNITY_DARK_THEME.name
        elif self.theme in {ETHERNITY_DARK_THEME.name, ETHERNITY_LIGHT_THEME.name}:
            requested_theme = self.theme
            self.theme = "textual-dark"
            self.theme = requested_theme
        self.active_task: TaskKey = "backup"
        self._install_task_states(
            build_initial_task_states(
                backup_state=backup_state,
                restore_state=restore_state,
                add_files_state=add_files_state,
                rebuild_state=rebuild_state,
                replace_recovery_docs_state=replace_recovery_docs_state,
                kit_state=kit_state,
                settings_state=settings_state,
            )
        )
        self._initial_task_payloads = self._task_payloads()
        self.execution_controller = ExecutionController(self)
        self.settings_controller = SettingsController(self)
        self._last_execution_result: TaskExecutionResult | None = None
        self._last_reviewed_task: ReviewedTask | None = None
        self._review_edit_task: TaskKey | None = None
        self._preparing_review_task: TaskKey | None = None
        self.workflow_ui_states = initial_workflow_ui_states()
        self.source_assessment_controller = SourceAssessmentController(self)
        self.backup_estimate_controller = BackupEstimateController(self)
        self.recovery_check_controller = RecoveryCheckController(self)
        self._nav_menu_open = False
        self._loaded_backup_context: LoadedBackupContext | None = None
        self._nav_menu: NavMenu = "manage"

    def _task_payloads(self) -> dict[TaskKey, str]:
        return {
            workflow.key: getattr(self, workflow.state_attribute).model_dump_json()
            for workflow in WORKFLOWS
        }

    @property
    def running_task(self) -> TaskKey | None:
        """Task whose reviewed snapshot currently owns the execution worker."""
        return self.execution_controller.running_task

    def compose(self) -> ComposeResult:
        yield from compose_app_shell()

    def on_unmount(self) -> None:
        self.backup_estimate_controller.close()
        self.recovery_check_controller.close()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self.running_task is not None and action in {
            "command_palette",
            "help",
            "diagnostics",
        }:
            return False
        if action == "close_navigation":
            return self._nav_menu_open
        if action == "open_navigation":
            return True if self.screen is self.screen_stack[0] else None
        return super().check_action(action, parameters)

    def action_open_navigation(self) -> None:
        if self.screen is not self.screen_stack[0]:
            return
        self._close_nav_menu(restore_focus=False)
        self._focus_top_navigation()

    def _focus_top_navigation(self) -> None:
        if not self._nav_menu_open and self.screen is self.screen_stack[0]:
            self.screen.set_focus(self.query_one("#workbench-navigation Button.active-task"))

    def action_focus_next(self) -> None:
        """Keep Tab from moving focus underneath an open menu."""

        if self._nav_menu_open and self.screen is self.screen_stack[0]:
            self._close_nav_menu()
            return
        self.screen.focus_next()

    def action_focus_previous(self) -> None:
        """Keep Shift+Tab symmetric with forward traversal around the menu."""

        if self._nav_menu_open and self.screen is self.screen_stack[0]:
            self._close_nav_menu()
            return
        self.screen.focus_previous()

    def get_system_commands(self, screen: Screen[object]) -> Iterable[SystemCommand]:
        del screen
        yield SystemCommand(
            "Quit Ethernity",
            "Close the application",
            self.action_quit,
        )
        for workflow in WORKFLOWS:
            yield SystemCommand(
                workflow.title,
                _TASK_COMMAND_DESCRIPTIONS[workflow.key],
                partial(self._show_task, workflow.key),
            )
        yield from self._workflow_system_commands()

    def _workflow_system_commands(self) -> Iterable[SystemCommand]:
        yield SystemCommand(
            "Help for this screen",
            "Guidance and keyboard shortcuts",
            self.action_help,
        )
        if self._last_output_folder() is not None:
            yield SystemCommand(
                "Open output folder",
                "Open the folder from the last completed task",
                self.action_open_output_folder,
            )
        if self._internals_button_enabled() and self._diagnostics_available():
            yield SystemCommand(
                "Show backup diagnostics",
                "View redacted details for the current backup",
                self.action_diagnostics,
            )
        if self.active_task == "settings":
            yield from self._settings_system_commands()
            return
        validation = self._current_state().validate_task()
        if validation.ready:
            yield SystemCommand(
                review_label(self.active_task),
                "Review changes before files are written",
                self.action_review,
            )
        else:
            yield SystemCommand(
                "Go to first problem",
                "Focus the first missing or invalid field",
                self.action_review,
            )

        yield from self._task_edit_system_commands()

    def _task_edit_system_commands(self) -> Iterable[SystemCommand]:
        if self.active_task == "backup":
            yield SystemCommand(
                "Add backup files",
                "Select files or folders",
                self.action_edit_primary,
            )
            yield SystemCommand(
                "Set output folder",
                "Override the automatic folder named for the backup ID",
                self.action_edit_output,
            )
        elif self.active_task == "restore":
            yield SystemCommand(
                "Load backup pages",
                "Use a backup folder, or scanned pages from PDFs, images, or folders",
                self.action_edit_primary,
            )
            yield SystemCommand(
                "Paste recovery text",
                "Use the MAIN block from a recovery sheet",
                self._edit_restore_recovery_text_source,
            )
            yield SystemCommand(
                "Load backup payload",
                "Use a payload exported from backup documents",
                self._edit_restore_payloads_source,
            )
            yield SystemCommand(
                "Change unlock method",
                "Use a passphrase, recovery sheets, or recovery payload files",
                self._edit_current_unlock,
            )
            yield SystemCommand(
                "Set latest fingerprint",
                "Check the latest loaded version against a trusted fingerprint",
                self._edit_expected_head_fingerprint,
            )
            yield SystemCommand(
                "Set restore folder",
                "Recovered files will be written here",
                self.action_edit_output,
            )
        elif self.active_task == "add_files":
            yield SystemCommand(
                "Add or replace files",
                "Select files or folders for this update",
                self.action_edit_primary,
            )
            yield SystemCommand(
                "Load backup documents",
                "Use PDFs, scans, images, or folders of documents",
                self._edit_add_files_source,
            )
            yield SystemCommand(
                "Paste recovery text",
                "Use recovery blocks for the original backup and required updates",
                self._edit_add_files_recovery_text_source,
            )
            yield SystemCommand(
                "Load backup payload",
                "Use payloads exported from the backup documents",
                self._edit_add_files_payloads_source,
            )
            yield SystemCommand(
                "Set update output folder",
                "Save new update documents to a separate folder",
                self.action_edit_output,
            )
            yield SystemCommand(
                "Change unlock method",
                "Use a passphrase, recovery sheets, or recovery payload files",
                self._edit_current_unlock,
            )
            yield SystemCommand(
                "Set latest fingerprint",
                "Check the latest loaded version against a trusted fingerprint",
                self._edit_expected_head_fingerprint,
            )
        elif self.active_task in {"rebuild", "replace_recovery_docs"}:
            yield SystemCommand(
                "Load existing backup",
                "Use a backup folder, or scanned pages from PDFs, images, or folders",
                self.action_edit_primary,
            )
            if self.active_task == "replace_recovery_docs":
                yield SystemCommand(
                    "Paste recovery text",
                    "Use the MAIN block from an existing recovery sheet",
                    self._edit_replace_recovery_text_source,
                )
                yield SystemCommand(
                    "Load backup payload",
                    "Use a payload exported from the existing backup documents",
                    self._edit_replace_payloads_source,
                )
            yield SystemCommand(
                "Change unlock method",
                "Use a passphrase, recovery sheets, or recovery payload files",
                self._edit_current_unlock,
            )
            yield SystemCommand(
                "Set latest fingerprint",
                "Check the latest loaded version against a trusted fingerprint",
                self._edit_expected_head_fingerprint,
            )
            yield SystemCommand(
                "Set output folder",
                "New documents will be written here",
                self.action_edit_output,
            )
        elif self.active_task == "kit":
            yield SystemCommand(
                "Set PDF output",
                "Choose the filename and folder",
                self.action_edit_output,
            )

    def _settings_system_commands(self) -> Iterable[SystemCommand]:
        group = self.query_one(SettingsForm).active_group
        if group != "Config file":
            yield SystemCommand(
                "Reset current section",
                "Restore defaults for this settings category",
                partial(self.settings_controller.reset_group, group),
            )
        yield SystemCommand(
            "Reset all settings",
            "Return every setting to its default value",
            self.settings_controller.request_reset_all,
        )
        return

    def action_open_output_folder(self) -> None:
        folder = self._last_output_folder()
        if folder is None:
            self.notify("No output folder is available.", severity="warning")
            return
        try:
            open_folder(folder)
        except OSError as exc:
            self.notify(f"Could not open folder: {exc}", severity="error")
            return
        self.notify("Opening output folder.")

    def _last_output_folder(self) -> Path | None:
        result = self._last_execution_result
        if result is None or not result.ok or not result.output_paths:
            return None
        return single_output_folder(result.output_paths)

    def _install_task_states(self, states: InitialTaskStates) -> None:
        for workflow in WORKFLOWS:
            setattr(self, workflow.state_attribute, getattr(states, workflow.key))

    def _rehydrate_workflow_defaults(self) -> None:
        self._install_task_states(
            apply_settings_defaults(
                InitialTaskStates(
                    backup=self.backup_state,
                    restore=self.restore_state,
                    add_files=self.add_files_state,
                    rebuild=self.rebuild_state,
                    replace_recovery_docs=self.replace_recovery_docs_state,
                    kit=self.kit_state,
                    settings=self.settings_state,
                )
            )
        )
