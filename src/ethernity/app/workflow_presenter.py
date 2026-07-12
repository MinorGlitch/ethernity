from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ethernity.app.app_types import ActiveTask, UnlockTaskState
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.file_summary import display_path, format_count
from ethernity.tasks.models import TaskSection, TaskValidation
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    CompositeBodyPartPresentation,
    CompositeBodyPresentation,
    DestinationBodyPresentation,
    InlineNoticePresentation,
    OptionsBodyPresentation,
    PathItemPresentation,
    PathSelectionBodyPresentation,
    QuorumBodyPresentation,
    SelectFieldPresentation,
    SelectOptionPresentation,
    SourceAssessmentPresentation,
    SourceBodyPresentation,
    StepBodyPresentation,
    StepPresentation,
    StepSeverity,
    StepState,
    SummaryPresentation,
    UnlockBodyPresentation,
    WorkflowPresentation,
    WorkspaceAction,
    WorkspaceValue,
)
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.source_assessment import SourceAssessableTaskState

GUIDED_WORKFLOW_SECTIONS: dict[ActiveTask, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "restore": (
        ("source", ("source",)),
        ("unlock", ("unlock",)),
        ("target", ("target",)),
        ("destination", ("output",)),
    ),
    "add_files": (
        ("source", ("backup", "source")),
        ("files", ("files",)),
        ("unlock", ("unlock",)),
        ("output", ("output",)),
    ),
    "rebuild": (
        ("source", ("source",)),
        ("unlock", ("unlock", "freshness")),
        ("output", ("output",)),
    ),
    "replace_recovery_docs": (
        ("source", ("source", "freshness")),
        ("unlock", ("unlock",)),
        ("recovery", ("recovery",)),
        ("output", ("output",)),
    ),
}


def initial_workflow_ui_states() -> dict[ActiveTask, WorkflowUiState]:
    return {
        task: WorkflowUiState.start(*(step for step, _sections in steps))
        for task, steps in GUIDED_WORKFLOW_SECTIONS.items()
    }


def is_guided_task(task: ActiveTask) -> bool:
    return task in GUIDED_WORKFLOW_SECTIONS


def step_for_section(task: ActiveTask, section: str | None) -> str | None:
    if section is None:
        return None
    return next(
        (
            step_key
            for step_key, section_keys in GUIDED_WORKFLOW_SECTIONS.get(task, ())
            if section in section_keys
        ),
        None,
    )


def active_step_is_complete(
    task: ActiveTask,
    validation: TaskValidation,
    ui_state: WorkflowUiState,
) -> bool:
    if ui_state.has_invalid_draft(ui_state.active_step):
        return False
    if ui_state.active_step == "source" and ui_state.source_assessment_loading:
        return False
    section_keys = _sections_for_step(task, ui_state.active_step)
    return bool(section_keys) and _step_complete(validation, section_keys)


def next_step(task: ActiveTask, active_step: str) -> str | None:
    step_keys = tuple(step for step, _ in GUIDED_WORKFLOW_SECTIONS.get(task, ()))
    if active_step not in step_keys:
        return None
    index = step_keys.index(active_step)
    return step_keys[index + 1] if index + 1 < len(step_keys) else None


def build_guided_workflow(
    *,
    task: ActiveTask,
    state: object,
    validation: TaskValidation,
    ui_state: WorkflowUiState,
    review_summary: SummaryPresentation,
    review_label: str,
) -> WorkflowPresentation | None:
    if task == "restore" and isinstance(state, RestoreTaskState):
        return _restore_workflow(
            state=state,
            validation=validation,
            ui_state=ui_state,
            review_summary=review_summary,
            review_label=review_label,
        )
    if task == "add_files" and isinstance(state, AddFilesTaskState):
        return _add_files_workflow(
            state=state,
            validation=validation,
            ui_state=ui_state,
            review_summary=review_summary,
            review_label=review_label,
        )
    if task == "rebuild" and isinstance(state, RebuildTaskState):
        return _rebuild_workflow(
            state=state,
            validation=validation,
            ui_state=ui_state,
            review_summary=review_summary,
            review_label=review_label,
        )
    if task == "replace_recovery_docs" and isinstance(state, ReplaceRecoveryDocsTaskState):
        return _replace_recovery_workflow(
            state=state,
            validation=validation,
            ui_state=ui_state,
            review_summary=review_summary,
            review_label=review_label,
        )
    return None


def restore_workflow_placeholder() -> WorkflowPresentation:
    state = RestoreTaskState()
    validation = state.validate_task()
    return _restore_workflow(
        state=state,
        validation=validation,
        ui_state=WorkflowUiState.start("source", "unlock", "target", "destination"),
        review_summary=SummaryPresentation(
            title="",
            items=(),
            blockers=(),
            warnings=(),
        ),
        review_label="Review restore",
    )


