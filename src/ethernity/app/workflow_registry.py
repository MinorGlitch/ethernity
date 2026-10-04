from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from ethernity.app.app_types import ActiveTask
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState
from ethernity.workflows.shared import api_codes

TaskStateFactory = Callable[[Path | None], BaseModel]


def _default_state(model: type[BaseModel]) -> TaskStateFactory:
    return lambda _settings_config_path: model()


def _settings_state(settings_config_path: Path | None) -> BaseModel:
    return SettingsTaskState.from_current(settings_config_path)


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    key: ActiveTask
    title: str
    nav_group: str
    shortcut: str
    state_attribute: str
    workspace_id: str | None
    initial_focus: str
    review_label: str
    execute_label: str
    state_factory: TaskStateFactory
    section_focus: tuple[tuple[str, str], ...] = ()
    issue_focus: tuple[tuple[str, str], ...] = ()

    def focus_for_section(self, section: str | None) -> str:
        if section is None:
            return self.initial_focus
        return dict(self.section_focus).get(section, self.initial_focus)

    def focus_for_issue(self, code: str, section: str | None) -> str:
        return dict(self.issue_focus).get(code, self.focus_for_section(section))

    def fresh_state(self, *, settings_config_path: Path | None = None) -> BaseModel:
        return self.state_factory(settings_config_path)


