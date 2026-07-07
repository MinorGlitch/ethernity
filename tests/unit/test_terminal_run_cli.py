from __future__ import annotations

import json
import tomllib
from pathlib import Path

from click.testing import CliRunner

import ethernity.cli as legacy_cli
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


def test_cli_package_no_longer_exports_legacy_entrypoints_or_command_runners() -> None:
    old_exports = (
        "main",
        "app",
        "run_wizard",
        "run_recover_wizard",
        "run_mint_wizard",
        "run_backup",
        "run_backup_command",
        "run_compact",
        "run_extend",
        "run_mint_command",
        "run_recover_command",
        "AUTH_FALLBACK_LABEL",
        "MAIN_FALLBACK_LABEL",
        "BackupResult",
        "InputFile",
        "decrypt_bytes",
        "encrypt_bytes_with_passphrase",
    )
    for name in old_exports:
        assert not hasattr(legacy_cli, name)


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
    assert "Nothing will be written until final review." in result.output


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
        "BACKUP_OUTPUT_REQUIRED",
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
        return TaskExecutionResult(ok=True, message="Backup documents created.")

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
    assert calls[0].to_backup_args().qr_chunk_size == 384
    assert calls[0].to_backup_args().passphrase_words == 18
    assert "Backup documents created." in result.output


def test_run_backup_json_yes_executes_task_model(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(
            ok=True,
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
    assert payload["result"]["output_paths"] == ["backup-out/main.pdf"]


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
    assert "Restore preview" in result.output


def test_run_restore_yes_executes_task_model(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(ok=True, message="Recovered files written.")

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
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0].source_paths
    assert calls[0].auth_text_file == Path("auth.txt")
    assert calls[0].to_recover_args().auth_fallback_file == "auth.txt"
    assert calls[0].passphrase == "secret"
    assert "Recovered files written." in result.output


def test_run_add_files_preview_uses_task_model() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "add-files",
            "--backup-folder",
            "backup-out",
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
        return TaskExecutionResult(ok=True, message="Added files as backup update 01.")

    monkeypatch.setattr("ethernity.tasks.add_files.AddFilesTaskState.execute", fake_execute)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "add-files",
            "--backup-folder",
            "backup-out",
            "--input",
            "new-file.txt",
            "--passphrase",
            "secret",
            "--qr-chunk-size",
            "384",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert str(calls[0].backup_folder) == "backup-out"
    assert calls[0].qr_chunk_size == 384
    assert calls[0].to_extend_args().qr_chunk_size == 384
    assert "Added files as backup update 01." in result.output


def test_run_add_files_rejects_unsupported_auth_material_options() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["add-files", "--auth-text", "auth.txt"])

    assert result.exit_code == 2
    assert "No such option '--auth-text'" in result.output


def test_run_rebuild_preview_uses_task_model() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "rebuild",
            "--backup-folder",
            "backup-out",
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
    assert "Backup source" in result.output
    assert "Rebuilt backup to create" in result.output


def test_run_rebuild_yes_executes_task_model(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(ok=True, message="Rebuilt backup documents created.")

    monkeypatch.setattr("ethernity.tasks.rebuild.RebuildTaskState.execute", fake_execute)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "rebuild",
            "--backup-folder",
            "backup-out",
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
    assert calls[0].to_compact_args().auth_payloads_file == "auth-payloads.json"
    assert calls[0].qr_chunk_size == 384
    assert calls[0].to_compact_args().qr_chunk_size == 384
    assert calls[0].paper_size == "LETTER"
    assert calls[0].design == "forge"
    assert calls[0].to_compact_args().paper == "LETTER"
    assert calls[0].to_compact_args().design == "forge"
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
    assert "Backup source" in result.output
    assert "Replacement recovery documents to create" in result.output


def test_run_replace_recovery_docs_yes_executes_task_model(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(ok=True, message="Replacement recovery documents created.")

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
    assert "Recovery kit" in result.output
    assert "Recovery kit to create" in result.output
    assert "kit.pdf" in result.output


def test_run_print_kit_yes_executes_task_model(monkeypatch) -> None:
    calls = []

    def fake_execute(self):
        calls.append(self)
        return TaskExecutionResult(ok=True, message="Recovery kit created.")

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


def test_run_doctor_uses_task_model() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["doctor"])

    assert result.exit_code == 0
    assert "Setup check" in result.output
    assert "Python runtime" in result.output