def add_files_workflow_placeholder() -> WorkflowPresentation:
    state = AddFilesTaskState()
    return _add_files_workflow(
        state=state,
        validation=state.validate_task(),
        ui_state=WorkflowUiState.start("source", "files", "unlock", "output"),
        review_summary=_empty_summary(),
        review_label="Review update",
    )


def rebuild_workflow_placeholder() -> WorkflowPresentation:
    state = RebuildTaskState()
    return _rebuild_workflow(
        state=state,
        validation=state.validate_task(),
        ui_state=WorkflowUiState.start("source", "unlock", "output"),
        review_summary=_empty_summary(),
        review_label="Review rebuild",
    )


def replace_recovery_workflow_placeholder() -> WorkflowPresentation:
    state = ReplaceRecoveryDocsTaskState()
    return _replace_recovery_workflow(
        state=state,
        validation=state.validate_task(),
        ui_state=WorkflowUiState.start("source", "unlock", "recovery", "output"),
        review_summary=_empty_summary(),
        review_label="Review replacement sheets",
    )


def _restore_workflow(
    *,
    state: RestoreTaskState,
    validation: TaskValidation,
    ui_state: WorkflowUiState,
    review_summary: SummaryPresentation,
    review_label: str,
) -> WorkflowPresentation:
    sections = {section.key: section for section in validation.sections}
    step_specs = (
        (
            "source",
            "Backup source",
            _source_summary(state, sections["source"]),
            _restore_source_body(state, ui_state),
        ),
        (
            "unlock",
            "Unlock",
            _unlock_summary(state, sections["unlock"]),
            _unlock_body(state, action_key="workspace-restore-unlock"),
        ),
        (
            "target",
            "Version",
            sections["target"].summary,
            _restore_target_body(state),
        ),
        (
            "destination",
            "Destination",
            _destination_summary(state),
            _restore_destination_body(state),
        ),
    )
    return _workflow_presentation(
        task_key="restore",
        title="Restore files",
        validation=validation,
        ui_state=ui_state,
        step_specs=step_specs,
        review_summary=review_summary,
        review_label=review_label,
    )


def _add_files_workflow(
    *,
    state: AddFilesTaskState,
    validation: TaskValidation,
    ui_state: WorkflowUiState,
    review_summary: SummaryPresentation,
    review_label: str,
) -> WorkflowPresentation:
    sections = {section.key: section for section in validation.sections}
    step_specs = (
        (
            "source",
            "Backup source",
            _add_files_source_summary(state, sections),
            _add_files_source_body(state, sections, ui_state),
        ),
        (
            "files",
            "Files",
            sections["files"].summary,
            _add_files_paths_body(state),
        ),
        (
            "unlock",
            "Unlock",
            _unlock_summary(state, sections["unlock"]),
            _unlock_body(state, action_key="workspace-add-files-unlock"),
        ),
        (
            "output",
            "Save update",
            sections["output"].summary,
            _add_files_destination_body(state),
        ),
    )
    return _workflow_presentation(
        task_key="add_files",
        title="Add files to backup",
        validation=validation,
        ui_state=ui_state,
        step_specs=step_specs,
        review_summary=review_summary,
        review_label=review_label,
    )


def _rebuild_workflow(
    *,
    state: RebuildTaskState,
    validation: TaskValidation,
    ui_state: WorkflowUiState,
    review_summary: SummaryPresentation,
    review_label: str,
) -> WorkflowPresentation:
    sections = {section.key: section for section in validation.sections}
    step_specs = (
        (
            "source",
            "Backup source",
            sections["source"].summary,
            _rebuild_source_body(state, ui_state),
        ),
        (
            "unlock",
            "Unlock and verify",
            _rebuild_unlock_summary(state, sections),
            _rebuild_unlock_body(state, sections),
        ),
        (
            "output",
            "Rebuilt backup",
            sections["output"].summary,
            _rebuild_output_body(state),
        ),
    )
    return _workflow_presentation(
        task_key="rebuild",
        title="Rebuild backup",
        validation=validation,
        ui_state=ui_state,
        step_specs=step_specs,
        review_summary=review_summary,
        review_label=review_label,
    )


