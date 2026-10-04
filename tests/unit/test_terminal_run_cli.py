from __future__ import annotations

import json
import tomllib
from pathlib import Path

from click.testing import CliRunner

import ethernity.main as root_entrypoint
from ethernity.main import main
from ethernity.run.cli import cli
from ethernity.tasks.models import TaskExecutionResult


def test_runtime_dependencies_exclude_old_prompt_stack() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    runtime_dependencies = tuple(
        dependency.partition(">=")[0].partition("==")[0].lower()
        for dependency in pyproject["project"]["dependencies"]
    )
    dev_dependencies = tuple(
        dependency.partition(">=")[0].partition("==")[0].lower()
        for dependency in pyproject["project"]["optional-dependencies"]["dev"]
    )

    assert "typer" not in runtime_dependencies
    assert "questionary" not in runtime_dependencies
    assert "prompt-toolkit" not in runtime_dependencies
    assert "typer" not in dev_dependencies
    assert "questionary" not in dev_dependencies
    assert "prompt-toolkit" not in dev_dependencies


def test_legacy_cli_source_package_is_removed() -> None:
    assert not any(Path("src/ethernity/cli").rglob("*.py"))


def test_root_help_points_to_new_terminal_app_and_runner(capsys) -> None:
    result = main(["--help"])

    captured = capsys.readouterr()
    assert result == 0
    assert "Launch the Ethernity terminal app" in captured.out
    assert "ethernity run backup" in captured.out


def test_root_version_prints_package_version(capsys, monkeypatch) -> None:
    monkeypatch.setattr(root_entrypoint, "get_ethernity_version", lambda: "9.8.7")

    result = main(["--version"])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "ethernity 9.8.7\n"


def test_root_rejects_old_top_level_commands(capsys) -> None:
    result = main(["backup"])

    captured = capsys.readouterr()
    assert result == 2
    assert "unknown command 'backup'" in captured.err


def test_run_backup_preview_uses_task_model() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "backup",
            "--input",
            "secrets.txt",
            "--output-dir",
            "backup-out",
            "--preview",
        ],
    )

    assert result.exit_code == 0
    assert "Files" in result.output
    assert "Documents to create" in result.output
    assert "3 recovery sheets" in result.output
    assert "Nothing will be written until final review." not in result.output


def test_run_backup_json_preview_uses_task_model() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "backup",
            "--input",
            "secrets.txt",
            "--output-dir",
            "backup-out",
            "--preview",
            "--json",
        ],
    )

    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["task"] == "backup"
    assert payload["status"] == "preview"
    assert payload["ready"] is True
    assert payload["preview"]["title"] == "Documents to create"
    assert payload["plan"]["output_paths"] == ["backup-out"]
    assert payload["result"] is None
    assert payload["error"] is None


def test_run_backup_json_preview_uses_automatic_output_folder_when_unset() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "backup",
            "--input",
            "secrets.txt",
            "--preview",
            "--json",
        ],
    )

    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["ready"] is True
    assert payload["validation"]["issues"] == []
    assert payload["plan"]["summary"] == (
        "Create backup documents in an automatic folder named for the backup ID"
    )
    assert payload["plan"]["output_paths"] == ["backup-<backup id>"]


def test_run_backup_requires_ready_state_without_preview() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["backup", "--yes"])

    assert result.exit_code != 0
    assert "Backup is not ready" in result.output


def test_run_backup_json_not_ready_is_machine_readable() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["backup", "--yes", "--json"])

    payload = json.loads(result.output)
    assert result.exit_code == 1
    assert payload["status"] == "not_ready"
    assert payload["ready"] is False
    assert payload["error"] == "Backup is not ready."
    assert [issue["code"] for issue in payload["validation"]["issues"]] == [
        "BACKUP_FILES_REQUIRED",
    ]


def test_run_shard_count_options_reject_values_above_shamir_limit() -> None:
    runner = CliRunner()
    cases = (
        ["backup", "--recovery-count", "256"],
        ["add-files", "--recovery-count", "256"],
        ["replace-recovery-docs", "--recovery-count", "256"],
    )

    for args in cases:
        result = runner.invoke(cli, args)

        assert result.exit_code == 2
        assert "255" in result.output


def test_run_backup_yes_executes_task_model(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(status="succeeded", message="Backup documents created.")

    monkeypatch.setattr("ethernity.tasks.backup.BackupTaskState.execute", fake_execute)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "backup",
            "--input",
            "secrets.txt",
            "--output-dir",
            "backup-out",
            "--qr-chunk-size",
            "384",
            "--passphrase-words",
            "18",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0].input_paths
    assert calls[0].qr_chunk_size == 384
    assert calls[0].passphrase_words == 18
    assert calls[0].to_backup_request().qr_chunk_size == 384
    assert calls[0].to_backup_request().passphrase_words == 18
    assert "Backup documents created." in result.output