WORKFLOWS: tuple[WorkflowDefinition, ...] = (
    WorkflowDefinition(
        key="backup",
        title="Create backup",
        nav_group="Start",
        shortcut="1",
        state_attribute="backup_state",
        workspace_id="backup-workspace",
        initial_focus="#workspace-backup-files",
        review_label="Review backup",
        execute_label="Create backup",
        state_factory=_default_state(BackupTaskState),
        section_focus=(
            ("files", "#workspace-backup-files"),
            ("output", "#workspace-backup-output"),
            ("recovery", "#workspace-backup-recovery-method"),
            ("signature", "#workspace-backup-signing-key-mode"),
            ("layout", "#workspace-backup-paper-size"),
            ("advanced", "#workspace-backup-passphrase"),
        ),
        issue_focus=(
            ("BACKUP_CUSTOM_QR_DENSITY", "#workspace-backup-qr-chunk-size"),
            (
                "BACKUP_SIGNING_KEY_QUORUM_INCOMPLETE",
                "#workspace-backup-signing-key-mode",
            ),
            (
                "BACKUP_SIGNING_KEY_QUORUM_MODE_REQUIRED",
                "#workspace-backup-signing-key-mode",
            ),
            (
                "BACKUP_SIGNING_KEY_SHARDS_REQUIRE_RECOVERY_DOCS",
                "#workspace-backup-recovery-method",
            ),
        ),
    ),
    WorkflowDefinition(
        key="restore",
        title="Restore files",
        nav_group="Start",
        shortcut="2",
        state_attribute="restore_state",
        workspace_id="restore-workspace",
        initial_focus="#workflow-restore-source-body-load",
        review_label="Review restore",
        execute_label="Restore files",
        state_factory=_default_state(RestoreTaskState),
        section_focus=(
            ("source", "#workflow-restore-source-body-load"),
            ("unlock", "#workflow-restore-unlock-body-methods"),
            ("target", "#workflow-restore-target-body-choices"),
            ("authentication", "#workspace-restore-auth-policy"),
            ("output", "#workflow-restore-destination-body-action"),
        ),
        issue_focus=(
            (
                "RESTORE_RECOVERY_TEXT_INVALID",
                "#workflow-restore-source-body-load",
            ),
            ("RESTORE_UPDATE_REQUIRED", "#workflow-restore-target-body-choices"),
            ("RESTORE_SIGNATURE_SOURCE_CONFLICT", "#workspace-restore-signature-source"),
        ),
    ),
    WorkflowDefinition(
        key="add_files",
        title="Add files to backup",
        nav_group="Loaded backup",
        shortcut="3",
        state_attribute="add_files_state",
        workspace_id="add_files-workspace",
        initial_focus="#workflow-add_files-source-body-load",
        review_label="Review update",
        execute_label="Create update",
        state_factory=_default_state(AddFilesTaskState),
        section_focus=(
            ("source", "#workflow-add_files-source-body-load"),
            ("files", "#workspace-add-files-add-files"),
            ("unlock", "#workflow-add_files-unlock-body-unlock-methods"),
            ("freshness", "#workspace-add-files-fingerprint"),
            ("output", "#workspace-add-files-output"),
            ("advanced", "#workspace-add-files-base-dir"),
        ),
        issue_focus=(
            ("ADD_FILES_CUSTOM_QR_DENSITY", "#workspace-add-files-qr-chunk-size"),
            (
                api_codes.ADD_FILES_RECOVERY_OUTPUT_EXISTS,
                "#workspace-add-files-recovery-sheets",
            ),
        ),
    ),
    WorkflowDefinition(
        key="rebuild",
        title="Rebuild backup",
        nav_group="Loaded backup",
        shortcut="4",
        state_attribute="rebuild_state",
        workspace_id="rebuild-workspace",
        initial_focus="#workflow-rebuild-source-body-load",
        review_label="Review rebuild",
        execute_label="Rebuild backup",
        state_factory=_default_state(RebuildTaskState),
        section_focus=(
            ("source", "#workflow-rebuild-source-body-load"),
            ("unlock", "#workflow-rebuild-unlock-body-unlock-methods"),
            ("freshness", "#workspace-rebuild-fingerprint"),
            ("output", "#workflow-rebuild-output-body-destination-action"),
            ("advanced", "#workspace-rebuild-qr-chunk-size"),
        ),
        issue_focus=(
            ("REBUILD_HEAD_TRUST_REQUIRED", "#workspace-rebuild-fingerprint"),
            ("REBUILD_CUSTOM_QR_DENSITY", "#workspace-rebuild-qr-chunk-size"),
            ("REBUILD_SIGNATURE_SOURCE_CONFLICT", "#workspace-rebuild-signature-source"),
        ),
    ),
    WorkflowDefinition(
        key="replace_recovery_docs",
        title="Create replacement recovery sheets",
        nav_group="Loaded backup",
        shortcut="5",
        state_attribute="replace_recovery_docs_state",
        workspace_id="replace_recovery_docs-workspace",
        initial_focus="#workflow-replace_recovery_docs-source-body-source-load",
        review_label="Review replacement sheets",
        execute_label="Create replacement sheets",
        state_factory=_default_state(ReplaceRecoveryDocsTaskState),
        section_focus=(
            ("source", "#workflow-replace_recovery_docs-source-body-source-load"),
            ("unlock", "#workflow-replace_recovery_docs-unlock-body-methods"),
            ("freshness", "#workspace-replace-fingerprint"),
            ("output", "#workflow-replace_recovery_docs-output-body-destination-action"),
            ("recovery", "#workflow-replace_recovery_docs-recovery-body-mode-choices"),
            ("signature", "#workspace-replace-signing-key-select"),
        ),
        issue_focus=(
            (
                "REPLACE_RECOVERY_TEXT_INVALID",
                "#workflow-replace_recovery_docs-source-body-source-load",
            ),
            ("REPLACE_RECOVERY_HEAD_TRUST_REQUIRED", "#workspace-replace-fingerprint"),
            (
                "REPLACE_RECOVERY_SIGNING_KEY_QUORUM_REQUIRED",
                "#workspace-replace-signing-key-select",
            ),
            (
                "REPLACE_RECOVERY_DOCUMENT_TYPE_REQUIRED",
                "#workspace-replace-passphrase-select",
            ),
            (
                "REPLACE_RECOVERY_PASSPHRASE_REPLACEMENT_DISABLED",
                "#workspace-replace-passphrase-select",
            ),
            (
                "REPLACE_RECOVERY_PASSPHRASE_REPLACEMENT_INPUT_REQUIRED",
                "#workspace-replace-unlock",
            ),
            (
                "REPLACE_RECOVERY_SIGNING_KEY_REPLACEMENT_INPUT_REQUIRED",
                "#workspace-replace-signing-key-payloads",
            ),
        ),
    ),
    WorkflowDefinition(
        key="kit",
        title="Create offline recovery kit",
        nav_group="Tools",
        shortcut="6",
        state_attribute="kit_state",
        workspace_id="kit-workspace",
        initial_focus="#workspace-kit-output",
        review_label="Review PDF",
        execute_label="Create PDF",
        state_factory=_default_state(PrintKitTaskState),
        section_focus=(
            ("output", "#workspace-kit-output"),
            ("layout", "#workspace-kit-paper"),
            ("variant", "#workspace-kit-variant-select"),
            ("qr", "#workspace-kit-chunk-size"),
        ),
        issue_focus=(("KIT_CUSTOM_QR_SIZING", "#workspace-kit-chunk-size"),),
    ),
    WorkflowDefinition(
        key="settings",
        title="Settings",
        nav_group="Tools",
        shortcut="7",
        state_attribute="settings_state",
        workspace_id=None,
        initial_focus="#setting-control-render_style",
        review_label="Save",
        execute_label="Save settings",
        state_factory=_settings_state,
    ),
)

WORKFLOW_BY_KEY = {workflow.key: workflow for workflow in WORKFLOWS}
WORKFLOW_GROUPS = tuple(dict.fromkeys(workflow.nav_group for workflow in WORKFLOWS))


def workflow_definition(task: ActiveTask) -> WorkflowDefinition:
    return WORKFLOW_BY_KEY[task]


def workflows_in_group(group: str) -> tuple[WorkflowDefinition, ...]:
    return tuple(workflow for workflow in WORKFLOWS if workflow.nav_group == group)


def nav_option_indices() -> dict[ActiveTask, int]:
    indices: dict[ActiveTask, int] = {}
    index = 0
    for group in WORKFLOW_GROUPS:
        index += 1
        for workflow in workflows_in_group(group):
            indices[workflow.key] = index
            index += 1
    return indices