def _replace_recovery_workflow(
    *,
    state: ReplaceRecoveryDocsTaskState,
    validation: TaskValidation,
    ui_state: WorkflowUiState,
    review_summary: SummaryPresentation,
    review_label: str,
) -> WorkflowPresentation:
    sections = {section.key: section for section in validation.sections}
    step_specs = (
        (
            "source",
            "Backup source",
            _replace_source_summary(state, sections),
            _replace_source_body(state, sections, ui_state),
        ),
        (
            "unlock",
            "Unlock",
            _unlock_summary(state, sections["unlock"]),
            _unlock_body(state, action_key="workspace-replace-unlock"),
        ),
        (
            "recovery",
            "Recovery sheets",
            sections["recovery"].summary,
            _replacement_recovery_body(state, ui_state),
        ),
        (
            "output",
            "Save sheets",
            sections["output"].summary,
            _replacement_output_body(state),
        ),
    )
    return _workflow_presentation(
        task_key="replace_recovery_docs",
        title="Create replacement recovery sheets",
        validation=validation,
        ui_state=ui_state,
        step_specs=step_specs,
        review_summary=review_summary,
        review_label=review_label,
    )


def _workflow_presentation(
    *,
    task_key: ActiveTask,
    title: str,
    validation: TaskValidation,
    ui_state: WorkflowUiState,
    step_specs: tuple[tuple[str, str, str, StepBodyPresentation], ...],
    review_summary: SummaryPresentation,
    review_label: str,
) -> WorkflowPresentation:
    _reconcile_active_step(task_key, validation, ui_state)
    sections = {section.key: section for section in validation.sections}
    steps: list[StepPresentation] = []
    prerequisites_complete = True
    for step_key, step_title, summary, body in step_specs:
        section_keys = _sections_for_step(task_key, step_key)
        if not section_keys:
            raise ValueError(f"no validation sections registered for {task_key}.{step_key}")
        show_issue = ui_state.attempted_review or ui_state.is_touched(step_key)
        issue = _step_issue(
            validation=validation,
            review_summary=review_summary,
            section_keys=section_keys,
            show_error=show_issue,
        )
        draft_error = ui_state.draft_error(step_key)
        state_issue = (
            InlineNoticePresentation(draft_error, tone="error")
            if draft_error is not None
            else issue
        )
        visible_issue = None if _body_owns_notice(body, issue) else issue
        complete = (
            _step_complete(validation, section_keys)
            and not (step_key == "source" and ui_state.source_assessment_loading)
            and not ui_state.has_invalid_draft(step_key)
        )
        steps.append(
            StepPresentation(
                key=step_key,
                title=step_title,
                state=_step_state(
                    active=step_key == ui_state.active_step,
                    prerequisites_complete=prerequisites_complete,
                    complete=complete,
                ),
                summary=summary,
                body=body,
                issue=visible_issue,
                severity=_step_severity(
                    warning=any(sections[key].status == "warning" for key in section_keys),
                    issue=state_issue,
                ),
            )
        )
        prerequisites_complete = prerequisites_complete and complete

    return WorkflowPresentation(
        task_key=task_key,
        title=title,
        active_step=ui_state.active_step,
        steps=tuple(steps),
        primary_action=WorkspaceAction(
            "primary",
            review_label if next_step(task_key, ui_state.active_step) is None else "Continue",
            enabled=not ui_state.has_invalid_draft(ui_state.active_step),
        ),
        review_summary=review_summary,
    )


def _reconcile_active_step(
    task: ActiveTask,
    validation: TaskValidation,
    ui_state: WorkflowUiState,
) -> None:
    """Move back to the first prerequisite that became incomplete."""

    active_index = ui_state.step_keys.index(ui_state.active_step)
    for step_key in ui_state.step_keys[:active_index]:
        complete = _step_complete(validation, _sections_for_step(task, step_key))
        if ui_state.has_invalid_draft(step_key):
            complete = False
        if step_key == "source" and ui_state.source_assessment_loading:
            complete = False
        if not complete:
            ui_state.activate(step_key)
            return


def _restore_source_body(
    state: RestoreTaskState,
    ui_state: WorkflowUiState,
) -> SourceBodyPresentation:
    selected = _restore_source_method(state)
    assessment = _resolved_source_assessment(state, _restore_source_assessment(state))
    return SourceBodyPresentation(
        methods=(
            ChoicePresentation(
                "scanned_pages",
                "Scanned pages",
                selected=selected == "scanned_pages",
                description="PDFs, images, or a folder.",
            ),
            ChoicePresentation(
                "recovery_text",
                "Recovery text",
                selected=selected == "recovery_text",
                description="Paste text or load it from a file.",
            ),
            ChoicePresentation(
                "payload_files",
                "Backup payload file",
                selected=selected == "payload_files",
                description="An exported backup payload.",
            ),
        ),
        assessment=assessment,
        change_action=(
            WorkspaceAction("restore-change-source", "Change source...")
            if assessment is not None
            else None
        ),
        loading=ui_state.source_assessment_loading,
        notice=_source_assessment_notice(state),
    )


def _restore_source_method(state: RestoreTaskState) -> str | None:
    if state.source_paths:
        return "scanned_pages"
    if state.recovery_text or state.recovery_text_file is not None:
        return "recovery_text"
    if state.payloads_file is not None:
        return "payload_files"
    return None