def test_run_backup_yes_uses_automatic_output_folder_when_unset(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(status="succeeded", message="Backup documents created.")

    monkeypatch.setattr("ethernity.tasks.backup.BackupTaskState.execute", fake_execute)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "backup",
            "--input",
            "secrets.txt",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0].output_dir is None
    assert calls[0].to_backup_request().output_dir is None
    assert "Backup documents created." in result.output


def test_run_backup_zero_recovery_count_disables_passphrase_shards(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(status="succeeded", message="Backup documents created.")

    monkeypatch.setattr("ethernity.tasks.backup.BackupTaskState.execute", fake_execute)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "backup",
            "--input",
            "secrets.txt",
            "--recovery-count",
            "0",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0].recovery_method == "single_phrase"
    assert calls[0].shard_count == 0
    assert calls[0].to_backup_request().shard_threshold is None
    assert calls[0].to_backup_request().shard_count is None


def test_run_backup_json_yes_executes_task_model(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Backup documents created.",
            output_paths=(Path("backup-out/main.pdf"),),
        )

    monkeypatch.setattr("ethernity.tasks.backup.BackupTaskState.execute", fake_execute)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "backup",
            "--input",
            "secrets.txt",
            "--output-dir",
            "backup-out",
            "--yes",
            "--json",
        ],
    )

    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert len(calls) == 1
    assert payload["status"] == "executed"
    assert payload["result"]["message"] == "Backup documents created."
    assert payload["result"]["output_paths"] == [str(Path("backup-out/main.pdf"))]


def test_run_restore_preview_uses_task_model() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "restore",
            "--scan",
            "scans",
            "--auth-text",
            "auth.txt",
            "--passphrase",
            "secret",
            "--output",
            "recovered",
            "--preview",
        ],
    )

    assert result.exit_code == 0
    assert "Backup source" in result.output
    assert "Files to restore" in result.output


def test_run_restore_yes_executes_task_model(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(status="succeeded", message="Recovered files written.")

    monkeypatch.setattr("ethernity.tasks.restore.RestoreTaskState.execute", fake_execute)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "restore",
            "--scan",
            "scans",
            "--auth-text",
            "auth.txt",
            "--passphrase",
            "secret",
            "--output",
            "recovered",
            "--resource-intensive-compatibility-recovery",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0].source_paths
    assert calls[0].auth_text_file == Path("auth.txt")
    assert calls[0].to_recovery_request().auth_text_file == Path("auth.txt")
    assert calls[0].passphrase == "secret"
    assert calls[0].resource_intensive_compatibility_recovery
    assert calls[0].to_recovery_request().resource_intensive_compatibility_recovery
    assert "Recovered files written." in result.output


def test_run_add_files_preview_uses_task_model(monkeypatch) -> None:
    monkeypatch.setattr(
        "ethernity.tasks.add_files.AddFilesTaskState.prepare_review",
        lambda _self, *, force=False: None,
    )
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "add-files",
            "--scan",
            "backup-out",
            "--output-dir",
            "update-out",
            "--allow-stale-head",
            "--input",
            "new-file.txt",
            "--passphrase",
            "secret",
            "--preview",
        ],
    )

    assert result.exit_code == 0
    assert "Files to add" in result.output
    assert "Backup update to create" in result.output


def test_run_add_files_yes_executes_task_model(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(status="succeeded", message="Added files as backup update 01.")

    monkeypatch.setattr("ethernity.tasks.add_files.AddFilesTaskState.execute", fake_execute)
    monkeypatch.setattr(
        "ethernity.tasks.add_files.AddFilesTaskState.prepare_review",
        lambda _self, *, force=False: None,
    )
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "add-files",
            "--scan",
            "backup-out",
            "--output-dir",
            "update-out",
            "--allow-stale-head",
            "--input",
            "new-file.txt",
            "--passphrase",
            "secret",
            "--qr-chunk-size",
            "384",
            "--new-recovery-sheets",
            "--auth-text",
            "signature.txt",
            "--recovery-threshold",
            "3",
            "--recovery-count",
            "5",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0].source_paths == [Path("backup-out")]
    assert calls[0].output_dir == Path("update-out")
    assert calls[0].allow_stale_head
    assert calls[0].auth_text_file == Path("signature.txt")
    assert calls[0].qr_chunk_size == 384
    assert calls[0].to_add_files_request().qr_chunk_size == 384
    assert calls[0].create_recovery_sheets
    assert calls[0].recovery_threshold == 3
    assert calls[0].recovery_sheet_count == 5
    assert "Added files as backup update 01." in result.output


