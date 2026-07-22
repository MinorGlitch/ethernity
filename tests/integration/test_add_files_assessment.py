from __future__ import annotations

import shutil
from pathlib import Path

from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.tasks.add_files import AddFilesTaskState

_FIXTURE = Path("tests/fixtures/v1_2/extension_golden/raw/extension_local_sharded_chain")
_LOOSE_FIXTURE = Path("tests/fixtures/v1_2/extension_golden/raw/loose_scan_append_chain")


def test_add_files_assessment_rejects_pre_policy_chain_without_required_recovery_kit(
    tmp_path: Path,
) -> None:
    backup_root = tmp_path / "chain"
    shutil.copytree(_FIXTURE / "chain", backup_root)
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "alpha.txt").write_bytes(b"extension local alpha\n")
    (input_root / "beta.txt").write_bytes(b"extension local beta\n")
    (input_root / "gamma.txt").write_bytes(b"new after review\n")
    state = AddFilesTaskState(
        config_path=DEFAULT_CONFIG_PATH,
        backup_folder=backup_root,
        input_dirs=[input_root],
        base_dir=input_root,
        passphrase="stable-v1_2-extension-passphrase",
        unlock_policy="self-contained",
        recovery_document_threshold=2,
        recovery_document_count=3,
        signing_key_mode="not-stored",
    )

    state.prepare_review(force=True)

    validation = state.validate_task()

    assert not validation.ready
    assert any(
        "missing required MAIN documents: recovery_kit" in issue.message
        for issue in validation.issues
    )
    assert sorted(path.name for path in (backup_root / "extensions").iterdir()) == ["01"]


def test_scan_assessment_keeps_source_carriers_separate_from_loose_output(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "alpha.txt").write_bytes(b"second loose extension alpha\n")
    (input_root / "beta.txt").write_bytes(b"second loose extension beta\n")
    output_root = tmp_path / "loose-update"
    scans = _LOOSE_FIXTURE / "loose_scans"
    state = AddFilesTaskState(
        config_path=DEFAULT_CONFIG_PATH,
        source_paths=[
            scans / "phone-root-carrier.pdf",
            scans / "wallet-extension-one.pdf",
        ],
        loose_output_folder=output_root,
        input_dirs=[input_root],
        base_dir=input_root,
        passphrase="stable-v1_2-extension-passphrase",
        expected_head_doc_hash=("a0571284dae33611b3b9ac177c896b4555ac31e53908474cbb4a07b98c84fc75"),
        unlock_policy="self-contained",
        recovery_document_threshold=2,
        recovery_document_count=3,
        signing_key_mode="not-stored",
    )

    state.prepare_review(force=True)

    assert state.validate_task().ready
    plan = state.execution_plan()
    assert len(plan.output_paths) == 1
    assert plan.output_paths[0].parent == output_root
    assert plan.output_paths[0].name.startswith("extension-02-")
    assert not output_root.exists()

    result = state.execute()

    details = {detail.key: detail.value for detail in result.details}
    assert details["publish_layout"] == "loose"
    assert details["parent_head_doc_hash"] == (
        "a0571284dae33611b3b9ac177c896b4555ac31e53908474cbb4a07b98c84fc75"
    )
    assert any("every earlier update" in step for step in result.next_steps)
    assert sorted(path.name for path in output_root.iterdir()) == [
        ".chain.lock",
        plan.output_paths[0].name,
    ]