def _restore_source_assessment(
    state: RestoreTaskState,
) -> SourceAssessmentPresentation | None:
    method = _restore_source_method(state)
    if method == "scanned_pages":
        return SourceAssessmentPresentation(
            source_kind="scanned_pages",
            source_label="Scanned pages",
            material_summary=_paths_material_summary(state.source_paths),
        )
    if method == "recovery_text":
        if state.recovery_text:
            lines = len([line for line in state.recovery_text.splitlines() if line.strip()])
            material = f"Pasted text, {format_count(lines, 'non-empty line')}"
        else:
            material = display_path(state.recovery_text_file or "")
        return SourceAssessmentPresentation(
            source_kind="recovery_text",
            source_label="Recovery text",
            material_summary=material,
        )
    if method == "payload_files":
        return SourceAssessmentPresentation(
            source_kind="payload_files",
            source_label="Backup payload file",
            material_summary=display_path(state.payloads_file or ""),
        )
    return None


def _unlock_body(
    state: UnlockTaskState,
    *,
    action_key: str,
) -> UnlockBodyPresentation:
    selected = _unlock_method(state)
    action_by_method = {
        "passphrase": WorkspaceAction(action_key, "Change passphrase..."),
        "recovery_documents": WorkspaceAction(
            action_key,
            "Change recovery sheets...",
        ),
        "recovery_payloads": WorkspaceAction(
            action_key,
            "Change recovery payloads...",
        ),
    }
    return UnlockBodyPresentation(
        methods=(
            ChoicePresentation("passphrase", "Passphrase", selected=selected == "passphrase"),
            ChoicePresentation(
                "recovery_documents",
                "Recovery sheets",
                selected=selected == "recovery_documents",
            ),
            ChoicePresentation(
                "recovery_payloads",
                "Recovery payload files",
                selected=selected == "recovery_payloads",
            ),
        ),
        contextual_action=action_by_method[selected] if selected is not None else None,
        material_summary=_unlock_material_summary(state),
    )


def _unlock_method(state: UnlockTaskState) -> str | None:
    if state.passphrase:
        return "passphrase"
    if state.recovery_documents:
        return "recovery_documents"
    if state.recovery_payload_files:
        return "recovery_payloads"
    return None


def _unlock_material_summary(state: UnlockTaskState) -> str:
    method = _unlock_method(state)
    if method == "passphrase":
        return "Passphrase set"
    if method == "recovery_documents":
        count = len(state.recovery_documents)
        first_path = display_path(state.recovery_documents[0])
        return (
            first_path
            if count == 1
            else f"{format_count(count, 'recovery sheet')}; first: {first_path}"
        )
    if method == "recovery_payloads":
        count = len(state.recovery_payload_files)
        first_path = display_path(state.recovery_payload_files[0])
        return (
            first_path
            if count == 1
            else f"{format_count(count, 'recovery payload file')}; first: {first_path}"
        )
    return ""


def _restore_target_body(
    state: RestoreTaskState,
) -> OptionsBodyPresentation:
    specific = state.target == "specific_update"
    return OptionsBodyPresentation(
        choices=(
            ChoicePresentation(
                "latest", "Newest loaded version", selected=state.target == "latest"
            ),
            ChoicePresentation(
                "original", "Initial backup only", selected=state.target == "original"
            ),
            ChoicePresentation(
                "specific_update",
                "Specific version or update",
                selected=specific,
            ),
        ),
        actions=(
            WorkspaceAction(
                "workspace-restore-target",
                "Set update number...",
                visible=specific,
            ),
            WorkspaceAction(
                "workspace-restore-target-fingerprint",
                "Set fingerprint...",
                visible=specific,
            ),
        ),
    )


def _restore_destination_body(state: RestoreTaskState) -> DestinationBodyPresentation:
    return DestinationBodyPresentation(
        label="Restore to",
        display_path=display_path(state.output_path) if state.output_path is not None else "",
        empty_label="No restore folder selected",
        action=WorkspaceAction("workspace-restore-output", "Choose restore folder..."),
    )


def _source_summary(state: RestoreTaskState, section: TaskSection) -> str:
    return (
        section.summary if _restore_source_method(state) is not None else "Choose backup material"
    )


def _unlock_summary(state: UnlockTaskState, section: TaskSection) -> str:
    return section.summary if _unlock_method(state) is not None else "Choose an unlock method"


def _destination_summary(state: RestoreTaskState) -> str:
    if state.output_path is None:
        return "Choose a restore folder"
    return display_path(state.output_path)


