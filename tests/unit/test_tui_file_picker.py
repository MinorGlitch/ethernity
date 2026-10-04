from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Button, DirectoryTree, Input, Static

from ethernity.app.application import EthernityApp
from ethernity.app.path_selection import complete_picker_path, resolve_picker_path
from ethernity.app.screens.file_picker import FilePickerMode, FilePickerScreen


def test_picker_path_resolution_uses_browsing_folder_and_expands_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "browse"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    assert resolve_picker_path("notes.txt", root) == root / "notes.txt"
    assert resolve_picker_path("../notes.txt", root) == tmp_path / "notes.txt"
    assert resolve_picker_path("~/notes.txt", root) == home / "notes.txt"
    assert resolve_picker_path(str(tmp_path / "notes.txt"), root) == tmp_path / "notes.txt"
    with pytest.raises(ValueError, match="Enter a file or folder path"):
        resolve_picker_path("", root)
    with pytest.raises(ValueError, match="null character"):
        resolve_picker_path("invalid\x00path", root)


def test_path_completion_preserves_relative_and_home_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "documents").mkdir()
    (tmp_path / "documentary").mkdir()
    (tmp_path / "documents" / "backup.pdf").touch()
    (tmp_path / "photos").mkdir()
    (tmp_path / "photo.txt").touch()
    monkeypatch.setenv("HOME", str(tmp_path))

    assert complete_picker_path("do", tmp_path, include_files=True).value == "document"
    assert complete_picker_path("documents", tmp_path, include_files=True).value == "documents/"
    assert (
        complete_picker_path("documents/ba", tmp_path, include_files=True).value
        == "documents/backup.pdf"
    )
    assert complete_picker_path("~/docum", tmp_path, include_files=True).value == "~/document"
    assert complete_picker_path("phot", tmp_path, include_files=False).value == "photos/"
    assert complete_picker_path("missing", tmp_path, include_files=True).value == "missing"
    with pytest.raises(ValueError, match="containing folder does not exist"):
        complete_picker_path("missing/child", tmp_path, include_files=True)


def test_open_picker_entered_files_append_and_entered_folders_only_navigate(tmp_path: Path) -> None:
    existing = tmp_path / "existing.txt"
    existing.touch()
    folder = tmp_path / "documents"
    folder.mkdir()
    entered = folder / "backup.pdf"
    entered.touch()

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            picker = FilePickerScreen(
                title="Choose files and folders",
                prompt="Paste a path or browse.",
                root=tmp_path,
                mode=FilePickerMode.OPEN_PATHS,
                selected_paths=(existing,),
            )
            await app.push_screen(picker)
            await pilot.pause()
            location = picker.query_one("#file-picker-location", Input)
            assert location.has_focus
            assert "Ctrl+Space" in str(picker.query_one("#file-picker-hint", Static).content)

            location.value = "documents"
            await pilot.press("enter")
            await pilot.pause()
            assert picker._root == folder
            assert picker._selected_paths == (existing,)
            assert Path(picker.query_one("#file-picker-tree", DirectoryTree).path) == folder

            location.value = "backup.pdf"
            location.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert picker._selected_paths == (existing, entered)
            assert not picker.query_one("#file-picker-choose", Button).disabled

            location.value = str(entered)
            await pilot.press("enter")
            await pilot.pause()
            assert picker._selected_paths == (existing, entered)

            await pilot.click("#file-picker-current")
            await pilot.pause()
            assert picker._selected_paths == (existing, entered, folder)

    asyncio.run(run())


def test_open_picker_accepts_home_paths_and_rejects_missing_paths_without_losing_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    entered = home / "backup.pdf"
    entered.touch()
    existing = tmp_path / "existing.txt"
    existing.touch()
    monkeypatch.setenv("HOME", str(home))

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            picker = FilePickerScreen(
                title="Choose files",
                prompt="Paste a path or browse.",
                root=tmp_path,
                mode=FilePickerMode.OPEN_FILES,
                selected_paths=(existing,),
            )
            await app.push_screen(picker)
            await pilot.pause()
            location = picker.query_one("#file-picker-location", Input)
            location.value = "~/backup.pdf"
            await pilot.press("enter")
            await pilot.pause()
            assert picker._selected_paths == (existing, entered)

            location.value = "missing.pdf"
            await pilot.press("enter")
            await pilot.pause()
            assert picker._selected_paths == (existing, entered)
            assert picker.query_one("#file-picker-choose", Button).disabled
            assert "does not exist" in str(picker.query_one("#file-picker-error", Static).content)

            location.value = str(entered)
            await pilot.press("enter")
            await pilot.pause()
            assert not picker.query_one("#file-picker-choose", Button).disabled
            assert str(picker.query_one("#file-picker-error", Static).content) == ""

    asyncio.run(run())


