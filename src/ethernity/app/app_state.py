from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeVar, cast

from pydantic import BaseModel

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState

TaskStateModel = TypeVar("TaskStateModel", bound=BaseModel)


@dataclass(slots=True)
class InitialTaskStates:
    backup: BackupTaskState
    restore: RestoreTaskState
    add_files: AddFilesTaskState
    rebuild: RebuildTaskState
    replace_recovery_docs: ReplaceRecoveryDocsTaskState
    kit: PrintKitTaskState
    settings: SettingsTaskState


def build_initial_task_states(
    *,
    backup_state: BackupTaskState | None,
    restore_state: RestoreTaskState | None,
    add_files_state: AddFilesTaskState | None,
    rebuild_state: RebuildTaskState | None,
    replace_recovery_docs_state: ReplaceRecoveryDocsTaskState | None,
    kit_state: PrintKitTaskState | None,
    settings_state: SettingsTaskState | None,
) -> InitialTaskStates:
    states = InitialTaskStates(
        backup=backup_state or BackupTaskState(),
        restore=restore_state or RestoreTaskState(),
        add_files=add_files_state or AddFilesTaskState(),
        rebuild=rebuild_state or RebuildTaskState(),
        replace_recovery_docs=replace_recovery_docs_state or ReplaceRecoveryDocsTaskState(),
        kit=kit_state or PrintKitTaskState(),
        settings=settings_state or SettingsTaskState.from_current(),
    )
    return apply_settings_defaults(states)


def apply_settings_defaults(states: InitialTaskStates) -> InitialTaskStates:
    """Resolve saved settings into workflow fields that the user has not edited."""

    settings = states.settings
    config_path = settings.config_path
    design = settings.design
    paper_size = settings.paper_size
    backup_shard_threshold = _positive_int(
        settings.setting_value("backup_shard_threshold"),
        fallback=2,
    )
    backup_shard_count = _positive_int(
        settings.setting_value("backup_shard_count"),
        fallback=3,
    )

    states.backup = _with_inherited_values(
        states.backup,
        {
            "config_path": config_path,
            "base_dir": settings.path_value("backup_base_dir"),
            "output_dir": settings.path_value("backup_output_dir"),
            "recovery_method": (
                "recommended_shards"
                if (backup_shard_threshold, backup_shard_count) == (2, 3)
                else "custom_shards"
            ),
            "shard_threshold": backup_shard_threshold,
            "shard_count": backup_shard_count,
            "signing_key_mode": settings.setting_value("backup_signing_key_mode") or "embedded",
            "signing_key_shard_threshold": _optional_positive_int(
                settings.setting_value("backup_signing_key_shard_threshold")
            ),
            "signing_key_shard_count": _optional_positive_int(
                settings.setting_value("backup_signing_key_shard_count")
            ),
            "paper_size": paper_size,
            "design": design,
        },
    )
    states.restore = _with_inherited_values(
        states.restore,
        {
            "config_path": config_path,
            "output_path": settings.path_value("recover_output"),
        },
    )
    states.add_files = _with_inherited_values(
        states.add_files,
        {
            "config_path": config_path,
            "base_dir": settings.path_value("extend_base_dir"),
            "unlock_policy": settings.setting_value("extend_unlock_policy") or "self-contained",
            "paper_size": paper_size,
            "design": design,
        },
    )
    states.rebuild = _with_inherited_values(
        states.rebuild,
        {
            "config_path": config_path,
            "paper_size": paper_size,
            "design": design,
        },
    )
    states.replace_recovery_docs = _with_inherited_values(
        states.replace_recovery_docs,
        {
            "config_path": config_path,
            "paper_size": paper_size,
            "design": design,
        },
    )
    states.kit = _with_inherited_values(
        states.kit,
        {
            "config_path": config_path,
            "paper_size": paper_size,
            "design": design,
        },
    )
    return states


def _with_inherited_values(
    state: TaskStateModel,
    values: Mapping[str, object],
) -> TaskStateModel:
    explicit_fields = set(state.model_fields_set)
    inherited_values = {
        field: value for field, value in values.items() if field not in explicit_fields
    }
    if not inherited_values:
        return state

    resolved_values = state.model_dump(mode="python")
    resolved_values.update(inherited_values)
    resolved = cast(TaskStateModel, state.__class__.model_validate(resolved_values))

    # Inherited values stay eligible for future settings changes. Any later assignment made by
    # the workflow editor is added to this set by Pydantic and becomes an explicit override.
    resolved.model_fields_set.clear()
    resolved.model_fields_set.update(explicit_fields)
    return resolved


def _positive_int(value: object, *, fallback: int) -> int:
    resolved = _optional_positive_int(value)
    return fallback if resolved is None else resolved


def _optional_positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
