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

from enum import StrEnum
from pathlib import Path
from typing import Sequence

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.geometry import Size
from textual.widgets import Button, DirectoryTree, Input, Label, SelectionList, Static
from textual.widgets.selection_list import Selection

from ethernity.app.screens.modal import EthernityModalScreen
from ethernity.app.widgets.actions import ActionButton, modal_action_row


class FilePickerMode(StrEnum):
    """Supported picker contracts.

    A mode describes what the caller expects back. Keeping this explicit prevents
    incompatible boolean combinations such as a save-file picker that also claims
    to disallow files.
    """

    OPEN_PATHS = "open_paths"
    OPEN_FILES = "open_files"
    OPEN_DIRECTORY = "open_directory"
    SAVE_FILE = "save_file"
    SAVE_DIRECTORY = "save_directory"

    @property
    def is_save(self) -> bool:
        return self in {self.SAVE_FILE, self.SAVE_DIRECTORY}

    @property
    def allows_files(self) -> bool:
        return self in {self.OPEN_PATHS, self.OPEN_FILES, self.SAVE_FILE}

    @property
    def allows_directories(self) -> bool:
        return self in {
            self.OPEN_PATHS,
            self.OPEN_DIRECTORY,
            self.SAVE_FILE,
            self.SAVE_DIRECTORY,
        }


