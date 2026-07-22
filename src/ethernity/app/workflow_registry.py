from __future__ import annotations

from dataclasses import dataclass

from ethernity.app.app_types import ActiveTask


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
    section_focus: tuple[tuple[str, str], ...] = ()
    issue_focus: tuple[tuple[str, str], ...] = ()

    def focus_for_section(self, section: str | None) -> str:
        if section is None:
            return self.initial_focus
        return dict(self.section_focus).get(section, self.initial_focus)

    def focus_for_issue(self, code: str, section: str | None) -> str:
        return dict(self.issue_focus).get(code, self.focus_for_section(section))


WORKFLOWS: tuple[WorkflowDefinition, ...] = (
    WorkflowDefinition(
        key="backup",
        title="Create backup",
        nav_group="Backup",
        shortcut="1",
        state_attribute="backup_state",
        workspace_id="backup-workspace",
        initial_focus="#workspace-backup-files",
        review_label="Review backup",
        execute_label="Create backup",
        section_focus=(
            ("files", "#workspace-backup-files"),
            ("output", "#workspace-backup-output"),
            ("recovery", "#workspace-backup-recovery-method"),
            ("advanced", "#workspace-backup-passphrase"),
        ),
        issue_focus=(
            ("BACKUP_CUSTOM_QR_DENSITY", "#workspace-backup-qr-chunk-size"),
            (
                "BACKUP_SIGNING_KEY_QUORUM_INCOMPLETE",
                "#workspace-backup-signing-key-shards",
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
        nav_group="Recovery",
        shortcut="2",
        state_attribute="restore_state",
        workspace_id="restore-workspace",
        initial_focus="#workflow-restore-source-body-methods",
        review_label="Review restore",
        execute_label="Restore files",
        section_focus=(
            ("source", "#workflow-restore-source-body-methods"),
            ("unlock", "#workflow-restore-unlock-body-methods"),
            ("target", "#workflow-restore-target-body-choices"),
            ("authentication", "#restore-advanced-panel"),
            ("output", "#workflow-restore-destination-body-action"),
        ),
        issue_focus=(
            (
                "RESTORE_RECOVERY_TEXT_INVALID",
                "#workflow-restore-source-body-change",
            ),
            ("RESTORE_UPDATE_REQUIRED", "#workflow-restore-target-body-choices"),
            ("RESTORE_AUTH_MATERIAL_CONFLICT", "#workspace-restore-auth-material"),
        ),
    ),
    WorkflowDefinition(
        key="add_files",
        title="Add files to backup",
        nav_group="Maintenance",
        shortcut="3",
        state_attribute="add_files_state",
        workspace_id="add_files-workspace",
        initial_focus="#workflow-add_files-source-body-source-methods",
        review_label="Review update",
        execute_label="Create update",
        section_focus=(
            ("backup", "#workflow-add_files-source-body-source-methods"),
            ("source", "#workspace-add-files-fingerprint"),
            ("files", "#workspace-add-files-add-files"),
            ("unlock", "#workflow-add_files-unlock-body-methods"),
            ("output", "#workflow-add_files-output-body-action"),
            ("advanced", "#workspace-add-files-base-dir"),
        ),
        issue_focus=(
            ("ADD_FILES_HEAD_TRUST_REQUIRED", "#workspace-add-files-fingerprint"),
            ("ADD_FILES_CUSTOM_QR_DENSITY", "#workspace-add-files-qr-chunk-size"),
            ("ADD_FILES_RECOVERY_SHEETS_SKIPPED", "#workspace-add-files-recovery-docs"),
            ("ADD_FILES_CUSTOM_RECOVERY_QUORUM", "#workspace-add-files-recovery-docs"),
            ("ADD_FILES_SIGNING_KEY_NOT_STORED", "#workspace-add-files-signing-key-mode"),
            ("ADD_FILES_CUSTOM_SIGNING_KEY_QUORUM", "#workspace-add-files-signing-key-mode"),
            (
                "ADD_FILES_REUSE_ROOT_RECOVERY_OVERRIDE",
                "#workspace-add-files-unlock-policy",
            ),
            (
                "ADD_FILES_RECOVERY_THRESHOLD_WITHOUT_DOCUMENTS",
                "#workspace-add-files-recovery-docs",
            ),
            (
                "ADD_FILES_ZERO_RECOVERY_REQUIRES_REUSE_ROOT",
                "#workspace-add-files-unlock-policy",
            ),
            ("ADD_FILES_RECOVERY_QUORUM_INVALID", "#workspace-add-files-recovery-docs"),
            (
                "ADD_FILES_SIGNING_KEY_SHARDS_NOT_STORED",
                "#workspace-add-files-signing-key-mode",
            ),
            (
                "ADD_FILES_SIGNING_KEY_QUORUM_INVALID",
                "#workspace-add-files-signing-key-mode",
            ),
            (
                "ADD_FILES_SIGNING_KEY_REQUIRES_RECOVERY_DOCS",
                "#workspace-add-files-recovery-docs",
            ),
        ),
    ),
    WorkflowDefinition(
        key="rebuild",
        title="Rebuild backup",
        nav_group="Maintenance",
        shortcut="4",
        state_attribute="rebuild_state",
        workspace_id="rebuild-workspace",
        initial_focus="#workflow-rebuild-source-body-methods",
        review_label="Review rebuild",
        execute_label="Rebuild backup",
        section_focus=(
            ("source", "#workflow-rebuild-source-body-methods"),
            ("unlock", "#workflow-rebuild-unlock-body-unlock-methods"),
            ("freshness", "#workspace-rebuild-fingerprint"),
            ("output", "#workflow-rebuild-output-body-destination-action"),
            ("advanced", "#rebuild-advanced-panel"),
        ),
        issue_focus=(
            ("REBUILD_HEAD_TRUST_REQUIRED", "#workspace-rebuild-fingerprint"),
            ("REBUILD_CUSTOM_QR_DENSITY", "#workspace-rebuild-qr-chunk-size"),
            ("REBUILD_AUTH_MATERIAL_CONFLICT", "#workspace-rebuild-auth-material"),
        ),
    ),
    WorkflowDefinition(
        key="replace_recovery_docs",
        title="Create replacement recovery sheets",
        nav_group="Maintenance",
        shortcut="5",
        state_attribute="replace_recovery_docs_state",
        workspace_id="replace_recovery_docs-workspace",
        initial_focus="#workflow-replace_recovery_docs-source-body-source-methods",
        review_label="Review replacement sheets",
        execute_label="Create replacement sheets",
        section_focus=(
            ("source", "#workflow-replace_recovery_docs-source-body-source-methods"),
            ("unlock", "#workflow-replace_recovery_docs-unlock-body-methods"),
            ("freshness", "#workspace-replace-fingerprint"),
            ("output", "#workflow-replace_recovery_docs-output-body-destination-action"),
            ("recovery", "#workflow-replace_recovery_docs-recovery-body-mode-choices"),
            ("signature", "#workspace-replace-signing-key-select"),
        ),
        issue_focus=(
            (
                "REPLACE_RECOVERY_TEXT_INVALID",
                "#workflow-replace_recovery_docs-source-body-source-change",
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
        title="Create unanchored rescue kit PDF",
        nav_group="Tools",
        shortcut="6",
        state_attribute="kit_state",
        workspace_id="kit-workspace",
        initial_focus="#workspace-kit-output",
        review_label="Review PDF",
        execute_label="Create PDF",
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
