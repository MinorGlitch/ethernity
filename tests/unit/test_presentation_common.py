from __future__ import annotations

from pathlib import Path

from ethernity.tasks.presentation.common import middle_truncate_path


def test_middle_truncate_path_preserves_parent_and_filename_when_possible() -> None:
    rendered = middle_truncate_path(
        Path("/var/tmp/Documents/projects/ethernity/config.toml"),
        max_chars=40,
    )

    assert rendered == str(Path("/var/.../ethernity/config.toml"))
    assert len(rendered) <= 40


def test_middle_truncate_path_respects_small_widths() -> None:
    rendered = middle_truncate_path("abcdefghijklmnopqrstuvwxyz", max_chars=8)

    assert rendered == "ab...xyz"
    assert len(rendered) == 8
    assert middle_truncate_path("abcdefghijklmnopqrstuvwxyz", max_chars=0) == ""
    assert middle_truncate_path("abcdefghijklmnopqrstuvwxyz", max_chars=2) == ".."
