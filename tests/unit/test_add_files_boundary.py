from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from ethernity.app.application import EthernityApp
from ethernity.app.execution import ExecutionContext
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.run.cli import cli
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.models import TaskExecutionResult, TaskResultDetail
from ethernity.workflows.extension.errors import ExtensionIssue
from ethernity.workflows.extension.models import SigningKeyNotStored
from ethernity.workflows.extension.service import (
    AssessedExtendRun,
    ExtensionAssessment,
    ExtensionExecutionResult,
    ExtensionPassphraseShards,
)


def _valid_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_bytes(DEFAULT_CONFIG_PATH.read_bytes())
    return path


def _fake_assessed(marker: bytes = b"A") -> AssessedExtendRun:
    stats = SimpleNamespace(
        changed_file_count=2,
        logical_bytes=12,
        new_chunks=1,
        reused_chunks=2,
    )
    prepared = SimpleNamespace(
        args=SimpleNamespace(base_directory=None),
        next_index=3,
        changed_paths=("changed.txt",),
        new_paths=("new.txt",),
        unchanged_paths=("same.txt",),
        parent_doc_hash=b"P" * 32,
    )
    encrypted = SimpleNamespace(
        built=SimpleNamespace(stats=stats),
        plaintext=b"plaintext-" + marker,
        ciphertext=b"ciphertext-" + marker,
        doc_id=b"D" * 8,
        doc_hash=marker * 32,
    )
    runtime = SimpleNamespace(
        passphrase=ExtensionPassphraseShards(threshold=2, share_count=3),
        signing_key=SigningKeyNotStored(),
        config=SimpleNamespace(paper_size="A4", design_name="sentinel"),
        qr_chunk_size=512,
    )
    return AssessedExtendRun(prepared=prepared, encrypted=encrypted, runtime=runtime)


def _fake_executed(assessed: AssessedExtendRun, output_root: Path) -> SimpleNamespace:
    result = SimpleNamespace(
        index=assessed.prepared.next_index,
        doc_id=assessed.encrypted.doc_id,
        doc_hash=assessed.encrypted.doc_hash,
        qr_document_path=output_root / "qr.pdf",
        recovery_document_path=output_root / "recovery.pdf",
        recovery_kit_path=output_root / "recovery-kit.pdf",
        recovery_kit_index_path=None,
        shard_paths=(),
        signing_key_shard_paths=(),
        parent_head_index=2,
        publish_root=output_root,
        final_dir=output_root / "extensions" / "03",
    )
    return SimpleNamespace(
        prepared=assessed.prepared,
        publish=SimpleNamespace(
            encrypted=assessed.encrypted,
            artifacts=SimpleNamespace(publish_layout="canonical"),
        ),
        result=result,
    )


def test_scan_source_has_a_distinct_loose_output_contract(tmp_path: Path) -> None:
    state = AddFilesTaskState(
        source_paths=[Path("root-scan.pdf")],
        loose_output_folder=tmp_path / "new-update",
        input_paths=[Path("new.txt")],
        passphrase="secret",
        allow_stale_head=True,
    )

    assert state.validate_task().ready
    assert state.to_extension_request().publish_root == str(tmp_path / "new-update")
    assert state.to_extension_request().scan_paths == ("root-scan.pdf",)
    assert "Separate update:" in state.sections()[4].summary

    missing_output = state.model_copy(update={"loose_output_folder": None})
    conflict = state.model_copy(update={"backup_folder": Path("published")})
    assert "ADD_FILES_OUTPUT_REQUIRED" in {
        issue.code for issue in missing_output.validate_task().issues
    }
    assert "ADD_FILES_SOURCE_CONFLICT" in {issue.code for issue in conflict.validate_task().issues}


def test_run_add_files_maps_scan_source_and_output_to_distinct_fields(monkeypatch) -> None:
    captured: list[AddFilesTaskState] = []

    def capture_task(_task, state, **_kwargs):
        captured.append(state)

    monkeypatch.setattr("ethernity.run.commands.add_files.run_task", capture_task)
    result = CliRunner().invoke(
        cli,
        [
            "add-files",
            "--scan",
            "root.pdf",
            "--output-folder",
            "loose-update",
            "--input",
            "new.txt",
            "--passphrase",
            "secret",
            "--allow-stale-head",
            "--preview",
        ],
    )

    assert result.exit_code == 0
    assert len(captured) == 1
    assert captured[0].backup_folder is None
    assert captured[0].source_paths == [Path("root.pdf")]
    assert captured[0].loose_output_folder == Path("loose-update")
    assert captured[0].to_extension_request().publish_root == "loose-update"


