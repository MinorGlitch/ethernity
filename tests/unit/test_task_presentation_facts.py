from __future__ import annotations

from pathlib import Path

import pytest

from ethernity.app.workflow_registry import WORKFLOWS, WorkflowDefinition, build_guided_workflow
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.backup_estimate import BackupEstimate
from ethernity.tasks.backup_facts import RecoveryMethod, SheetQuorum
from ethernity.tasks.models import TaskExecutionPlan, TaskValidation
from ethernity.tasks.presentation.builder import workspace_groups
from ethernity.tasks.presentation.models import SummaryPresentation
from ethernity.tasks.presentation.registry import build_review_details, task_presenter
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.task_types import TaskState


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("recommended_shards", SheetQuorum(2, 3)),
        ("custom_shards", SheetQuorum(3, 5)),
        ("single_phrase", None),
    ],
)
def test_selected_policy_drives_request_preview_workspace_and_review(
    method: RecoveryMethod,
    expected: SheetQuorum | None,
) -> None:
    state = BackupTaskState(
        input_paths=[Path("records.txt")],
        recovery_method="custom_shards",
        shard_threshold=3,
        shard_count=5,
    )
    state.recovery_method = method
    facts = state.facts()
    request = state.to_backup_request()
    assert facts.recovery == expected
    assert (request.shard_threshold, request.shard_count) == (
        (expected.required, expected.total) if expected is not None else (None, None)
    )
    group = next(
        group
        for group in workspace_groups("backup", state, state.validate_task())
        if group.key == "recovery"
    )
    assert (
        next(value.value for value in group.values if value.key == "recovery")
        == facts.recovery_summary
    )
    assert next(choice.key for choice in group.choices if choice.selected) == method
    details = {
        item.label: item.value
        for item in build_review_details("backup", state, TaskExecutionPlan(summary="Backup"))
    }
    if expected is None:
        assert details["Recovery"] == "One recovery phrase"
        assert any(item.label == "One recovery phrase" for item in state.preview().items)
    else:
        assert (
            details["Recovery"] == f"{expected.total} sheets, {expected.required} needed to restore"
        )
        assert any(
            item.label == f"{expected.total} recovery sheets" for item in state.preview().items
        )
    # Switching policies preserves custom values for when the user returns to them.
    assert (state.shard_threshold, state.shard_count) == (3, 5)


@pytest.mark.parametrize(
    ("threshold", "count", "expected"),
    [(None, None, SheetQuorum(3, 5)), (2, 4, SheetQuorum(2, 4))],
)
def test_signing_sheet_counts_share_the_resolved_recovery_policy(
    threshold: int | None,
    count: int | None,
    expected: SheetQuorum,
) -> None:
    state = BackupTaskState(
        recovery_method="custom_shards",
        shard_threshold=3,
        shard_count=5,
        signing_key_mode="sharded",
        signing_key_shard_threshold=threshold,
        signing_key_shard_count=count,
    )
    facts = state.facts()
    assert facts.signing_recovery == expected
    assert f"{expected.total} signing-key recovery sheets" in facts.document_summary
    assert any(
        item.label == f"{expected.total} signing-key recovery sheets"
        for item in state.preview().items
    )
    assert f"{expected.total} key sheets" in facts.compact_document_summary


def test_document_inventory_has_one_owner_for_all_presentations() -> None:
    state = BackupTaskState(recovery_method="single_phrase")
    facts = state.facts()
    expected = {doc.label for doc in facts.documents}
    assert expected <= {item.label for item in state.preview().items}
    details = build_review_details("backup", state, TaskExecutionPlan(summary="Backup"))
    assert (
        next(detail.value for detail in details if detail.label == "Documents")
        == facts.document_summary
    )
    assert not any(doc.kind == "signing" for doc in facts.documents)
    assert ("Document inventory PDF" in facts.document_summary) == facts.include_inventory


def test_inherited_signing_policy_is_not_reported_as_embedded() -> None:
    state = BackupTaskState(signing_key_mode=None)
    assert state.facts().signing_summary == "From settings"
    assert "From settings" in next(
        section.summary for section in state.sections() if section.key == "advanced"
    )


def test_stale_estimate_is_not_shared_with_presenters(tmp_path: Path) -> None:
    state = BackupTaskState(input_paths=[tmp_path / "first.txt"])
    request = state.estimate_request()
    assert request is not None
    estimate = BackupEstimate(
        file_count=1, input_bytes=123, document_bytes=456, backup_pages=2, qr_count=3
    )
    assert state.store_estimate(request, estimate)
    assert state.facts().estimate == estimate
    state.input_paths = [tmp_path / "second.txt"]
    assert state.facts().estimate is None
    assert "About" not in state.facts().compact_document_summary
    assert not any(
        detail.label == "Backup pages"
        for detail in build_review_details("backup", state, TaskExecutionPlan(summary="Backup"))
    )


@pytest.mark.parametrize("definition", WORKFLOWS, ids=lambda definition: definition.key)
def test_every_workflow_routes_to_its_own_task_presenter(definition: WorkflowDefinition) -> None:
    state = definition.fresh_state()
    assert isinstance(state, task_presenter(definition.key).state_type)
    assert isinstance(state, TaskState)
    workspace_groups(definition.key, state, state.validate_task())
    build_review_details(definition.key, state, state.execution_plan())


def test_mismatched_task_state_is_rejected_by_all_presenters() -> None:
    state = RestoreTaskState()
    with pytest.raises(TypeError, match="Expected BackupTaskState"):
        workspace_groups("backup", state, TaskValidation(sections=()))
    with pytest.raises(TypeError, match="Expected BackupTaskState"):
        build_review_details("backup", state, TaskExecutionPlan(summary="Backup"))
    with pytest.raises(TypeError, match="Expected RestoreTaskState"):
        build_guided_workflow(
            task="restore",
            state=BackupTaskState(),
            validation=TaskValidation(sections=()),
            ui_state=WorkflowUiState.start("source"),
            review_summary=SummaryPresentation(title="", items=(), blockers=(), warnings=()),
            review_label="Review",
        )


def test_invalid_separate_key_choice_is_not_described_as_embedded() -> None:
    state = BackupTaskState(recovery_method="single_phrase", signing_key_mode="sharded")
    assert "key sheets" in state.facts().signing_summary
    assert any(
        issue.code == "BACKUP_SIGNING_KEY_SHARDS_REQUIRE_RECOVERY_DOCS"
        for issue in state.validate_task().issues
    )
