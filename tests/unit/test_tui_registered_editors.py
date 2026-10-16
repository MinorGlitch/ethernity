from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from ethernity.app import events
from ethernity.app.application import EthernityApp
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.file_picker import FilePickerMode
from ethernity.tasks.task_types import TaskKey

PATH_TASKS: tuple[TaskKey, ...] = (
    "backup",
    "restore",
    "add_files",
    "rebuild",
    "replace_recovery_docs",
    "kit",
)


@pytest.mark.parametrize(
    ("task", "callback", "attribute", "mode"),
    [
        ("backup", "_apply_backup_output_picked", "output_dir", FilePickerMode.SAVE_DIRECTORY),
        ("restore", "_apply_restore_output_picked", "output_path", FilePickerMode.SAVE_DIRECTORY),
        (
            "add_files",
            "_apply_add_files_output_picked",
            "output_dir",
            FilePickerMode.SAVE_DIRECTORY,
        ),
        ("rebuild", "_apply_rebuild_output_picked", "output_dir", FilePickerMode.SAVE_DIRECTORY),
        (
            "replace_recovery_docs",
            "_apply_replace_recovery_output_picked",
            "output_dir",
            FilePickerMode.SAVE_DIRECTORY,
        ),
        ("kit", "_apply_kit_output_picked", "output_path", FilePickerMode.SAVE_FILE),
    ],
)
def test_registered_destination_opens_the_correct_picker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    task: TaskKey,
    callback: str,
    attribute: str,
    mode: FilePickerMode,
) -> None:
    app = EthernityApp()
    app.active_task = task
    path = tmp_path / ("kit.pdf" if task == "kit" else "destination")
    setattr(app._current_state(), attribute, path)
    picker = AsyncMock()
    monkeypatch.setattr(app, "_pick_paths", picker)
    asyncio.run(app.action_edit_output())
    options = picker.call_args.kwargs
    assert options["selected_paths"] == (tmp_path,)
    assert options["save_name"] == path.name
    assert options["mode"] == mode
    assert options["callback"].__self__ is app
    assert options["callback"].__name__ == callback
    assert options["allow_clear"] == (task != "kit")


@pytest.mark.parametrize("task", PATH_TASKS[:-1])
def test_registered_passphrase_editor_changes_only_its_task(
    monkeypatch: pytest.MonkeyPatch,
    task: TaskKey,
) -> None:
    app = EthernityApp()
    app.active_task = task
    app._current_state().passphrase = "old phrase"
    if task != "backup":
        app._current_state().recovery_documents = [Path("sheet.pdf")]
    push = AsyncMock()
    monkeypatch.setattr(app, "_push_editor", push)
    monkeypatch.setattr(app, "refresh_task_view", Mock())
    asyncio.run(app.action_edit_passphrase())
    editor, callback = push.call_args.args
    assert isinstance(editor, EditFieldScreen)
    callback("new phrase")
    assert app._current_state().passphrase == "new phrase"
    if task != "backup":
        assert app._current_state().recovery_documents == []
        assert app.backup_state.passphrase is None
    else:
        assert app.restore_state.passphrase is None


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("backup", "_apply_backup_files_picked"),
        ("restore", "_apply_restore_sources_picked"),
        ("add_files", "_apply_add_files_inputs_picked"),
        ("rebuild", "_apply_rebuild_source_picked"),
        ("replace_recovery_docs", "_apply_replace_recovery_sources_picked"),
    ],
)
def test_primary_picker_uses_task_specific_selection_and_callback(
    monkeypatch: pytest.MonkeyPatch,
    task: TaskKey,
    expected: str,
) -> None:
    app = EthernityApp()
    app.active_task = task
    state: Any = app._current_state()
    paths = [Path("first.txt"), Path("second.txt")]
    if task in {"backup", "add_files"}:
        state.input_paths = paths[:1]
        state.input_dirs = paths[1:]
    else:
        state.source_paths = paths
    picker = AsyncMock()
    monkeypatch.setattr(app, "_pick_paths", picker)
    asyncio.run(app.action_edit_primary())
    options = picker.call_args.kwargs
    assert tuple(options["selected_paths"]) == tuple(paths)
    assert options["callback"].__self__ is app
    assert options["callback"].__name__ == expected


@pytest.mark.parametrize("task", ("restore", "add_files", "rebuild", "replace_recovery_docs"))
def test_destination_event_updates_its_owner_instead_of_the_active_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    task: TaskKey,
) -> None:
    app = EthernityApp()
    app.active_task = "backup"
    monkeypatch.setattr(events, "_owning_task", lambda _editor: task)
    monkeypatch.setattr(app, "refresh_task_view", Mock())
    path = tmp_path / "recovered"
    event: Any = SimpleNamespace(editor=object(), value=str(path), stop=Mock())
    app.on_destination_editor_value_changed(event)
    attribute = "output_path" if task == "restore" else "output_dir"
    assert getattr(app._state_for_task(task), attribute) == path
    assert app.backup_state.output_dir != path
    assert app.workflow_ui_states[task].is_touched("destination" if task == "restore" else "output")


def test_recommended_recovery_and_signing_editor_use_the_same_quorum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = EthernityApp()
    state = app.backup_state
    state.recovery_method = "custom_shards"
    state.shard_count = 5
    state.shard_threshold = 3
    monkeypatch.setattr(app, "refresh_task_view", Mock())
    app._apply_backup_recovery("recommended")
    request = state.to_backup_request()
    assert (request.shard_threshold, request.shard_count) == (2, 3)
    assert (state.shard_threshold, state.shard_count) == (3, 5)
    push = AsyncMock()
    monkeypatch.setattr(app, "_push_editor", push)
    asyncio.run(app._edit_backup_signing_key_shards())
    editor = push.call_args.args[0]
    assert isinstance(editor, EditFieldScreen)
    # The edit form must start from the actual requested counts, not dormant custom counts.
    assert editor._value == "2/3"
