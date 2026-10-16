from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from ethernity.tasks import recovery_check
from ethernity.tasks.recovery_check import GeneratedRecoveryCheckRequest, check_generated_recovery


def test_generated_check_recovers_renamed_frozen_pdfs_and_keeps_sources_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures/v1_0/golden/base64/sharded_embedded"
    snapshot = json.loads((fixture / "snapshot.json").read_text(encoding="utf-8"))
    source_paths = [
        fixture / "backup/qr_document.pdf",
        *sorted((fixture / "backup").glob("shard-*.pdf")),
    ]
    supplied: list[Path] = []
    for index, source in enumerate(source_paths):
        renamed = tmp_path / f"page-{index}.pdf"
        shutil.copyfile(source, renamed)
        supplied.append(renamed)
    original_hashes = [hashlib.sha256(path.read_bytes()).digest() for path in supplied]
    temporary_paths: list[Path] = []

    def temporary_directory(*, prefix: str) -> TemporaryDirectory[str]:
        directory = TemporaryDirectory(prefix=prefix, dir=tmp_path)
        temporary_paths.append(Path(directory.name))
        return directory

    monkeypatch.setattr(recovery_check, "TemporaryDirectory", temporary_directory)
    result = check_generated_recovery(GeneratedRecoveryCheckRequest(documents=tuple(supplied)))

    assert result.file_count == len(snapshot["manifest_projection"]["files"])
    assert result.total_bytes == sum(
        entry["size"] for entry in snapshot["manifest_projection"]["files"]
    )
    assert result.recovery_sheet_count == 2
    assert [hashlib.sha256(path.read_bytes()).digest() for path in supplied] == original_hashes
    assert temporary_paths
    assert all(not path.exists() for path in temporary_paths)
    assert set(tmp_path.iterdir()) == set(supplied)