class FilePickerScreen(EthernityModalScreen[tuple[Path, ...] | None]):
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
        mode: FilePickerMode,
        selected_paths: Sequence[Path] = (),
        multiple: bool = True,
        save_name: str = "",
        save_placeholder: str = "",
        choose_label: str = "Select",
        allow_clear: bool = True,
    ) -> None:
        super().__init__()
        self._picker_title = title
        self._prompt = prompt
        self._root = _existing_directory(root)
        self._selected_paths = tuple(Path(path) for path in selected_paths if str(path))
        self._mode = mode
        self._multiple = multiple and not mode.is_save and mode != FilePickerMode.OPEN_DIRECTORY
        self._save_name = save_name
        self._save_placeholder = save_placeholder
        self._choose_label = choose_label
        self._allow_clear = allow_clear

    def compose(self) -> ComposeResult:
        modal_classes = "save-mode" if self._mode.is_save else "open-mode"
        with Vertical(id="file-picker-modal", classes=modal_classes):
            yield Static(self._picker_title, id="file-picker-title")
            yield Label(self._prompt, id="file-picker-prompt")
            with Horizontal(id="file-picker-body"):
                with Vertical(id="file-picker-browser"):
                    with Horizontal(id="file-picker-location-row"):
                        yield Button("Up", id="file-picker-up")
                        yield Static("", classes="action-button-gap")
                        yield Static(
                            _display_path(self._root),
                            id="file-picker-location",
                            markup=False,
                        )
                    yield DirectoryTree(self._root, id="file-picker-tree")
                with Vertical(id="file-picker-side"):
                    with Horizontal(id="file-picker-selected-header"):
                        yield Label(self._selection_title(), id="file-picker-selected-title")
                        yield Button("Remove", id="file-picker-remove", compact=True)
                    yield SelectionList[int](id="file-picker-selected", compact=True)
                    if self._mode.is_save:
                        yield Label(self._name_title(), id="file-picker-name-title")
                        yield Input(
                            self._save_name,
                            placeholder=self._save_placeholder,
                            id="file-picker-name",
                        )
                        yield Static("", id="file-picker-error", markup=False)
            if not self._mode.is_save:
                yield Static("", id="file-picker-error", markup=False)
            actions = [ActionButton(self._choose_label, "file-picker-choose", variant="primary")]
            if self._mode.allows_directories:
                actions.append(
                    ActionButton(
                        self._current_folder_action_label(compact=False),
                        "file-picker-current",
                    )
                )
            if self._allow_clear and self._selected_paths:
                actions.append(ActionButton("Clear", "file-picker-clear"))
            actions.append(ActionButton("Cancel", "file-picker-cancel"))
            yield modal_action_row(
                "file-picker-actions",
                *actions,
                align_end=False,
                equal_width=True,
            )

    def on_mount(self) -> None:
        self._sync_responsive_layout(self.size)
        self._refresh_selected()
        self._refresh_location()
        self._refresh_choose_state()
        if not self._mode.is_save:
            self.query_one("#file-picker-tree", DirectoryTree).focus()
        else:
            self.query_one("#file-picker-name", Input).focus()
            self._refresh_save_validation(show_message=True)

    def on_resize(self, event: events.Resize) -> None:
        self._sync_responsive_layout(event.size)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "file-picker-name":
            self._refresh_save_validation(show_message=True)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "file-picker-name":
            self._choose()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        path = Path(event.path)
        if self._mode == FilePickerMode.SAVE_FILE:
            self._selected_paths = (path.parent,)
            self.query_one("#file-picker-name", Input).value = path.name
            self._refresh_selection_state()
        elif self._mode.allows_files and not self._mode.is_save:
            self._add_path(path)

    def on_directory_tree_directory_selected(
        self,
        event: DirectoryTree.DirectorySelected,
    ) -> None:
        event.stop()
        path = Path(event.path)
        if self._mode.is_save:
            self._selected_paths = (path,)
            self._refresh_selection_state()
        elif self._mode.allows_directories:
            self._add_path(path)

    def on_selection_list_selection_toggled(
        self,
        event: SelectionList.SelectionToggled[int],
    ) -> None:
        if event.selection_list.id != "file-picker-selected":
            return
        event.stop()
        self._remove_selected_at(event.selection_index)

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
        elif button_id == "file-picker-remove":
            self.action_remove_selected()
        else:
            self.dismiss(None)

    def action_remove_selected(self) -> None:
        selected = self.query_one("#file-picker-selected", SelectionList)
        highlighted = selected.highlighted
        if highlighted is None:
            highlighted = len(self._selected_paths) - 1
        self._remove_selected_at(highlighted)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_go_up(self) -> None:
        self._go_up()

    def set_selected_paths(self, paths: Sequence[Path]) -> None:
        """Set selected paths from tests or parent screens."""
        self._selected_paths = tuple(Path(path) for path in paths if str(path))
        if self.is_mounted:
            self._refresh_selection_state()

    def _add_path(self, path: Path) -> None:
        if self._multiple:
            paths = list(self._selected_paths)
            if _find_path_index(paths, path) is None:
                paths.append(path)
            self._selected_paths = tuple(paths)
        else:
            self._selected_paths = (path,)
        self._refresh_selection_state()

    def _remove_selected_at(self, index: int) -> None:
        if index < 0 or index >= len(self._selected_paths):
            return
        paths = list(self._selected_paths)
        del paths[index]
        self._selected_paths = tuple(paths)
        self._refresh_selection_state()

    def _choose(self) -> None:
        if self._mode.is_save:
            name = self.query_one("#file-picker-name", Input).value.strip()
            base = self._selected_paths[0] if self._selected_paths else self._root
            error = _save_target_error(mode=self._mode, base=base, name=name)
            if error is not None:
                self._show_error(error)
                return
            self.dismiss((base / name,) if name else (base,))
            return
        if not self._selected_paths:
            self.notify(self._empty_selection_hint(), severity="warning")
            return
        self.dismiss(self._selected_paths)

    def _use_current_folder(self) -> None:
        tree = self.query_one("#file-picker-tree", DirectoryTree)
        node = tree.cursor_node
        path = Path(getattr(node.data, "path", self._root)) if node is not None else self._root
        folder = path if path.is_dir() else path.parent
        if self._mode == FilePickerMode.OPEN_DIRECTORY:
            self.dismiss((folder,))
            return
        if self._mode.is_save:
            self._selected_paths = (folder,)
            self._refresh_selection_state()
            return
        if self._mode.allows_directories:
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
        self._refresh_selection_state()

    def _refresh_location(self) -> None:
        self.query_one("#file-picker-location", Static).update(_display_path(self._root))
        self.query_one("#file-picker-up", Button).disabled = self._root.parent == self._root

    def _refresh_selected(self) -> None:
        selected = self.query_one("#file-picker-selected", SelectionList)
        selected.set_options(
            [_path_selection(path, index) for index, path in enumerate(self._paths())]
        )
        self.query_one("#file-picker-selected-title", Label).update(self._selection_title())
        remove = self.query_one("#file-picker-remove", Button)
        remove.display = not self._mode.is_save and bool(self._selected_paths)

    def _refresh_selection_state(self) -> None:
        self._refresh_selected()
        self._refresh_choose_state()
        self._sync_responsive_layout(self.size)
        if self._mode.is_save:
            self._refresh_save_validation(show_message=True)

    def _sync_responsive_layout(self, size: Size) -> None:
        modal = self.query_one("#file-picker-modal", Vertical)
        compact = size.width < 88 or size.height < 28
        modal.set_class(compact, "compact")
        side = self.query_one("#file-picker-side", Vertical)
        side.display = self._mode.is_save or not compact or bool(self._selected_paths)
        if self._mode.allows_directories:
            self.query_one("#file-picker-current", Button).label = Content.from_text(
                self._current_folder_action_label(compact=compact),
                markup=False,
            )

    def _current_folder_action_label(self, *, compact: bool) -> str:
        if self._mode == FilePickerMode.OPEN_DIRECTORY:
            return "Use folder" if compact else "Use current folder"
        if self._mode == FilePickerMode.OPEN_PATHS:
            return "Add folder" if compact else "Add current folder"
        return "Set folder" if compact else "Set save folder"

    def _paths(self) -> tuple[Path, ...]:
        if not self._mode.is_save:
            return self._selected_paths
        return (self._selected_paths[0] if self._selected_paths else self._root,)

    def _selection_title(self) -> str:
        if self._mode.is_save:
            return "Save location"
        if self._mode == FilePickerMode.OPEN_DIRECTORY:
            return "Folder selected" if self._selected_paths else "No folder selected"
        count = len(self._selected_paths)
        return f"{count} selected" if count else "None selected"

    def _name_title(self) -> str:
        if self._mode == FilePickerMode.SAVE_FILE:
            return "File name"
        return "Folder name (optional)"

    def _refresh_save_validation(self, *, show_message: bool) -> None:
        if not self._mode.is_save:
            return
        field = self.query_one("#file-picker-name", Input)
        base = self._selected_paths[0] if self._selected_paths else self._root
        error = _save_target_error(mode=self._mode, base=base, name=field.value.strip())
        self.query_one("#file-picker-choose", Button).disabled = error is not None
        self._show_error(error if show_message else None)

    def _refresh_choose_state(self) -> None:
        if self._mode.is_save:
            return
        has_selection = bool(self._selected_paths)
        self.query_one("#file-picker-choose", Button).disabled = not has_selection
        feedback = self.query_one("#file-picker-error", Static)
        feedback.update("" if has_selection else self._empty_selection_hint())
        feedback.set_class(not has_selection, "selection-hint")

    def _empty_selection_hint(self) -> str:
        if self._mode == FilePickerMode.OPEN_FILES:
            return "Select at least one file."
        if self._mode == FilePickerMode.OPEN_DIRECTORY:
            return "Select a folder."
        return "Select at least one file or folder."

    def _show_error(self, message: str | None) -> None:
        error = self.query_one("#file-picker-error", Static)
        error.update(message or "")
        error.set_class(message is not None, "visible")