def _add_files_source_body(
    state: AddFilesTaskState,
    sections: Mapping[str, TaskSection],
    ui_state: WorkflowUiState,
) -> CompositeBodyPresentation:
    selected = _folder_or_scans_method(state.backup_folder, state.source_paths)
    assessment = _resolved_source_assessment(
        state,
        _folder_or_scans_assessment(
            backup_folder=state.backup_folder,
            source_paths=state.source_paths,
        ),
    )
    scanned = selected == "scanned_pages"
    return CompositeBodyPresentation(
        parts=(
            CompositeBodyPartPresentation(
                "source",
                SourceBodyPresentation(
                    methods=_folder_or_scans_choices(selected),
                    assessment=assessment,
                    change_action=(
                        WorkspaceAction("add-files-change-source", "Change source...")
                        if assessment is not None
                        else None
                    ),
                    loading=ui_state.source_assessment_loading,
                    notice=_source_assessment_notice(state),
                ),
            ),
            CompositeBodyPartPresentation(
                "trust",
                OptionsBodyPresentation(
                    values=(
                        WorkspaceValue(
                            "freshness",
                            "Scan version",
                            sections["source"].summary if scanned else "",
                        ),
                    ),
                    actions=(
                        WorkspaceAction(
                            "workspace-add-files-freshness",
                            "Treat scans as latest",
                            visible=scanned,
                        ),
                        WorkspaceAction(
                            "workspace-add-files-fingerprint",
                            "Enter expected fingerprint...",
                            visible=scanned,
                        ),
                    ),
                ),
            ),
        )
    )


def _add_files_source_summary(
    state: AddFilesTaskState,
    sections: Mapping[str, TaskSection],
) -> str:
    method = _folder_or_scans_method(state.backup_folder, state.source_paths)
    if method is None:
        return "Choose a backup folder or scanned pages"
    if method == "backup_folder":
        return f"Folder: {display_path(state.backup_folder or '')}"
    return f"Scans: {sections['source'].summary}"


def _add_files_paths_body(state: AddFilesTaskState) -> PathSelectionBodyPresentation:
    items = (
        *(
            PathItemPresentation(
                key=f"file-{index}",
                label="File",
                display_path=display_path(path),
            )
            for index, path in enumerate(state.input_paths)
        ),
        *(
            PathItemPresentation(
                key=f"folder-{index}",
                label="Folder",
                display_path=display_path(path),
            )
            for index, path in enumerate(state.input_dirs)
        ),
    )
    return PathSelectionBodyPresentation(
        items=items,
        empty_label="No files or folders selected",
        count_summary=_path_count_summary(len(state.input_paths), len(state.input_dirs)),
        actions=(
            WorkspaceAction("workspace-add-files-add-files", "Add files..."),
            WorkspaceAction("workspace-add-files-add-folder", "Add folder..."),
            WorkspaceAction(
                "workspace-add-files-remove-selected",
                "Remove selected",
                requires_selection=True,
            ),
            WorkspaceAction(
                "workspace-add-files-clear-files",
                "Clear all",
                enabled=bool(items),
            ),
        ),
    )


def _add_files_destination_body(state: AddFilesTaskState) -> DestinationBodyPresentation:
    scanned = bool(state.source_paths)
    output = state.loose_output_folder if scanned else state.backup_folder
    return DestinationBodyPresentation(
        label="Save to",
        display_path=display_path(output) if output is not None else "",
        empty_label=(
            "Choose an output folder" if scanned else "Choose the existing backup folder first"
        ),
        action=WorkspaceAction(
            "workspace-add-files-output",
            "Choose output folder...",
            visible=scanned,
        ),
    )


def _rebuild_source_body(
    state: RebuildTaskState,
    ui_state: WorkflowUiState,
) -> SourceBodyPresentation:
    selected = _folder_or_scans_method(state.backup_folder, state.source_paths)
    assessment = _resolved_source_assessment(
        state,
        _folder_or_scans_assessment(
            backup_folder=state.backup_folder,
            source_paths=state.source_paths,
        ),
    )
    return SourceBodyPresentation(
        methods=_folder_or_scans_choices(selected),
        assessment=assessment,
        change_action=(
            WorkspaceAction("rebuild-change-source", "Change source...")
            if assessment is not None
            else None
        ),
        loading=ui_state.source_assessment_loading,
        notice=_source_assessment_notice(state),
    )


def _rebuild_unlock_body(
    state: RebuildTaskState,
    sections: Mapping[str, TaskSection],
) -> CompositeBodyPresentation:
    scanned = bool(state.source_paths) and state.backup_folder is None
    return CompositeBodyPresentation(
        parts=(
            CompositeBodyPartPresentation(
                "unlock",
                _unlock_body(state, action_key="workspace-rebuild-unlock"),
            ),
            CompositeBodyPartPresentation(
                "trust",
                OptionsBodyPresentation(
                    values=(
                        WorkspaceValue(
                            "freshness",
                            "Scan version",
                            sections["freshness"].summary if scanned else "",
                        ),
                    ),
                    actions=(
                        WorkspaceAction(
                            "workspace-rebuild-freshness",
                            "Treat scans as latest",
                            visible=scanned,
                        ),
                        WorkspaceAction(
                            "workspace-rebuild-fingerprint",
                            "Enter expected fingerprint...",
                            visible=scanned,
                        ),
                    ),
                ),
            ),
        )
    )


