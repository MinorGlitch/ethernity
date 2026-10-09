from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel

from ethernity.app import workflow_presenter
from ethernity.app.editing import definitions as editors
from ethernity.app.screens.file_picker import FilePickerMode
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.tasks import task_types
from ethernity.tasks.models import TaskValidation
from ethernity.tasks.presentation.models import SummaryPresentation, WorkflowPresentation
from ethernity.tasks.presentation.registry import task_presenter
from ethernity.tasks.settings import SettingsTaskState
from ethernity.tasks.task_types import TaskKey, TaskState
from ethernity.workflows.shared import issue_codes

TaskStateFactory = Callable[[Path | None], BaseModel]
GuidedBuilder = Callable[
    [TaskState, TaskValidation, WorkflowUiState, SummaryPresentation, str], WorkflowPresentation
]


State = TypeVar("State", bound=BaseModel)


def _guided_builder(
    model: type[State],
    build: Callable[
        [State, TaskValidation, WorkflowUiState, SummaryPresentation, str], WorkflowPresentation
    ],
) -> GuidedBuilder:
    return lambda state, validation, ui, summary, label: build(
        task_types.require_state(state, model), validation, ui, summary, label
    )


def _default_state(task: TaskKey) -> TaskStateFactory:
    return lambda _settings_config_path: task_presenter(task).state_type()


def _settings_state(settings_config_path: Path | None) -> BaseModel:
    return SettingsTaskState.from_current(settings_config_path)


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    key: TaskKey
    title: str
    nav_group: str
    shortcut: str
    state_attribute: str
    workspace_id: str | None
    initial_focus: str
    review_label: str
    execute_label: str
    state_factory: TaskStateFactory
    primary_editor: editors.PathEditorDefinition | str | None = None
    output_editor: editors.OutputEditorDefinition | str | None = None
    passphrase_editor: editors.PassphraseEditorDefinition | str | None = None
    workspace_prefix: str | None = None
    unlock_selector: str | None = None
    qr_size_attribute: Literal["qr_chunk_size", "chunk_size"] | None = None
    guided_builder: GuidedBuilder | None = None
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


