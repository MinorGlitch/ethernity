from __future__ import annotations

from pathlib import Path
from typing import cast

from ethernity.app.bindings import APP_BINDINGS
from ethernity.app.help_content import HELP_MODES
from ethernity.app.navigation import (
    DIRECT_NAV_TASKS,
    MANAGE_TASKS,
    NAV_LABELS,
    NAV_NUMBERS,
    issue_focus_selector,
)
from ethernity.app.task_catalog import TASK_ORDER, TASK_TITLES
from ethernity.app.workflow_registry import WORKFLOWS
from ethernity.app.workspaces.workspace_controls import control_value
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import (
    TaskExecutionPlan,
    TaskIssue,
    TaskPreview,
    TaskSection,
    TaskValidation,
)
from ethernity.tasks.presentation.builder import build_task_presentation
from ethernity.tasks.presentation.models import (
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.registry import build_review_details
from ethernity.tasks.presentation.workflow_add_files import add_files_auxiliary_groups
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.task_types import TaskKey, TaskState


def _section(key: str) -> TaskSection:
    return TaskSection(key=key, title=key.title(), status="ready", summary="Complete")


def test_blocking_issue_can_never_present_ready_readiness() -> None:
    validation = TaskValidation(
        sections=tuple(
            _section(key) for key in ("files", "recovery", "print", "output", "advanced")
        ),
        issues=(
            TaskIssue(
                code="BLOCKED_RECOVERY",
                message="Choose a usable recovery method.",
                section="recovery",
            ),
        ),
    )

    presentation = build_task_presentation(
        task_key="backup",
        title="Create backup",
        state=BackupTaskState(),
        validation=validation,
        preview=TaskPreview(title="Backup"),
        primary_label="Review backup",
        diagnostics_available=False,
    )

    assert not presentation.validation_ready
    assert presentation.ready_count == presentation.total_count - 1
    assert presentation.readiness_label != "Ready to review"


def test_add_files_control_values_are_typed_not_inferred_from_copy() -> None:
    state = AddFilesTaskState(
        auth_text_file=Path("signature.txt"),
    )
    sections = {section.key: section for section in state.sections()}

    advanced = add_files_auxiliary_groups(state, sections["advanced"])[0]
    controls = {item.key: item.control_value for item in advanced.values}

    assert controls == {
        "update-mode": "cumulative",
        "update-mode-locked": "editable",
        "base-dir": "automatic",
        "qr-chunk-size": "default",
        "signature-source": "text",
        "recovery-sheets": "off",
    }


def test_empty_rebuild_controls_do_not_claim_a_backup_is_loaded() -> None:
    state = RebuildTaskState()
    presentation = build_task_presentation(
        task_key="rebuild",
        title="Rebuild a backup",
        state=state,
        validation=state.validate_task(),
        preview=state.preview(),
        primary_label="Review rebuild",
        diagnostics_available=False,
    )

    assert [group.key for group in presentation.workspace_groups] == ["advanced"]
    assert control_value(presentation.workspace_groups[0], "source-status") == "empty"


def test_help_states_the_settled_extension_requirements() -> None:
    help_by_key = {mode.key: mode for mode in HELP_MODES}
    add_files_text = "\n".join(
        line
        for section in help_by_key["add_files"].sections
        for line in (section.body, *section.notes)
    )
    rebuild_text = "\n".join(
        line
        for section in help_by_key["rebuild"].sections
        for line in (section.body, *section.notes)
    )
    restore_text = "\n".join(
        line
        for section in help_by_key["restore"].sections
        for line in (section.body, *section.notes)
    )

    assert "Files with matching backup paths are replaced" in add_files_text
    assert "To delete or rename files, restore them and create a new backup" in add_files_text
    assert "backup PDFs, scans, printed text, or exported data" in help_by_key["restore"].summary
    assert "Rebuild scanned or printed documents" not in add_files_text
    assert "Optional new recovery sheets are saved separately" in add_files_text
    assert "original backup and its passphrase or enough recovery sheets" in add_files_text
    assert "Signing-key sheets do not add another approval step" in add_files_text
    assert "Separate updates from the same version conflict" in add_files_text
    assert "cannot be merged" in add_files_text
    assert "The passphrase and any embedded signing key stay the same" in rebuild_text
    assert "Backups without an embedded signing key get a new one" in rebuild_text
    assert "new recovery sheets" in rebuild_text
    assert "Test recovery from the new printed pages before retiring the old ones" in (rebuild_text)
    assert "Create a new backup" in rebuild_text
    assert "latest valid update you supplied" in restore_text


def test_workspace_copy_can_change_without_changing_control_behavior() -> None:
    advanced = WorkspaceGroup(
        key="advanced",
        title="Advanced",
        kind="fields",
        values=(
            WorkspaceValue(
                "qr-chunk-size",
                "QR density",
                "Localized default copy",
                control_value="default",
            ),
            WorkspaceValue(
                "signing-key",
                "Signing key",
                "Localized embedded copy",
                control_value="embedded",
            ),
        ),
    )

    assert control_value(advanced, "qr-chunk-size") == "default"
    assert control_value(advanced, "signing-key") == "embedded"
    assert (
        "Keep the recovery phrase separate"
        in BackupTaskState(recovery_method="single_phrase").facts().storage_note
    )
    assert (
        "Store recovery sheets separately"
        in BackupTaskState(recovery_method="custom_shards").facts().storage_note
    )


def test_workflow_registry_is_the_single_metadata_source() -> None:
    keys = tuple(workflow.key for workflow in WORKFLOWS)

    assert keys == TASK_ORDER
    assert len(keys) == len(set(keys))
    assert TASK_TITLES == {workflow.key: workflow.title for workflow in WORKFLOWS}
    assert set(DIRECT_NAV_TASKS.values()).isdisjoint(MANAGE_TASKS)
    assert set(DIRECT_NAV_TASKS.values()) | set(MANAGE_TASKS) == set(keys)
    assert set(NAV_LABELS) == set(keys)
    assert NAV_NUMBERS == {workflow.key: workflow.shortcut for workflow in WORKFLOWS}
    workflow_bindings = {
        binding.key: binding.action
        for binding in APP_BINDINGS
        if binding.key in {workflow.shortcut for workflow in WORKFLOWS}
    }
    assert workflow_bindings == {
        workflow.shortcut: f"show_task('{workflow.key}')" for workflow in WORKFLOWS
    }
    selectors = (selector for workflow in WORKFLOWS for _, selector in workflow.section_focus)
    assert all("workspace-rebuild-paper" not in selector for selector in selectors)


def test_blocking_issue_focus_targets_the_actual_advanced_control() -> None:
    cases = (
        (
            "backup",
            "BACKUP_SIGNING_KEY_QUORUM_INCOMPLETE",
            "advanced",
            "#workspace-backup-signing-key-mode",
        ),
        (
            "restore",
            "RESTORE_SIGNATURE_SOURCE_CONFLICT",
            "source",
            "#workspace-restore-signature-source",
        ),
        (
            "add_files",
            "ADD_FILES_CUSTOM_QR_DENSITY",
            "advanced",
            "#workspace-add-files-qr-chunk-size",
        ),
        (
            "add_files",
            "ADD_FILES_RECOVERY_OUTPUT_EXISTS",
            "advanced",
            "#workspace-add-files-recovery-sheets",
        ),
        (
            "rebuild",
            "REBUILD_SIGNATURE_SOURCE_CONFLICT",
            "advanced",
            "#workspace-rebuild-signature-source",
        ),
        (
            "replace_recovery_docs",
            "REPLACE_RECOVERY_SIGNING_KEY_REPLACEMENT_INPUT_REQUIRED",
            "signature",
            "#workspace-replace-signing-key-payloads",
        ),
    )

    for task, code, section, expected in cases:
        issue = TaskIssue(code=code, message="Fix this value.", section=section)
        assert issue_focus_selector(task, issue) == expected


def test_review_details_describe_each_task() -> None:
    cases = (
        (
            "backup",
            BackupTaskState(
                input_paths=[Path("records.txt")],
                recovery_method="custom_shards",
                shard_threshold=3,
                shard_count=5,
                output_dir=Path("backup-out"),
            ),
            TaskExecutionPlan(summary="Backup", output_paths=(Path("backup-out"),)),
            {
                "Files": "1 file",
                "Recovery": "5 sheets, 3 needed to restore",
                "Destination": str(Path("backup-out").absolute()),
            },
        ),
        (
            "restore",
            RestoreTaskState(
                payloads_file=Path("recovery.bin"),
                passphrase="secret",
                target="original",
                allow_unsigned=True,
                output_path=Path("restored"),
            ),
            TaskExecutionPlan(summary="Restore", output_paths=(Path("restored"),)),
            {
                "Source": "Exported backup data",
                "Unlock": "Passphrase",
                "Version": "Initial backup only",
                "Signature": "Unsigned legacy backups allowed",
            },
        ),
        (
            "add_files",
            AddFilesTaskState(
                source_paths=[Path("backup")],
                output_dir=Path("update-out"),
                allow_stale_head=True,
                input_paths=[Path("changed.txt")],
                passphrase="secret",
            ),
            TaskExecutionPlan(summary="Update", output_paths=(Path("backup"),)),
            {
                "Changes": "1 file, replacing matching paths",
                "Source version": "Newest loaded version accepted",
                "Recovery sheets": "No new recovery sheets",
            },
        ),
        (
            "rebuild",
            RebuildTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
                allow_stale_head=True,
                output_dir=Path("rebuilt"),
            ),
            TaskExecutionPlan(summary="Rebuild", output_paths=(Path("rebuilt"),)),
            {
                "Source": "1 document input",
                "Source version": "Latest loaded version accepted",
                "Layout": "A4, Sentinel",
            },
        ),
        (
            "replace_recovery_docs",
            ReplaceRecoveryDocsTaskState(
                payloads_file=Path("recovery.bin"),
                passphrase="secret",
                recovery_threshold=3,
                recovery_document_count=5,
                signing_key_recovery_threshold=2,
                signing_key_recovery_count=4,
                output_dir=Path("replacement"),
            ),
            TaskExecutionPlan(summary="Replace", output_paths=(Path("replacement"),)),
            {
                "Recovery sheets": "5 sheets; any 3 can restore",
                "Signing-key sheets": "4 new sheets (2 required)",
            },
        ),
        (
            "kit",
            PrintKitTaskState(
                variant="scanner",
                paper_size="LETTER",
                design="forge",
                chunk_size=384,
                output_path=Path("kit.pdf"),
            ),
            TaskExecutionPlan(summary="Kit", output_paths=(Path("kit.pdf"),)),
            {
                "Kit type": "Paste text + scan QR codes",
                "Layout": "Letter, Forge",
                "QR sizing": "384-byte chunks",
            },
        ),
    )

    for task, state, plan, expected in cases:
        details = {
            detail.label: detail.value
            for detail in build_review_details(
                cast(TaskKey, task),
                cast(TaskState, state),
                plan,
            )
        }
        assert details.items() >= expected.items()
