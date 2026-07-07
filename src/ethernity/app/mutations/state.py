from __future__ import annotations

from ethernity.app.app_context import EthernityAppContext
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.doctor import DoctorTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState


class TaskStateMutationActions(EthernityAppContext):
    def action_clear_task(self) -> None:
        if self.active_task == "backup":
            self.backup_state = BackupTaskState()
        elif self.active_task == "restore":
            self.restore_state = RestoreTaskState()
        elif self.active_task == "add_files":
            self.add_files_state = AddFilesTaskState()
        elif self.active_task == "rebuild":
            self.rebuild_state = RebuildTaskState()
        elif self.active_task == "replace_recovery_docs":
            self.replace_recovery_docs_state = ReplaceRecoveryDocsTaskState()
        elif self.active_task == "kit":
            self.kit_state = PrintKitTaskState()
        elif self.active_task == "doctor":
            self.doctor_state = DoctorTaskState()
        elif self.active_task == "settings":
            self.settings_state = SettingsTaskState.from_current()
        self._last_execution_result = None
        self.refresh_task_view()
