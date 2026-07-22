from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState

_TASK_STATE_TYPES: tuple[type[BaseModel], ...] = (
    BackupTaskState,
    AddFilesTaskState,
    RebuildTaskState,
    ReplaceRecoveryDocsTaskState,
    PrintKitTaskState,
)


@pytest.mark.parametrize("state_type", _TASK_STATE_TYPES)
def test_task_paper_sizes_normalize_on_load_assignment_and_json_round_trip(
    state_type: type[BaseModel],
) -> None:
    state = state_type.model_validate({"paper_size": " letter "})

    assert state.model_dump()["paper_size"] == "LETTER"
    setattr(state, "paper_size", " a4 ")
    assert state.model_dump()["paper_size"] == "A4"

    restored = state_type.model_validate_json(state.model_dump_json())
    assert restored.model_dump()["paper_size"] == "A4"


@pytest.mark.parametrize("state_type", _TASK_STATE_TYPES)
def test_task_paper_sizes_reject_unregistered_names(state_type: type[BaseModel]) -> None:
    with pytest.raises(ValidationError, match="unknown paper size"):
        state_type.model_validate({"paper_size": "TABLOID"})


def test_add_files_preserves_unspecified_paper_size() -> None:
    assert AddFilesTaskState(paper_size=None).paper_size is None
