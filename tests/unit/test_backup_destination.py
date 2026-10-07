"""Backup destinations are always parents, regardless of whether they exist."""

from pathlib import Path

import pytest

from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.file_summary import display_path
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.workflows.shared.outputs import (
    backup_output_path,
    commit_prepared_output_dir,
    discard_prepared_output_dir,
    prepare_backup_output_dir,
)
from tests.support.environment import home_environment


@pytest.mark.parametrize("destination", [None, ".", "~", "~/new/nested", "existing", "new"])
def test_backup_always_publishes_in_a_named_child(tmp_path, monkeypatch, destination) -> None:
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    for name, value in home_environment(home).items():
        monkeypatch.setenv(name, value)
    (tmp_path / "existing").mkdir()
    parent = Path(destination).expanduser() if destination is not None else Path(".")
    if parent.is_dir():
        (parent / "keep.txt").write_text("existing content")

    final, staging = prepare_backup_output_dir(destination, "deadbeef")

    assert Path(final) == parent / "backup-deadbeef"
    assert Path(staging).parent == Path(final).parent
    assert not Path(final).exists()
    (Path(staging) / "qr_document.pdf").write_bytes(b"staged document")
    commit_prepared_output_dir(staging, final)
    assert (Path(final) / "qr_document.pdf").read_bytes() == b"staged document"
    assert not Path(staging).exists()
    if (parent / "keep.txt").exists():
        assert (parent / "keep.txt").read_text() == "existing content"

    next_final, next_staging = prepare_backup_output_dir(destination, "feedbeef")
    assert Path(next_final) == parent / "backup-feedbeef"
    discard_prepared_output_dir(next_staging)
    assert Path(final).is_dir()
    assert not Path(next_final).exists()


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_existing_backup_is_never_overwritten(tmp_path, kind) -> None:
    final = backup_output_path(tmp_path, "deadbeef")
    if kind == "directory":
        final.mkdir()
        (final / "keep.txt").write_text("original")
    elif kind == "file":
        final.write_text("original")
    else:
        try:
            final.symlink_to(tmp_path / "missing", target_is_directory=True)
        except OSError:
            pytest.skip("Symlink creation unavailable")
    before = tuple(tmp_path.iterdir())

    with pytest.raises(ValueError, match="backup output already exists"):
        prepare_backup_output_dir(tmp_path, "deadbeef")

    assert tuple(tmp_path.iterdir()) == before
    if kind == "directory":
        assert (final / "keep.txt").read_text() == "original"
    elif kind == "file":
        assert final.read_text() == "original"
    else:
        assert final.is_symlink()


@pytest.mark.parametrize("state_type", [BackupTaskState, RebuildTaskState])
@pytest.mark.parametrize("existing", [False, True])
def test_task_preview_names_the_child_without_parent_overwrite_warning(
    tmp_path, state_type, existing
) -> None:
    parent = tmp_path / "backups"
    if existing:
        parent.mkdir()
    state = state_type(output_dir=parent)
    expected = parent / "backup-<id>"
    output = next(section for section in state.sections() if section.key == "output")

    assert output.status == "ready"
    assert output.summary == display_path(expected)
    assert state.execution_plan().output_paths == (expected,)
    assert not any(warning.section == "output" for warning in state.preview().warnings)
    assert parent.exists() is existing


@pytest.mark.parametrize("state_type", [BackupTaskState, RebuildTaskState])
@pytest.mark.parametrize("nested", [False, True])
def test_task_rejects_file_as_destination_parent(tmp_path, state_type, nested) -> None:
    file = tmp_path / "file.txt"
    file.write_text("keep")
    parent = file / "new" if nested else file
    state = state_type(output_dir=parent)
    issues = state.validate_task().issues
    assert any(issue.code == "BACKUP_DESTINATION_NOT_DIRECTORY" for issue in issues)
    assert (
        next(section for section in state.sections() if section.key == "output").status == "blocked"
    )
    with pytest.raises((FileExistsError, NotADirectoryError)):
        prepare_backup_output_dir(parent, "deadbeef")
    assert file.read_text() == "keep"