def _rebuild_unlock_summary(
    state: RebuildTaskState,
    sections: Mapping[str, TaskSection],
) -> str:
    unlock = _unlock_summary(state, sections["unlock"])
    if not state.source_paths:
        return unlock
    return f"{unlock}; {sections['freshness'].summary}"


def _rebuild_output_body(state: RebuildTaskState) -> CompositeBodyPresentation:
    return CompositeBodyPresentation(
        parts=(
            CompositeBodyPartPresentation(
                "destination",
                DestinationBodyPresentation(
                    label="Save to",
                    display_path=(
                        display_path(state.output_dir) if state.output_dir is not None else ""
                    ),
                    empty_label="No output folder selected",
                    action=WorkspaceAction(
                        "workspace-rebuild-output",
                        "Choose output folder...",
                    ),
                ),
            ),
            CompositeBodyPartPresentation(
                "layout",
                OptionsBodyPresentation(
                    selects=(
                        SelectFieldPresentation(
                            key="workspace-rebuild-paper",
                            label="Paper size",
                            options=(
                                SelectOptionPresentation("A4", "A4"),
                                SelectOptionPresentation("LETTER", "Letter"),
                            ),
                            value=state.paper_size,
                            allow_blank=False,
                        ),
                        SelectFieldPresentation(
                            key="workspace-rebuild-design",
                            label="Print design",
                            options=tuple(
                                SelectOptionPresentation(key, key.title())
                                for key in ("archive", "forge", "ledger", "maritime", "sentinel")
                            ),
                            value=state.design,
                            allow_blank=False,
                        ),
                    ),
                ),
            ),
        )
    )


def _replace_source_body(
    state: ReplaceRecoveryDocsTaskState,
    sections: Mapping[str, TaskSection],
    ui_state: WorkflowUiState,
) -> CompositeBodyPresentation:
    selected = _replace_source_method(state)
    assessment = _resolved_source_assessment(state, _replace_source_assessment(state))
    scanned = selected == "scanned_pages"
    return CompositeBodyPresentation(
        parts=(
            CompositeBodyPartPresentation(
                "source",
                SourceBodyPresentation(
                    methods=(
                        ChoicePresentation(
                            "scanned_pages",
                            "Scanned pages",
                            selected=selected == "scanned_pages",
                        ),
                        ChoicePresentation(
                            "recovery_text",
                            "Recovery text",
                            selected=selected == "recovery_text",
                        ),
                        ChoicePresentation(
                            "payload_files",
                            "Backup payload file",
                            selected=selected == "payload_files",
                        ),
                    ),
                    assessment=assessment,
                    change_action=(
                        WorkspaceAction("replace-change-source", "Change source...")
                        if assessment is not None
                        else None
                    ),
                    loading=ui_state.source_assessment_loading,
                    notice=_source_assessment_notice(state),
                ),
            ),
            CompositeBodyPartPresentation(
                "trust",
                OptionsBodyPresentation(
                    values=(
                        WorkspaceValue(
                            "freshness",
                            "Scan version",
                            sections["freshness"].summary if scanned else "",
                        ),
                    ),
                    actions=(
                        WorkspaceAction(
                            "workspace-replace-freshness",
                            "Treat scans as latest",
                            visible=scanned,
                        ),
                        WorkspaceAction(
                            "workspace-replace-fingerprint",
                            "Enter expected fingerprint...",
                            visible=scanned,
                        ),
                    ),
                ),
            ),
        )
    )


def _replace_source_method(state: ReplaceRecoveryDocsTaskState) -> str | None:
    if state.source_paths:
        return "scanned_pages"
    if state.recovery_text or state.recovery_text_file is not None:
        return "recovery_text"
    if state.payloads_file is not None:
        return "payload_files"
    return None


def _replace_source_assessment(
    state: ReplaceRecoveryDocsTaskState,
) -> SourceAssessmentPresentation | None:
    method = _replace_source_method(state)
    if method == "scanned_pages":
        return SourceAssessmentPresentation(
            source_kind="scanned_pages",
            source_label="Scanned pages",
            material_summary=_paths_material_summary(state.source_paths),
        )
    if method == "recovery_text":
        material = (
            _pasted_text_summary(state.recovery_text)
            if state.recovery_text
            else display_path(state.recovery_text_file or "")
        )
        return SourceAssessmentPresentation(
            source_kind="recovery_text",
            source_label="Recovery text",
            material_summary=material,
        )
    if method == "payload_files":
        return SourceAssessmentPresentation(
            source_kind="payload_files",
            source_label="Backup payload file",
            material_summary=display_path(state.payloads_file or ""),
        )
    return None


