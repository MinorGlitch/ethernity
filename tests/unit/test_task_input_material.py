from pathlib import Path

from ethernity.tasks.input_material import has_selected_inputs


def test_has_selected_inputs_accepts_files_or_directories() -> None:
    assert not has_selected_inputs([], [])
    assert has_selected_inputs([Path("file.txt")], [])
    assert has_selected_inputs([], [Path("folder")])