def test_run_add_files_rejects_removed_backup_folder_option() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["add-files", "--backup-folder", "backup-out"])

    assert result.exit_code == 2
    assert "No such option '--backup-folder'" in result.output


def test_run_add_files_preserves_mixed_document_sources(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(status="succeeded", message="Update written.")

    monkeypatch.setattr("ethernity.tasks.add_files.AddFilesTaskState.execute", fake_execute)
    monkeypatch.setattr(
        "ethernity.tasks.add_files.AddFilesTaskState.prepare_review",
        lambda _self, *, force=False: None,
    )

    result = CliRunner().invoke(
        cli,
        [
            "add-files",
            "--scan",
            "renamed-root.pdf",
            "--scan",
            "scanned-update.png",
            "--recovery-text",
            "transcribed.txt",
            "--payloads-file",
            "payloads.txt",
            "--input",
            "new-file.txt",
            "--passphrase",
            "secret",
            "--output-dir",
            "update-out",
            "--expected-head",
            "ab" * 32,
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    request = calls[0].to_add_files_request()
    assert request.scan_paths == ("renamed-root.pdf", "scanned-update.png")
    assert request.recovery_text_file == "transcribed.txt"
    assert request.payloads_file == "payloads.txt"


def test_run_rebuild_preview_uses_task_model() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "rebuild",
            "--backup-folder",
            "backup-out",
            "--allow-stale-head",
            "--passphrase",
            "secret",
            "--auth-payloads-file",
            "auth-payloads.json",
            "--output-dir",
            "rebuilt",
            "--preview",
        ],
    )

    assert result.exit_code == 0
    assert "Existing backup" in result.output
    assert "Rebuilt backup to create" in result.output


def test_run_rebuild_yes_executes_task_model(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(status="succeeded", message="Rebuilt backup documents created.")

    monkeypatch.setattr("ethernity.tasks.rebuild.RebuildTaskState.execute", fake_execute)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "rebuild",
            "--backup-folder",
            "backup-out",
            "--allow-stale-head",
            "--passphrase",
            "secret",
            "--auth-payloads-file",
            "auth-payloads.json",
            "--qr-chunk-size",
            "384",
            "--paper",
            "LETTER",
            "--design",
            "forge",
            "--output-dir",
            "rebuilt",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert str(calls[0].output_dir) == "rebuilt"
    assert calls[0].auth_payloads_file == Path("auth-payloads.json")
    assert calls[0].to_rebuild_request().auth_payloads_file == Path("auth-payloads.json")
    assert calls[0].qr_chunk_size == 384
    assert calls[0].to_rebuild_request().qr_chunk_size == 384
    assert calls[0].paper_size == "LETTER"
    assert calls[0].design == "forge"
    assert calls[0].to_rebuild_request().paper_size == "LETTER"
    assert calls[0].to_rebuild_request().design == "forge"
    assert "Rebuilt backup documents created." in result.output


def test_run_replace_recovery_docs_preview_uses_task_model() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "replace-recovery-docs",
            "--scan",
            "scans",
            "--passphrase",
            "secret",
            "--output-dir",
            "replacement-docs",
            "--allow-stale-head",
            "--preview",
        ],
    )

    assert result.exit_code == 0
    assert "Existing backup" in result.output
    assert "Replacement recovery sheets to create" in result.output


def test_run_replace_recovery_docs_yes_executes_task_model(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(
            status="succeeded", message="Replacement recovery documents created."
        )

    monkeypatch.setattr(
        "ethernity.tasks.replace_recovery_docs.ReplaceRecoveryDocsTaskState.execute",
        fake_execute,
    )
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "replace-recovery-docs",
            "--scan",
            "scans",
            "--passphrase",
            "secret",
            "--output-dir",
            "replacement-docs",
            "--allow-stale-head",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert str(calls[0].output_dir) == "replacement-docs"
    assert calls[0].allow_stale_head
    assert "Replacement recovery documents created." in result.output


def test_run_print_kit_preview_uses_task_model() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "print-kit",
            "--output",
            "kit.pdf",
            "--preview",
        ],
    )

    assert result.exit_code == 0
    assert "Offline recovery kit" in result.output
    assert "Offline recovery kit to create" in result.output
    assert "kit.pdf" in result.output


def test_run_print_kit_yes_executes_task_model(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(status="succeeded", message="Recovery kit created.")

    monkeypatch.setattr("ethernity.tasks.kit.PrintKitTaskState.execute", fake_execute)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "print-kit",
            "--output",
            "kit.pdf",
            "--qr-chunk-size",
            "512",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert str(calls[0].output_path) == "kit.pdf"
    assert calls[0].chunk_size == 512
    assert "Recovery kit created." in result.output