def test_zero_recovery_count_requires_reuse_root_policy() -> None:
    self_contained = AddFilesTaskState(
        unlock_policy="self-contained",
        recovery_document_count=0,
    )
    reuse_root = AddFilesTaskState(
        unlock_policy="reuse-root",
        recovery_document_count=0,
    )

    assert "ADD_FILES_ZERO_RECOVERY_REQUIRES_REUSE_ROOT" in {
        issue.code for issue in self_contained.validate_task().issues
    }
    assert "ADD_FILES_ZERO_RECOVERY_REQUIRES_REUSE_ROOT" not in {
        issue.code for issue in reuse_root.validate_task().issues
    }


def test_task_facade_uses_saved_extend_defaults_without_hardcoded_overrides(
    tmp_path: Path,
) -> None:
    config_path = _valid_config(tmp_path)
    config_text = config_path.read_text(encoding="utf-8")
    extend_start = config_text.index("[defaults.extend]")
    recover_start = config_text.index("[defaults.recover]")
    extend = config_text[extend_start:recover_start]
    extend = extend.replace('base_dir = ""', f"base_dir = {json.dumps(str(tmp_path))}", 1)
    extend = extend.replace('unlock_policy = ""', 'unlock_policy = "reuse-root"', 1)
    config_path.write_text(
        config_text[:extend_start] + extend + config_text[recover_start:],
        encoding="utf-8",
    )

    state = AddFilesTaskState(
        config_path=config_path,
        backup_folder=Path("published"),
        input_paths=[Path("new.txt")],
        passphrase="secret",
    )
    request = state.to_extension_request()

    assert request.base_directory == str(tmp_path)
    assert request.unlock_policy is None
    assert request.paper_size is None
    assert request.design is None


def test_review_assessment_is_shared_and_exact_payload_is_executed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _valid_config(tmp_path)
    assessed = _fake_assessed()
    assessment_calls: list[object] = []
    execution_calls: list[object] = []

    def fake_assess(request):
        assessment_calls.append(request)
        return ExtensionAssessment(request=request, assessed=assessed)

    def fake_execute(assessment, **_kwargs):
        execution_calls.append(assessment.assessed)
        return ExtensionExecutionResult(
            assessment=assessment,
            executed=_fake_executed(assessment.assessed, tmp_path / "published"),
        )

    monkeypatch.setattr("ethernity.tasks.add_files.assess_extension", fake_assess)
    monkeypatch.setattr("ethernity.tasks.add_files.execute_extension", fake_execute)

    state = AddFilesTaskState(
        config_path=config_path,
        backup_folder=tmp_path / "published",
        input_paths=[tmp_path / "new.txt"],
        passphrase="secret",
    )
    state.prepare_review(force=True)

    assert state.validate_task().ready
    assert "03" in state.execution_plan().summary
    assert any(item.label == "New fingerprint" for item in state.preview().items)
    result = state.execute()

    assert len(assessment_calls) == 1
    assert execution_calls == [assessed]
    assert result.output_paths[2].name == "recovery-kit.pdf"
    assert "Replace and test the previous recovery kit." in result.next_steps
    assert (
        next(detail for detail in result.details if detail.key == "doc_hash").value
        == (b"A" * 32).hex()
    )


def test_failed_assessment_blocks_review_without_replanning(monkeypatch) -> None:
    calls = 0

    def reject(request):
        nonlocal calls
        calls += 1
        return ExtensionAssessment(
            request=request,
            issues=(ExtensionIssue(code="EXTENSION_NO_CHANGES", message="nothing to extend"),),
        )

    monkeypatch.setattr("ethernity.tasks.add_files.assess_extension", reject)
    state = AddFilesTaskState(
        backup_folder=Path("published"),
        input_paths=[Path("same.txt")],
        passphrase="secret",
    )

    state.prepare_review(force=True)
    validation = state.validate_task()
    state.preview()
    state.execution_plan()

    assert not validation.ready
    assert validation.issues[0].code == "EXTENSION_NO_CHANGES"
    assert validation.issues[0].section == "files"
    assert calls == 1