def _replace_source_summary(
    state: ReplaceRecoveryDocsTaskState,
    sections: Mapping[str, TaskSection],
) -> str:
    method = _replace_source_method(state)
    if method is None:
        return "Choose existing backup material"
    if method == "scanned_pages":
        return f"{sections['source'].summary}; {sections['freshness'].summary}"
    return sections["source"].summary


def _replacement_recovery_body(
    state: ReplaceRecoveryDocsTaskState,
    ui_state: WorkflowUiState,
) -> CompositeBodyPresentation:
    custom = (
        state.recovery_threshold != 2
        or state.recovery_document_count != 3
        or ui_state.is_touched("recovery.custom")
    )
    replacement_summary = (
        format_count(state.passphrase_replacement_count, "sheet")
        if state.passphrase_replacement_count is not None
        else ""
    )
    return CompositeBodyPresentation(
        parts=(
            CompositeBodyPartPresentation(
                "mode",
                OptionsBodyPresentation(
                    choices=(
                        ChoicePresentation(
                            "recommended",
                            "3 sheets; any 2 can restore (recommended)",
                            selected=not custom,
                        ),
                        ChoicePresentation(
                            "custom",
                            "Custom quorum",
                            selected=custom,
                        ),
                    ),
                ),
            ),
            CompositeBodyPartPresentation(
                "quorum",
                QuorumBodyPresentation(
                    threshold=state.recovery_threshold,
                    count=state.recovery_document_count,
                    visible=custom,
                ),
            ),
            CompositeBodyPartPresentation(
                "passphrase",
                OptionsBodyPresentation(
                    values=(
                        WorkspaceValue(
                            "replacement-count",
                            "Sheets to replace",
                            replacement_summary,
                        ),
                    ),
                    selects=(
                        SelectFieldPresentation(
                            key="workspace-replace-passphrase-select",
                            label="Passphrase recovery",
                            options=(
                                SelectOptionPresentation("create", "Create new"),
                                SelectOptionPresentation("replace", "Replace existing"),
                                SelectOptionPresentation("off", "Do not create"),
                            ),
                            value=_passphrase_recovery_policy(state),
                            allow_blank=False,
                        ),
                    ),
                ),
            ),
        )
    )


def _replacement_output_body(
    state: ReplaceRecoveryDocsTaskState,
) -> CompositeBodyPresentation:
    return CompositeBodyPresentation(
        parts=(
            CompositeBodyPartPresentation(
                "destination",
                DestinationBodyPresentation(
                    label="Save to",
                    display_path=(
                        display_path(state.output_dir) if state.output_dir is not None else ""
                    ),
                    empty_label="No output folder selected",
                    action=WorkspaceAction(
                        "workspace-replace-output",
                        "Choose output folder...",
                    ),
                ),
            ),
            CompositeBodyPartPresentation(
                "layout",
                OptionsBodyPresentation(
                    selects=(
                        SelectFieldPresentation(
                            key="workspace-replace-paper",
                            label="Paper size",
                            options=(
                                SelectOptionPresentation("A4", "A4"),
                                SelectOptionPresentation("LETTER", "Letter"),
                            ),
                            value=state.paper_size,
                            allow_blank=False,
                        ),
                        SelectFieldPresentation(
                            key="workspace-replace-design",
                            label="Print design",
                            options=tuple(
                                SelectOptionPresentation(key, key.title())
                                for key in ("archive", "forge", "ledger", "maritime", "sentinel")
                            ),
                            value=state.design,
                            allow_blank=False,
                        ),
                    ),
                ),
            ),
        )
    )


def _passphrase_recovery_policy(state: ReplaceRecoveryDocsTaskState) -> str:
    if not state.mint_passphrase_recovery:
        return "off"
    if state.passphrase_replacement_count is not None:
        return "replace"
    return "create"


def _pasted_text_summary(value: str | None) -> str:
    line_count = len([line for line in (value or "").splitlines() if line.strip()])
    noun = "line" if line_count == 1 else "lines"
    return f"Pasted text, {line_count} non-empty {noun}"


def _resolved_source_assessment(
    state: SourceAssessableTaskState,
    fallback: SourceAssessmentPresentation | None,
) -> SourceAssessmentPresentation | None:
    assessment = state.current_source_assessment()
    if assessment is None:
        return fallback
    return SourceAssessmentPresentation(
        source_kind=assessment.source_kind,
        source_label=assessment.source_label,
        material_summary=assessment.material_summary,
        backup_identity=assessment.backup_identity,
        version_summary=assessment.version_summary,
    )


