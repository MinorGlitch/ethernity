from __future__ import annotations

from dataclasses import dataclass

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.doctor import DoctorTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState


@dataclass(slots=True)
class InitialTaskStates:
    backup: BackupTaskState
    restore: RestoreTaskState
    add_files: AddFilesTaskState
    rebuild: RebuildTaskState
    replace_recovery_docs: ReplaceRecoveryDocsTaskState
    kit: PrintKitTaskState
    doctor: DoctorTaskState
    settings: SettingsTaskState


def build_initial_task_states(
    *,
    backup_state: BackupTaskState | None,
    restore_state: RestoreTaskState | None,
    add_files_state: AddFilesTaskState | None,
    rebuild_state: RebuildTaskState | None,
    replace_recovery_docs_state: ReplaceRecoveryDocsTaskState | None,
    kit_state: PrintKitTaskState | None,
    doctor_state: DoctorTaskState | None,
    settings_state: SettingsTaskState | None,
) -> InitialTaskStates:
    return InitialTaskStates(
        backup=backup_state or BackupTaskState(),
        restore=restore_state or RestoreTaskState(),
        add_files=add_files_state or AddFilesTaskState(),
        rebuild=rebuild_state or RebuildTaskState(),
        replace_recovery_docs=replace_recovery_docs_state or ReplaceRecoveryDocsTaskState(),
        kit=kit_state or PrintKitTaskState(),
        doctor=doctor_state or DoctorTaskState(),
        settings=settings_state or SettingsTaskState.from_current(),
    )