def _existing_directory(path: Path) -> Path:
    candidate = _normalized_path(path)
    if candidate.is_dir():
        return candidate
    if candidate.parent.is_dir():
        return candidate.parent
    return Path.cwd().resolve()


def _path_selection(path: Path, index: int) -> Selection[int]:
    normalized = _normalized_path(path)
    display_path = _display_path(normalized)
    name = normalized.name or display_path
    parent = _display_path(normalized.parent)

    text = Text()
    text.append(name, style="bold")
    if parent not in {"", "."} and parent != display_path:
        text.append(f"  {parent}", style="dim")
    return Selection(text, index, True)


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


def _save_target_error(*, mode: FilePickerMode, base: Path, name: str) -> str | None:
    if mode == FilePickerMode.SAVE_FILE and not name:
        return "Enter a file name."
    if name:
        if "\x00" in name:
            return "The name contains an invalid null character."
        name_path = Path(name)
        if name_path.is_absolute() or len(name_path.parts) != 1 or name in {".", ".."}:
            return "Enter only a name. Remove any folder path."

    target = base / name if name else base
    if target.exists():
        if mode == FilePickerMode.SAVE_FILE and target.is_dir():
            return "That name belongs to an existing folder. Enter a file name."
        if mode == FilePickerMode.SAVE_DIRECTORY and not target.is_dir():
            return "That name belongs to an existing file. Enter a folder name."
    return None