def _source_assessment_notice(
    state: SourceAssessableTaskState,
) -> InlineNoticePresentation | None:
    assessment = state.current_source_assessment()
    if assessment is None or assessment.issue is None:
        return None
    return InlineNoticePresentation(assessment.issue.message, tone="error")


def _body_owns_notice(
    body: StepBodyPresentation,
    issue: InlineNoticePresentation | None,
) -> bool:
    if issue is None:
        return False
    if isinstance(body, SourceBodyPresentation):
        source_bodies = (body,)
    elif isinstance(body, CompositeBodyPresentation):
        source_bodies = tuple(
            part.body for part in body.parts if isinstance(part.body, SourceBodyPresentation)
        )
    else:
        source_bodies = ()
    return any(source.notice == issue for source in source_bodies)


def _folder_or_scans_method(
    backup_folder: Path | None,
    source_paths: list[Path],
) -> str | None:
    if backup_folder is not None and not source_paths:
        return "backup_folder"
    if source_paths and backup_folder is None:
        return "scanned_pages"
    return None


def _folder_or_scans_choices(selected: str | None) -> tuple[ChoicePresentation, ...]:
    return (
        ChoicePresentation(
            "backup_folder",
            "Backup folder",
            selected=selected == "backup_folder",
        ),
        ChoicePresentation(
            "scanned_pages",
            "Scanned pages",
            selected=selected == "scanned_pages",
        ),
    )


def _folder_or_scans_assessment(
    *,
    backup_folder: Path | None,
    source_paths: list[Path],
) -> SourceAssessmentPresentation | None:
    selected = _folder_or_scans_method(backup_folder, source_paths)
    if selected == "backup_folder":
        return SourceAssessmentPresentation(
            source_kind="backup_folder",
            source_label="Backup folder",
            material_summary=display_path(backup_folder or ""),
        )
    if selected == "scanned_pages":
        return SourceAssessmentPresentation(
            source_kind="scanned_pages",
            source_label="Scanned pages",
            material_summary=_paths_material_summary(source_paths),
        )
    return None


def _paths_material_summary(paths: list[Path]) -> str:
    first_path = display_path(paths[0])
    if len(paths) == 1:
        return first_path
    return f"{format_count(len(paths), 'item')}: {first_path} and {len(paths) - 1} more"


def _path_count_summary(file_count: int, folder_count: int) -> str:
    if file_count == 0 and folder_count == 0:
        return "Nothing selected"
    parts = []
    if file_count:
        parts.append(format_count(file_count, "file"))
    if folder_count:
        parts.append(format_count(folder_count, "folder"))
    return ", ".join(parts)


def _empty_summary() -> SummaryPresentation:
    return SummaryPresentation(title="", items=(), blockers=(), warnings=())


def _step_state(
    *,
    active: bool,
    prerequisites_complete: bool,
    complete: bool,
) -> StepState:
    if not prerequisites_complete:
        return "locked"
    if active:
        return "current"
    if complete:
        return "complete"
    return "available"


def _step_severity(
    *,
    warning: bool,
    issue: InlineNoticePresentation | None,
) -> StepSeverity:
    if issue is not None and issue.tone == "error":
        return "error"
    if warning or (issue is not None and issue.tone == "warning"):
        return "warning"
    return "none"


def _step_issue(
    *,
    validation: TaskValidation,
    review_summary: SummaryPresentation,
    section_keys: tuple[str, ...],
    show_error: bool,
) -> InlineNoticePresentation | None:
    if show_error:
        error = next(
            (
                issue
                for issue in validation.issues
                if issue.severity == "error" and issue.section in section_keys
            ),
            None,
        )
        if error is not None:
            return InlineNoticePresentation(error.message, tone="error")
    warning = next(
        (issue for issue in review_summary.warnings if issue.section in section_keys),
        None,
    )
    if warning is not None:
        return InlineNoticePresentation(warning.message, tone="warning")
    return None


def _sections_for_step(task: ActiveTask, step_key: str) -> tuple[str, ...]:
    return dict(GUIDED_WORKFLOW_SECTIONS.get(task, ())).get(step_key, ())


def _step_complete(validation: TaskValidation, section_keys: tuple[str, ...]) -> bool:
    return all(_section_complete(validation, section_key) for section_key in section_keys)


def _section_complete(validation: TaskValidation, section_key: str) -> bool:
    sections: Mapping[str, TaskSection] = {section.key: section for section in validation.sections}
    section = sections.get(section_key)
    if section is None or section.status not in {"ready", "warning", "optional"}:
        return False
    return not any(
        issue.severity == "error" and issue.section == section_key for issue in validation.issues
    )