def test_execution_context_reuses_reviewed_assessment_and_ignores_later_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _valid_config(tmp_path)
    assessed = _fake_assessed(b"R")
    assessment_count = 0
    executed_hashes: list[bytes] = []
    executed_assessments: list[AssessedExtendRun] = []
    execution_config_payloads: list[bytes] = []
    reviewed_config_payload = config_path.read_bytes()

    def fake_assess(request):
        nonlocal assessment_count
        assessment_count += 1
        return ExtensionAssessment(request=request, assessed=assessed)

    monkeypatch.setattr("ethernity.tasks.add_files.assess_extension", fake_assess)

    def fake_execute(assessment, *, config_path=None, **_kwargs):
        value = assessment.assessed
        executed_assessments.append(value)
        executed_hashes.append(value.encrypted.doc_hash)
        assert config_path is not None
        execution_config_payloads.append(Path(config_path).read_bytes())
        return ExtensionExecutionResult(
            assessment=assessment,
            executed=_fake_executed(value, tmp_path / "published"),
        )

    monkeypatch.setattr("ethernity.tasks.add_files.execute_extension", fake_execute)

    state = AddFilesTaskState(
        config_path=config_path,
        backup_folder=tmp_path / "published",
        input_paths=[tmp_path / "reviewed.txt"],
        passphrase="secret",
    )
    state.prepare_review(force=True)
    context = ExecutionContext.capture("add_files", state)

    state.input_paths = [tmp_path / "later.txt"]
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + "\n# changed after review\n",
        encoding="utf-8",
    )
    result = context.execute()

    assert result.ok
    assert assessment_count == 1
    assert executed_assessments[0] is assessed
    assert executed_hashes == [b"R" * 32]
    assert execution_config_payloads == [reviewed_config_payload]
    assert context.state_snapshot.input_paths == [tmp_path / "reviewed.txt"]


def test_run_task_and_textual_review_prime_add_files_assessment(monkeypatch) -> None:
    run_calls: list[bool] = []

    def record_run_review(_self, *, force=False):
        run_calls.append(force)

    monkeypatch.setattr(AddFilesTaskState, "prepare_review", record_run_review)
    result = CliRunner().invoke(
        cli,
        [
            "add-files",
            "--backup-folder",
            "published",
            "--input",
            "new.txt",
            "--passphrase",
            "secret",
            "--preview",
        ],
    )
    assert result.exit_code == 0
    assert run_calls == [True]

    tui_calls: list[bool] = []

    def record_tui_review(_self, *, force=False):
        tui_calls.append(force)

    monkeypatch.setattr(AddFilesTaskState, "prepare_review", record_tui_review)

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("3")
            await app.action_review()
            await pilot.pause()

    asyncio.run(run())
    assert tui_calls == [True]


def test_run_add_files_blocks_execution_when_assessment_fails(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "add-files",
            "--backup-folder",
            str(tmp_path / "missing-backup"),
            "--input",
            str(tmp_path / "missing-input"),
            "--passphrase",
            "secret",
            "--yes",
        ],
    )

    assert result.exit_code == 1
    assert "root backup directory not found" in result.output


def test_add_files_result_metadata_reaches_json_and_text_surfaces(monkeypatch) -> None:
    result = TaskExecutionResult(
        ok=True,
        message="Added files as backup update 03.",
        output_paths=(Path("published/extensions/03/qr.pdf"),),
        details=(
            TaskResultDetail(
                key="doc_hash",
                label="New full fingerprint",
                value="ab" * 32,
            ),
            TaskResultDetail(key="new_chunks", label="New chunks", value=4),
        ),
        next_steps=("Keep the original backup and every earlier update.",),
    )
    monkeypatch.setattr(
        AddFilesTaskState,
        "prepare_review",
        lambda _self, *, force=False: None,
    )
    monkeypatch.setattr(AddFilesTaskState, "execute", lambda _self: result)
    args = [
        "add-files",
        "--backup-folder",
        "published",
        "--input",
        "new.txt",
        "--passphrase",
        "secret",
        "--yes",
    ]

    json_result = CliRunner().invoke(cli, [*args, "--json"])
    text_result = CliRunner().invoke(cli, args)

    assert json_result.exit_code == 0
    payload = json.loads(json_result.output)
    assert payload["result"]["details"][0] == {
        "key": "doc_hash",
        "label": "New full fingerprint",
        "value": "ab" * 32,
    }
    assert payload["result"]["next_steps"] == ["Keep the original backup and every earlier update."]
    assert text_result.exit_code == 0
    assert "New full fingerprint" in text_result.output
    assert "Keep the original backup and every earlier update." in text_result.output
