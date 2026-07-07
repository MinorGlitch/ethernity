from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import App, ComposeResult

from ethernity.app.app_state import InitialTaskStates, build_initial_task_states
from ethernity.app.app_types import ActiveTask
from ethernity.app.bindings import APP_BINDINGS, APP_SUB_TITLE, APP_TITLE
from ethernity.app.editing.actions import TaskEditingActions
from ethernity.app.events import AppEventHandlers
from ethernity.app.mutations.actions import TaskMutationActions
from ethernity.app.settings_controller import SettingsController
from ethernity.app.shell import compose_app_shell
from ethernity.app.task_view import TaskViewActions
from ethernity.tasks.models import TaskExecutionResult

if TYPE_CHECKING:
    from ethernity.tasks.add_files import AddFilesTaskState
    from ethernity.tasks.backup import BackupTaskState
    from ethernity.tasks.doctor import DoctorTaskState
    from ethernity.tasks.kit import PrintKitTaskState
    from ethernity.tasks.rebuild import RebuildTaskState
    from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
    from ethernity.tasks.restore import RestoreTaskState
    from ethernity.tasks.settings import SettingsTaskState


class EthernityApp(
    AppEventHandlers,
    TaskEditingActions,
    TaskMutationActions,
    TaskViewActions,
    App[None],
):
    """Terminal-first Ethernity application shell."""

    CSS_PATH = "theme.tcss"
    BINDINGS = APP_BINDINGS
    TITLE = APP_TITLE
    SUB_TITLE = APP_SUB_TITLE

    def __init__(
        self,
        backup_state: BackupTaskState | None = None,
        restore_state: RestoreTaskState | None = None,
        add_files_state: AddFilesTaskState | None = None,
        rebuild_state: RebuildTaskState | None = None,
        replace_recovery_docs_state: ReplaceRecoveryDocsTaskState | None = None,
        kit_state: PrintKitTaskState | None = None,
        doctor_state: DoctorTaskState | None = None,
        settings_state: SettingsTaskState | None = None,
    ) -> None:
        super().__init__()
        self.active_task: ActiveTask = "backup"
        self._install_task_states(
            build_initial_task_states(
                backup_state=backup_state,
                restore_state=restore_state,
                add_files_state=add_files_state,
                rebuild_state=rebuild_state,
                replace_recovery_docs_state=replace_recovery_docs_state,
                kit_state=kit_state,
                doctor_state=doctor_state,
                settings_state=settings_state,
            )
        )
        self.settings_controller = SettingsController(self)
        self._last_execution_result: TaskExecutionResult | None = None

    def compose(self) -> ComposeResult:
        yield from compose_app_shell()

    def _install_task_states(self, states: InitialTaskStates) -> None:
        self.backup_state = states.backup
        self.restore_state = states.restore
        self.add_files_state = states.add_files
        self.rebuild_state = states.rebuild
        self.replace_recovery_docs_state = states.replace_recovery_docs
        self.kit_state = states.kit
        self.doctor_state = states.doctor
        self.settings_state = states.settings
