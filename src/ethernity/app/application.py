from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from textual.app import ComposeResult, SystemCommand
from textual.screen import Screen
from textual.theme import Theme

from ethernity.app.app_state import (
    InitialTaskStates,
    apply_settings_defaults,
    build_initial_task_states,
)
from ethernity.app.app_types import ActiveTask
from ethernity.app.bindings import APP_BINDINGS, APP_SUB_TITLE, APP_TITLE
from ethernity.app.editing.actions import TaskEditingActions
from ethernity.app.events import AppEventHandlers
from ethernity.app.execution_controller import ExecutionController
from ethernity.app.mutations.actions import TaskMutationActions
from ethernity.app.output_paths import open_folder, single_output_folder
from ethernity.app.settings_controller import SettingsController
from ethernity.app.shell import compose_app_shell
from ethernity.app.source_assessment_controller import SourceAssessmentController
from ethernity.app.task_catalog import review_label
from ethernity.app.task_view import TaskViewActions
from ethernity.app.workflow_presenter import initial_workflow_ui_states
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState

ETHERNITY_DARK_THEME = Theme(
    name="ethernity-dark",
    primary="#55AFA5",
    secondary="#78BDB5",
    accent="#9FC9C3",
    foreground="#ECE9E1",
    background="#171A1B",
    surface="#202526",
    panel="#2A3031",
    warning="#D4A64A",
    error="#D16C72",
    success="#75A987",
    variables={
        "border": "#607170",
        "border-blurred": "#384342",
        "button-color-foreground": "#111718",
        "button-focus-text-style": "bold",
        "footer-background": "#202526",
        "footer-key-foreground": "#55AFA5",
        "input-selection-background": "#55AFA5 35%",
    },
)

ETHERNITY_LIGHT_THEME = Theme(
    name="ethernity-light",
    primary="#267B73",
    secondary="#3E8D85",
    accent="#226D66",
    foreground="#272A2A",
    background="#F3F0E9",
    surface="#E8E5DE",
    panel="#DCD9D2",
    warning="#9A6B13",
    error="#A8474F",
    success="#4D7C5B",
    dark=False,
    variables={
        "border": "#71817F",
        "border-blurred": "#BBC3C1",
        "button-color-foreground": "#F8F6F0",
        "button-focus-text-style": "bold",
        "footer-background": "#E8E5DE",
        "footer-key-foreground": "#267B73",
        "input-selection-background": "#267B73 25%",
    },
)


class EthernityApp(
    AppEventHandlers,
    TaskEditingActions,
    TaskMutationActions,
    TaskViewActions,
):
    """Terminal-first Ethernity application shell."""

    CSS_PATH = "theme.tcss"
    BINDINGS = APP_BINDINGS
    TITLE = APP_TITLE
    SUB_TITLE = APP_SUB_TITLE
    HORIZONTAL_BREAKPOINTS = [
        (0, "-ethernity-narrow"),
        (88, "-ethernity-standard"),
        (132, "-ethernity-wide"),
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
        super().__init__()
        self.register_theme(ETHERNITY_DARK_THEME)
        self.register_theme(ETHERNITY_LIGHT_THEME)
        if self.theme == "textual-dark":
            self.theme = ETHERNITY_DARK_THEME.name
        elif self.theme in {ETHERNITY_DARK_THEME.name, ETHERNITY_LIGHT_THEME.name}:
            requested_theme = self.theme
            self.theme = "textual-dark"
            self.theme = requested_theme
        self.active_task: ActiveTask = "backup"
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
        self._preparing_review_task: ActiveTask | None = None
        self.workflow_ui_states = initial_workflow_ui_states()
        self.source_assessment_controller = SourceAssessmentController(self)
        self._nav_drawer_open = False
        self._nav_rendered_task: ActiveTask | None = None
        self._nav_return_focus_id: str | None = None
        self._nav_return_focus_task: ActiveTask | None = None
        self._nav_focus_generation = 0

    def _task_payloads(self) -> dict[ActiveTask, str]:
        return {
            task: getattr(self, f"{task}_state").model_dump_json()
            for task in (
                "backup",
                "restore",
                "add_files",
                "rebuild",
                "replace_recovery_docs",
                "kit",
                "settings",
            )
        }

    def _nav_should_collapse(self) -> bool:
        """Keep navigation responsive to the same app-level layout contract as TCSS."""

        return self.size.width < 132 or self.size.height < 28

    @property
    def _running_task(self) -> ActiveTask | None:
        """Compatibility view used by settings while writes are locked."""

        return self.execution_controller.running_task

    def compose(self) -> ComposeResult:
        yield from compose_app_shell()

    def action_focus_next(self) -> None:
        """Keep Tab from moving focus underneath an open navigation drawer."""

        if self._nav_drawer_open and self.screen is self.screen_stack[0]:
            self._close_nav_drawer()
            return
        self.screen.focus_next()

    def action_focus_previous(self) -> None:
        """Keep Shift+Tab symmetric with forward traversal around the drawer."""

        if self._nav_drawer_open and self.screen is self.screen_stack[0]:
            self._close_nav_drawer()
            return
        self.screen.focus_previous()

    def get_system_commands(self, screen: Screen[object]) -> Iterable[SystemCommand]:
        del screen
        yield SystemCommand(
            "Quit Ethernity",
            "Close the application",
            self.action_quit,
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
            yield SystemCommand(
                "Reset current tab",
                "Reset settings in the focused tab",
                self.settings_controller.reset_selected_group,
            )
            yield SystemCommand(
                "Reset all settings",
                "Return every setting to its default value",
                self.settings_controller.request_reset_all,
            )
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
            if self.add_files_state.source_paths:
                yield SystemCommand(
                    "Set update output",
                    "Choose a new or empty folder for scan-based update documents",
                    self.action_edit_output,
                )
            else:
                yield SystemCommand(
                    "Set backup folder",
                    "Use the folder containing the current backup",
                    self.action_edit_output,
                )
            yield SystemCommand(
                "Load backup pages",
                "Use scanned pages as the current backup source",
                self._edit_add_files_current_source,
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
        self.backup_state = states.backup
        self.restore_state = states.restore
        self.add_files_state = states.add_files
        self.rebuild_state = states.rebuild
        self.replace_recovery_docs_state = states.replace_recovery_docs
        self.kit_state = states.kit
        self.settings_state = states.settings

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