BACKUP_DOCUMENT_PROMPT = (
    "Choose original PDFs, scanned pages, images, or folders. "
    "Include recovery sheets if you have them."
)
BACKUP_PARENT_PROMPT = "Choose a parent folder. A new backup-<id> folder will be created inside it."
BACKUP_PASSPHRASE_PROMPT = "Enter the passphrase for this backup."


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
        state_factory=_default_state("backup"),
        qr_size_attribute="qr_chunk_size",
        primary_editor=editors.PathEditorDefinition(
            "Backup files",
            "Add files or folders. Folder contents are included.",
            lambda host: (*host.backup_state.input_paths, *host.backup_state.input_dirs),
            lambda host: host._editor_callbacks._apply_backup_files_picked,
        ),
        output_editor=editors.OutputEditorDefinition(
            "Backup output",
            f"{BACKUP_PARENT_PROMPT} Clear uses the current folder.",
            "output_dir",
            lambda host: host._editor_callbacks._apply_backup_output_picked,
            "parent-folder",
        ),
        passphrase_editor=editors.PassphraseEditorDefinition(
            "Backup passphrase",
            "Leave blank to generate a strong passphrase.",
            lambda host: host._editor_callbacks._apply_backup_passphrase,
        ),
        workspace_prefix="workspace-backup-",
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
        state_factory=_default_state("restore"),
        primary_editor=editors.PathEditorDefinition(
            "Load backup documents",
            BACKUP_DOCUMENT_PROMPT,
            lambda host: host.restore_state.source_paths,
            lambda host: host._editor_callbacks._apply_restore_sources_picked,
        ),
        output_editor=editors.OutputEditorDefinition(
            "Restore destination",
            "Recovered files will be written here.",
            "output_path",
            lambda host: host._editor_callbacks._apply_restore_output_picked,
            "recovered",
        ),
        passphrase_editor=editors.PassphraseEditorDefinition(
            "Restore passphrase",
            BACKUP_PASSPHRASE_PROMPT,
            lambda host: host._editor_callbacks._apply_restore_passphrase,
        ),
        workspace_prefix="workspace-restore-",
        unlock_selector="#workflow-restore-unlock-body",
        guided_builder=_guided_builder(
            task_types.RestoreTaskState, workflow_presenter.restore_workflow
        ),
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
        state_factory=_default_state("add_files"),
        qr_size_attribute="qr_chunk_size",
        primary_editor=editors.PathEditorDefinition(
            "Files to add or replace",
            "A selected path replaces content at the same backup path.",
            lambda host: (*host.add_files_state.input_paths, *host.add_files_state.input_dirs),
            lambda host: host._editor_callbacks._apply_add_files_inputs_picked,
        ),
        output_editor=editors.OutputEditorDefinition(
            "Backup update output",
            "Choose a new folder. Clear uses the original backup ID and update number "
            "in the current folder.",
            "output_dir",
            lambda host: host._editor_callbacks._apply_add_files_output_picked,
            "backup-<original-id>-update-<number>",
            prepare_path=editors.update_output_path,
        ),
        passphrase_editor=editors.PassphraseEditorDefinition(
            "Backup passphrase",
            BACKUP_PASSPHRASE_PROMPT,
            lambda host: host._editor_callbacks._apply_add_files_passphrase,
        ),
        workspace_prefix="workspace-add-files-",
        unlock_selector="#workflow-add_files-unlock-body-unlock",
        guided_builder=_guided_builder(
            task_types.AddFilesTaskState, workflow_presenter.add_files_workflow
        ),
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
                issue_codes.ADD_FILES_RECOVERY_OUTPUT_EXISTS,
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
        state_factory=_default_state("rebuild"),
        qr_size_attribute="qr_chunk_size",
        primary_editor=editors.PathEditorDefinition(
            "Load backup documents",
            BACKUP_DOCUMENT_PROMPT,
            editors.rebuild_source_paths,
            lambda host: host._editor_callbacks._apply_rebuild_source_picked,
        ),
        output_editor=editors.OutputEditorDefinition(
            "Rebuilt backup output",
            BACKUP_PARENT_PROMPT,
            "output_dir",
            lambda host: host._editor_callbacks._apply_rebuild_output_picked,
            "parent-folder",
        ),
        passphrase_editor=editors.PassphraseEditorDefinition(
            "Backup passphrase",
            BACKUP_PASSPHRASE_PROMPT,
            lambda host: host._editor_callbacks._apply_rebuild_passphrase,
        ),
        workspace_prefix="workspace-rebuild-",
        unlock_selector="#workflow-rebuild-unlock-body-unlock",
        guided_builder=_guided_builder(
            task_types.RebuildTaskState, workflow_presenter.rebuild_workflow
        ),
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
        state_factory=_default_state("replace_recovery_docs"),
        primary_editor=editors.PathEditorDefinition(
            "Load backup documents",
            "Choose the newest backup PDFs, scanned pages, images, or folders. "
            "Include recovery sheets if you have them.",
            lambda host: host.replace_recovery_docs_state.source_paths,
            lambda host: host._editor_callbacks._apply_replace_recovery_sources_picked,
        ),
        output_editor=editors.OutputEditorDefinition(
            "Replacement sheet output",
            "Choose a new folder path. Existing folders cannot be used, even if empty.",
            "output_dir",
            lambda host: host._editor_callbacks._apply_replace_recovery_output_picked,
            "replacement-recovery-docs",
        ),
        passphrase_editor=editors.PassphraseEditorDefinition(
            "Backup passphrase",
            BACKUP_PASSPHRASE_PROMPT,
            lambda host: host._editor_callbacks._apply_replace_recovery_passphrase,
        ),
        workspace_prefix="workspace-replace-",
        unlock_selector="#workflow-replace_recovery_docs-unlock-body",
        guided_builder=_guided_builder(
            task_types.ReplaceRecoveryDocsTaskState, workflow_presenter.replace_recovery_workflow
        ),
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
        state_factory=_default_state("kit"),
        qr_size_attribute="chunk_size",
        primary_editor="#workspace-kit-variant-select",
        output_editor=editors.OutputEditorDefinition(
            "Offline recovery kit PDF",
            "Creates one printable PDF.",
            "output_path",
            lambda host: host._editor_callbacks._apply_kit_output_picked,
            "recovery_kit_qr.pdf",
            mode=FilePickerMode.SAVE_FILE,
            allow_clear=False,
        ),
        workspace_prefix="workspace-kit-",
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
        primary_editor="#setting-control-render_style",
        output_editor="backup_output_dir",
        passphrase_editor="#setting-control-page_size",
    ),
)

WORKFLOW_BY_KEY = {workflow.key: workflow for workflow in WORKFLOWS}
WORKFLOW_GROUPS = tuple(dict.fromkeys(workflow.nav_group for workflow in WORKFLOWS))


def workflow_definition(task: TaskKey) -> WorkflowDefinition:
    return WORKFLOW_BY_KEY[task]


def workflows_in_group(group: str) -> tuple[WorkflowDefinition, ...]:
    return tuple(workflow for workflow in WORKFLOWS if workflow.nav_group == group)


def nav_option_indices() -> dict[TaskKey, int]:
    indices: dict[TaskKey, int] = {}
    index = 0
    for group in WORKFLOW_GROUPS:
        index += 1
        for workflow in workflows_in_group(group):
            indices[workflow.key] = index
            index += 1
    return indices


def build_guided_workflow(
    *,
    task: TaskKey,
    state: TaskState,
    validation: TaskValidation,
    ui_state: WorkflowUiState,
    review_summary: SummaryPresentation,
    review_label: str,
) -> WorkflowPresentation | None:
    definition = workflow_definition(task)
    if definition.guided_builder is None:
        return None
    return definition.guided_builder(state, validation, ui_state, review_summary, review_label)
