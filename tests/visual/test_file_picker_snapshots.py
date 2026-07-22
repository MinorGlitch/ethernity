"""Visual gates for the production file-picker selection states."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest
from textual.geometry import Region
from textual.pilot import Pilot
from textual.widgets import Button, DirectoryTree, SelectionList, Static

from ethernity.app.screens.file_picker import FilePickerMode, FilePickerScreen
from tests.visual.production_states import (
    PRODUCTION_SNAPSHOT_CASES,
    VISUAL_SECRET,
    ProductionVisualApp,
)
from tests.visual.snapshot_support import assert_svg_snapshot, capture_svg

SNAPSHOT_DIR = Path(__file__).with_name("snapshots")
PROJECT_ROOT = Path(__file__).parents[2]
PICKER_FIXTURE_ROOT = Path(__file__).with_name("picker_fixture")
BACKUP_EMPTY_CASE = next(case for case in PRODUCTION_SNAPSHOT_CASES if case.key == "backup-empty")


@dataclass(frozen=True, slots=True)
class FilePickerSnapshotCase:
    key: str
    terminal_size: tuple[int, int]
    selected_paths: tuple[Path, ...]


FILE_PICKER_CASES = (
    FilePickerSnapshotCase("empty", (80, 24), ()),
    FilePickerSnapshotCase(
        "selected",
        (120, 32),
        (
            PICKER_FIXTURE_ROOT / "documents" / "family-records.txt",
            PICKER_FIXTURE_ROOT / "photos",
        ),
    ),
)


@pytest.mark.parametrize("case", FILE_PICKER_CASES, ids=lambda case: case.key)
def test_file_picker_snapshot(
    case: FilePickerSnapshotCase,
    update_tui_snapshots: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
    width, height = case.terminal_size
    svg = capture_svg(
        lambda: ProductionVisualApp(BACKUP_EMPTY_CASE),
        terminal_size=case.terminal_size,
        title=f"Ethernity - file-picker-{case.key} - {width}x{height}",
        run_before=lambda app, pilot: _open_file_picker(
            cast(ProductionVisualApp, app),
            pilot,
            case,
        ),
    )

    assert VISUAL_SECRET not in svg
    assert_svg_snapshot(
        svg,
        SNAPSHOT_DIR / f"app-file-picker-{case.key}-{width}x{height}.svg",
        update=update_tui_snapshots,
    )


async def _open_file_picker(
    app: ProductionVisualApp,
    pilot: Pilot[object],
    case: FilePickerSnapshotCase,
) -> None:
    screen = FilePickerScreen(
        title="Choose files and folders",
        prompt="Select the material to include in this backup.",
        root=PICKER_FIXTURE_ROOT,
        mode=FilePickerMode.OPEN_PATHS,
        selected_paths=case.selected_paths,
        multiple=True,
        choose_label="Select",
    )
    await app.push_screen(screen)
    await pilot.pause()
    app.screen.refresh(layout=True)
    await pilot.pause()
    _assert_file_picker_geometry(screen, case)


def _assert_file_picker_geometry(
    screen: FilePickerScreen,
    case: FilePickerSnapshotCase,
) -> None:
    width, height = case.terminal_size
    viewport = Region(0, 0, width, height)
    modal = screen.query_one("#file-picker-modal")
    body = screen.query_one("#file-picker-body")
    actions = screen.query_one("#file-picker-actions")
    tree = screen.query_one("#file-picker-tree", DirectoryTree)
    selected = screen.query_one("#file-picker-selected", SelectionList)
    choose = screen.query_one("#file-picker-choose", Button)
    remove = screen.query_one("#file-picker-remove", Button)
    feedback = screen.query_one("#file-picker-error", Static)

    assert _inside(viewport, modal.region)
    assert _inside(modal.region, body.region)
    assert _inside(modal.region, actions.region)
    assert body.region.bottom <= actions.region.y
    assert tree.max_scroll_x == 0
    assert selected.max_scroll_x == 0
    for button in actions.query(Button):
        assert _inside(actions.region, button.region)
        assert len(str(button.label)) <= button.region.width

    if case.selected_paths:
        assert selected.option_count == len(case.selected_paths)
        assert str(screen.query_one("#file-picker-selected-title").content) == "2 selected"
        assert list(screen.query("#file-picker-clear"))
        assert remove.display
        assert not choose.disabled
        assert str(feedback.content) == ""
    else:
        assert selected.option_count == 0
        assert not list(screen.query("#file-picker-clear"))
        assert not remove.display
        assert choose.disabled
        assert str(feedback.content) == "Select at least one file or folder."


def _inside(outer: Region, inner: Region) -> bool:
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and inner.x + inner.width <= outer.x + outer.width
        and inner.y + inner.height <= outer.y + outer.height
    )
