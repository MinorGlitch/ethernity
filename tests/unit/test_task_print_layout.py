from __future__ import annotations

from pathlib import Path

import pytest

from ethernity.tasks import backup
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.page_layout import with_print_layout
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.source_assessment import SourceAssessment


def test_print_layout_changes_are_validated_as_a_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    def require_pair(design: str, paper: str, **_kwargs: object) -> None:
        if (paper, design) not in {("A4", "archive"), ("LETTER", "forge")}:
            raise ValueError("Unsupported paper and design combination")

    monkeypatch.setattr(backup, "require_workflow_page_size", require_pair)
    state = BackupTaskState(paper_size="A4", design="archive")
    updated = with_print_layout(state, paper_size="LETTER", design="forge")
    assert (updated.paper_size, updated.design) == ("LETTER", "forge")
    assert (state.paper_size, state.design) == ("A4", "archive")
    with pytest.raises(ValueError, match="Unsupported paper and design"):
        with_print_layout(state, paper_size="LETTER", design="archive")
    assert (state.paper_size, state.design) == ("A4", "archive")


def test_paper_override_keeps_design_inherited() -> None:
    state = BackupTaskState()
    updated = with_print_layout(state, paper_size="LETTER", design=state.design)
    assert updated.model_fields_set == {"paper_size"}
    assert "design" not in updated.model_fields_set
    unchanged = with_print_layout(state, paper_size=state.paper_size, design=state.design)
    assert unchanged.model_fields_set == set()


def test_print_edit_preserves_current_decoded_source_details() -> None:
    state = RebuildTaskState(source_paths=[Path("backup.pdf")])
    request = state.source_assessment_request()
    assert request is not None
    assessment = SourceAssessment(
        source_kind=request.source_kind,
        source_label=request.source_label,
        source_summary=request.source_summary,
        backup_identity="Decoded backup",
        has_updates=True,
    )
    assert state.store_source_assessment(request, assessment)
    updated = with_print_layout(state, paper_size="LETTER", design=state.design)
    assert updated.current_source_assessment() is assessment
