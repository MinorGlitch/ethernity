#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Label, OptionList, Static
from textual.widgets.option_list import Option


class FilePickerScreen(ModalScreen[tuple[Path, ...] | None]):
    """Modal file picker built on Textual's DirectoryTree."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("backspace", "remove_selected", "Remove"),
        ("alt+up", "go_up", "Up"),
    ]

    def __init__(
        self,
        *,
        title: str,
        prompt: str,
        root: Path,
        selected_paths: Sequence[Path] = (),
        allow_files: bool = True,
        allow_dirs: bool = True,
        multiple: bool = True,
        save_name: str | None = None,
        save_placeholder: str = "",
        choose_label: str = "Choose",
    ) -> None:
        super().__init__()
        self._picker_title = title
        self._prompt = prompt
        self._root = _existing_directory(root)
        self._selected_paths = tuple(Path(path) for path in selected_paths if str(path))
        self._allow_files = allow_files
        self._allow_dirs = allow_dirs
        self._multiple = multiple
        self._save_name = save_name
        self._save_placeholder = save_placeholder
        self._choose_label = choose_label

    def compose(self) -> ComposeResult:
        with Vertical(id="file-picker-modal"):
            yield Static(self._picker_title, id="file-picker-title")
            yield Label(self._prompt, id="file-picker-prompt")
            with Horizontal(id="file-picker-body"):
                with Vertical(id="file-picker-browser"):
                    with Horizontal(id="file-picker-location-row"):
                        yield Button("Up", id="file-picker-up")
                        yield Static(_display_path(self._root), id="file-picker-location")
                    yield DirectoryTree(self._root, id="file-picker-tree")
                with Vertical(id="file-picker-side"):
                    yield Label("Selected", id="file-picker-selected-title")
                    yield OptionList(id="file-picker-selected", compact=True)
                    if self._save_name is not None:
                        yield Label("Name", id="file-picker-name-title")
                        yield Input(
                            self._save_name,
                            placeholder=self._save_placeholder,
                            id="file-picker-name",
                        )
            with Horizontal(id="file-picker-actions"):
                yield Button(self._choose_label, id="file-picker-choose", variant="primary")
                yield Button("Use this folder", id="file-picker-current")
                yield Button("Clear", id="file-picker-clear")
                yield Button("Cancel", id="file-picker-cancel")

    def on_mount(self) -> None:
        self._refresh_selected()
        self._refresh_location()
        if self._save_name is None:
            self.query_one("#file-picker-tree", DirectoryTree).focus()
        else:
            self.query_one("#file-picker-name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "file-picker-name":
            self._choose()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        path = Path(event.path)
        if self._save_name is not None:
            self._selected_paths = (path.parent,)
            self.query_one("#file-picker-name", Input).value = path.name
            self._refresh_selected()
        elif self._allow_files:
            self._add_path(path)

    def on_directory_tree_directory_selected(
        self,
        event: DirectoryTree.DirectorySelected,
    ) -> None:
        event.stop()
        path = Path(event.path)
        if self._save_name is not None:
            self._selected_paths = (path,)
            self._refresh_selected()
        elif self._allow_dirs:
            self._add_path(path)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "file-picker-selected":
            return
        event.stop()
        self._remove_selected_at(event.option_index)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "file-picker-choose":
            self._choose()
        elif button_id == "file-picker-up":
            self._go_up()
        elif button_id == "file-picker-current":
            self._use_current_folder()
        elif button_id == "file-picker-clear":
            self.dismiss(())
        else:
            self.dismiss(None)

    def action_remove_selected(self) -> None:
        selected = self.query_one("#file-picker-selected", OptionList)
        highlighted = selected.highlighted
        if highlighted is None:
            return
        self._remove_selected_at(highlighted)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_go_up(self) -> None:
        self._go_up()

    def set_selected_paths(self, paths: Sequence[Path]) -> None:
        """Set selected paths from tests or parent screens."""
        self._selected_paths = tuple(Path(path) for path in paths if str(path))
        if self.is_mounted:
            self._refresh_selected()

    def _add_path(self, path: Path) -> None:
        if self._multiple:
            paths = list(self._selected_paths)
            if _find_path_index(paths, path) is None:
                paths.append(path)
            self._selected_paths = tuple(paths)
        else:
            self._selected_paths = (path,)
        self._refresh_selected()

    def _remove_selected_at(self, index: int) -> None:
        if index < 0 or index >= len(self._selected_paths):
            return
        paths = list(self._selected_paths)
        del paths[index]
        self._selected_paths = tuple(paths)
        self._refresh_selected()

    def _choose(self) -> None:
        if self._save_name is not None:
            name = self.query_one("#file-picker-name", Input).value.strip()
            base = self._selected_paths[0] if self._selected_paths else self._root
            self.dismiss((base / name,) if name else (base,))
            return
        if not self._selected_paths:
            self.notify("Choose at least one path first.", severity="warning")
            return
        self.dismiss(self._selected_paths)

    def _use_current_folder(self) -> None:
        tree = self.query_one("#file-picker-tree", DirectoryTree)
        node = tree.cursor_node
        path = Path(getattr(node.data, "path", self._root)) if node is not None else self._root
        folder = path if path.is_dir() else path.parent
        if self._save_name is not None:
            self._selected_paths = (folder,)
            self._refresh_selected()
            return
        if self._allow_dirs:
            self._add_path(folder)

    def _go_up(self) -> None:
        parent = self._root.parent
        if parent == self._root:
            return
        self._set_root(parent)

    def _set_root(self, root: Path) -> None:
        self._root = _existing_directory(root)
        tree = self.query_one("#file-picker-tree", DirectoryTree)
        tree.path = self._root
        tree.focus()
        self._refresh_location()

    def _refresh_location(self) -> None:
        self.query_one("#file-picker-location", Static).update(_display_path(self._root))
        self.query_one("#file-picker-up", Button).disabled = self._root.parent == self._root

    def _refresh_selected(self) -> None:
        selected = self.query_one("#file-picker-selected", OptionList)
        selected.set_options(
            [_path_option(path, index) for index, path in enumerate(self._paths())]
        )

    def _paths(self) -> tuple[Path, ...]:
        if self._save_name is None:
            return self._selected_paths
        return (self._selected_paths[0] if self._selected_paths else self._root,)


def _existing_directory(path: Path) -> Path:
    candidate = _normalized_path(path)
    if candidate.is_dir():
        return candidate
    if candidate.parent.is_dir():
        return candidate.parent
    return Path.cwd().resolve()


def _path_option(path: Path, index: int) -> Option:
    text = Text()
    text.append(_display_path(path), style="bold")
    return Option(text, id=str(index))


def _display_path(path: Path) -> str:
    try:
        return str(_normalized_path(path).relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(_normalized_path(path))


def _find_path_index(paths: Sequence[Path], path: Path) -> int | None:
    normalized = _normalized_path(path)
    for index, candidate in enumerate(paths):
        if _normalized_path(candidate) == normalized:
            return index
    return None


def _normalized_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)
