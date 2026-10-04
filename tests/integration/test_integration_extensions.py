# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pypdf import PdfReader

from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.encoding.framing import encode_frame
from ethernity.encoding.qr_payloads import encode_qr_payload
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.workflows.add_files.request import AddFilesRequest
from ethernity.workflows.add_files.service import assess_add_files, execute_add_files
from ethernity.workflows.backup.service import execute_prepared_backup, prepare_backup_run
from ethernity.workflows.recovery.service import execute_recover_plan, prepare_recover_plan
from ethernity.workflows.shared.operation_types import (
    BackupArgs,
    RecoverArgs,
)
from tests.test_support import suppress_output, temp_env

TEST_PASSPHRASE = "extension-integration-passphrase"


def test_renamed_scans_can_be_extended_directly_and_combined_with_text_inputs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    original = tmp_path / "original"
    scans = tmp_path / "scans"
    first_output = tmp_path / "independent-first-update"
    second_output = tmp_path / "unrelated-second-update"
    recovered = tmp_path / "recovered"
    debug = tmp_path / "layout-debug"
    source.mkdir()
    scans.mkdir()
    (source / "alpha.txt").write_text("root-alpha", encoding="utf-8")

    with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
        _run_backup(source, original)
        root_snapshot = _snapshot_tree(original)
        renamed_root = scans / "camera-page.pdf"
        shutil.copy2(original / "qr_document.pdf", renamed_root)
        (source / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
        (source / "beta.txt").write_text("extension-beta", encoding="utf-8")
        first = _run_add_files(
            source,
            first_output,
            scan=[renamed_root],
            layout_debug_dir=debug,
        )

        assert {path.name for path in first.final_dir.iterdir()} == {
            f"qr_document-01-{first.doc_id.hex()}.pdf",
            f"recovery_document-01-{first.doc_id.hex()}.pdf",
        }
        assert len(PdfReader(first.recovery_document_path).pages) >= 1
        _assert_layout_debug(debug)
        assert first.final_dir == first_output
        assert _snapshot_tree(original) == root_snapshot
        assert not (original / "extensions").exists()

        first_snapshot = _snapshot_tree(first_output)
        first_text = tmp_path / "pasted-update.txt"
        first_text.write_text(
            "\n".join(
                str(encode_qr_payload(encode_frame(frame)))
                for frame in reversed(first.recovery_frames)
            )
            + "\n",
            encoding="ascii",
        )
        moved_root = tmp_path / "relocated" / "arbitrary-name.pdf"
        moved_root.parent.mkdir()
        renamed_root.rename(moved_root)

        (source / "later.txt").write_text("direct second update", encoding="utf-8")
        appended = _run_add_files(
            source,
            second_output,
            scan=[moved_root],
            payloads_file=first_text,
            expected_head_doc_hash=first.doc_hash.hex(),
        )
        loose_first = scans / "z.pdf"
        loose_second = scans / "a.pdf"
        shutil.copy2(first.qr_document_path, loose_first)
        shutil.copy2(appended.qr_document_path, loose_second)
        _run_recover(
            [loose_second, moved_root, loose_first],
            recovered,
            expected_head_doc_hash=appended.doc_hash.hex(),
        )
        assert _snapshot_tree(original) == root_snapshot
        assert _snapshot_tree(first_output) == first_snapshot

    assert appended.index == 2
    assert appended.parent_head_doc_hash == first.doc_hash.hex()
    assert _snapshot_tree(recovered) == {
        "alpha.txt": b"extension-alpha",
        "beta.txt": b"extension-beta",
        "later.txt": b"direct second update",
    }


def test_add_files_replacement_sheets_recover_root_after_update_is_lost(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    root = tmp_path / "backup"
    update_output = tmp_path / "update"
    recovered = tmp_path / "recovered"
    recovered_root = tmp_path / "recovered-root"
    source.mkdir()
    (source / "alpha.txt").write_text("root-alpha", encoding="utf-8")

    with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
        _run_backup(source, root, shard_threshold=2, shard_count=3)
        root_shards = sorted(root.glob("shard-*.pdf"))
        assert len(root_shards) == 3

        (source / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
        state = AddFilesTaskState(
            config_path=DEFAULT_CONFIG_PATH,
            source_paths=[root / "qr_document.pdf"],
            output_dir=update_output,
            allow_stale_head=True,
            input_dirs=[source],
            base_dir=source,
            recovery_documents=root_shards[:2],
            design="sentinel",
            create_recovery_sheets=True,
            recovery_threshold=2,
            recovery_sheet_count=3,
        )
        with suppress_output():
            state.prepare_review(force=True)
            update = state.execute()

        extension_dir = update_output
        extension_names = {path.name for path in extension_dir.iterdir()}
        assert len(extension_names) == 2
        assert not any(
            name.startswith(("shard-", "signing-key-shard-")) for name in extension_names
        )
        replacement_sheets = list(update.recovery_check_paths[1:])
        assert len(replacement_sheets) == 3
        assert all(
            path.parent.parent == tmp_path / "update-recovery-sheets" for path in replacement_sheets
        )
        _run_recover(
            [root / "qr_document.pdf", extension_dir],
            recovered,
            passphrase=None,
            shard_scan=replacement_sheets[:2],
        )
        shutil.rmtree(update_output)
        _run_recover(
            [root / "qr_document.pdf"],
            recovered_root,
            passphrase=None,
            shard_scan=replacement_sheets[:2],
        )
        (source / "later.txt").write_text("after lost update", encoding="utf-8")
        continued = _run_add_files(
            source,
            tmp_path / "continued-update",
            scan=[root / "qr_document.pdf"],
            passphrase=None,
            shard_scan=replacement_sheets[:2],
        )

    assert update.ok
    assert next(detail.value for detail in update.details if detail.key == "index") == 1
    assert "3 created; 2 needed" in str(
        next(detail.value for detail in update.details if detail.key == "recovery_sheets")
    )
    assert _snapshot_tree(recovered) == {"alpha.txt": b"extension-alpha"}
    assert _snapshot_tree(recovered_root) == {"alpha.txt": b"root-alpha"}
    assert continued.index == 1


def _run_backup(
    source: Path,
    root: Path,
    *,
    shard_threshold: int | None = None,
    shard_count: int | None = None,
) -> None:
    with suppress_output():
        result = execute_prepared_backup(
            prepare_backup_run(
                BackupArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    input_dir=[str(source)],
                    base_dir=str(source),
                    output_dir=str(root),
                    passphrase=TEST_PASSPHRASE,
                    design="sentinel",
                    shard_threshold=shard_threshold,
                    shard_count=shard_count,
                    quiet=True,
                )
            )
        )
    assert Path(result.qr_path).is_file()
    assert Path(result.recovery_path).is_file()


def _run_add_files(
    source: Path,
    output: Path,
    *,
    scan: list[Path],
    payloads_file: Path | None = None,
    expected_head_doc_hash: str | None = None,
    passphrase: str | None = TEST_PASSPHRASE,
    shard_scan: list[Path] | None = None,
    layout_debug_dir: Path | None = None,
):
    with suppress_output():
        assessment = assess_add_files(
            AddFilesRequest(
                config_path=str(DEFAULT_CONFIG_PATH),
                scan_paths=tuple(str(path) for path in scan),
                payloads_file=str(payloads_file) if payloads_file is not None else None,
                output_dir=str(output),
                expected_head_doc_hash=expected_head_doc_hash,
                allow_stale_head=expected_head_doc_hash is None,
                input_directories=(str(source),),
                base_directory=str(source),
                passphrase=passphrase,
                shard_scan_paths=tuple(str(path) for path in shard_scan or ()),
                layout_debug_directory=(
                    str(layout_debug_dir) if layout_debug_dir is not None else None
                ),
                design="sentinel",
                quiet=True,
            )
        )
        assert assessment.ready, assessment.issues
        result = execute_add_files(assessment)
    assert result.ok and result.executed is not None, result.issues
    return result.executed.result


def _run_recover(
    scan: list[Path],
    output: Path,
    *,
    passphrase: str | None = TEST_PASSPHRASE,
    shard_scan: list[Path] | None = None,
    expected_head_doc_hash: str | None = None,
) -> None:
    with suppress_output():
        args = RecoverArgs(
            config=str(DEFAULT_CONFIG_PATH),
            scan=[str(path) for path in scan],
            expected_head_doc_hash=expected_head_doc_hash,
            passphrase=passphrase,
            shard_scan=[str(path) for path in shard_scan or ()] or None,
            output=str(output),
            assume_yes=True,
            quiet=True,
        )
        execute_recover_plan(prepare_recover_plan(args), quiet=True)


def _assert_layout_debug(debug: Path) -> None:
    for filename, doc_type in {
        "qr_document.layout.json": "main",
        "recovery_document.layout.json": "recovery",
    }.items():
        payload = json.loads((debug / filename).read_text(encoding="utf-8"))
        assert payload["doc_type"] == doc_type
        assert payload["pages"]


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