def test_open_directory_path_requires_explicit_folder_selection_and_rejects_files(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "documents"
    folder.mkdir()
    file = tmp_path / "backup.pdf"
    file.touch()

    async def run() -> None:
        results: list[tuple[Path, ...] | None] = []
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            picker = FilePickerScreen(
                title="Choose folder",
                prompt="Paste a path or browse.",
                root=tmp_path,
                mode=FilePickerMode.OPEN_DIRECTORY,
            )
            await app.push_screen(picker, results.append)
            await pilot.pause()
            location = picker.query_one("#file-picker-location", Input)
            location.value = str(file)
            await pilot.press("enter")
            await pilot.pause()
            assert not picker._selected_paths
            assert "path is a file" in str(picker.query_one("#file-picker-error", Static).content)

            location.value = str(folder)
            await pilot.press("enter")
            await pilot.pause()
            assert picker._root == folder
            assert not picker._selected_paths
            assert picker.query_one("#file-picker-choose", Button).disabled
            await pilot.click("#file-picker-current")
            await pilot.pause()
            assert results == [(folder,)]

    asyncio.run(run())


@pytest.mark.parametrize("mode", (FilePickerMode.SAVE_FILE, FilePickerMode.SAVE_DIRECTORY))
def test_save_picker_accepts_full_new_path_and_rejects_missing_parent(
    tmp_path: Path, mode: FilePickerMode
) -> None:
    target = tmp_path / ("kit.pdf" if mode == FilePickerMode.SAVE_FILE else "backup")

    async def run() -> None:
        results: list[tuple[Path, ...] | None] = []
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            picker = FilePickerScreen(
                title="Choose destination",
                prompt="Paste a path or browse.",
                root=tmp_path,
                mode=mode,
            )
            await app.push_screen(picker, results.append)
            await pilot.pause()
            await pilot.press("ctrl+l")
            location = picker.query_one("#file-picker-location", Input)
            assert location.has_focus
            location.value = str(tmp_path / "missing-parent" / target.name)
            await pilot.press("enter")
            await pilot.pause()
            assert picker.query_one("#file-picker-choose", Button).disabled
            assert "containing folder does not exist" in str(
                picker.query_one("#file-picker-error", Static).content
            )

            location.value = str(target)
            await pilot.press("enter")
            await pilot.pause()
            assert picker.query_one("#file-picker-name", Input).value == target.name
            assert picker._selected_paths == (tmp_path,)
            assert not picker.query_one("#file-picker-choose", Button).disabled
            await pilot.click("#file-picker-choose")
            await pilot.pause()
            assert results == [(target,)]

    asyncio.run(run())


def test_picker_completion_shortcut_fills_path_without_modifying_selection(tmp_path: Path) -> None:
    (tmp_path / "documents").mkdir()
    existing = tmp_path / "existing.txt"
    existing.touch()

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            picker = FilePickerScreen(
                title="Choose files",
                prompt="Paste a path or browse.",
                root=tmp_path,
                mode=FilePickerMode.OPEN_FILES,
                selected_paths=(existing,),
            )
            await app.push_screen(picker)
            await pilot.pause()
            location = picker.query_one("#file-picker-location", Input)
            location.value = "doc"
            await pilot.press("ctrl+space")
            await pilot.pause()
            assert location.value == "documents/"
            assert picker._selected_paths == (existing,)
            assert picker._root == tmp_path

    asyncio.run(run())


def test_path_completion_keeps_symlink_spelling(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.touch()
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    completion = complete_picker_path("link.txt", tmp_path, include_files=True)

    assert completion.value == "link.txt"
