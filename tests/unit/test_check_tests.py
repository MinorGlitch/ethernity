"""A partial or failed local test run must not masquerade as a complete CI check."""

import subprocess
from pathlib import Path

import pytest
from tooling import check_tests


@pytest.fixture
def commands(monkeypatch):
    calls = []

    def run(command, *, cwd, env, check):
        calls.append((command, env))
        if env and "COVERAGE_FILE" in env:
            Path(env["COVERAGE_FILE"]).touch()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(check_tests.subprocess, "run", run)
    monkeypatch.setattr(check_tests, "check_setup", lambda: True)
    return calls


def test_default_includes_every_suite_and_enforces_both_coverage_gates(commands, tmp_path, capsys):
    assert check_tests.main(["--results-dir", str(tmp_path)]) == 0
    pytest_runs = [(cmd, env) for cmd, env in commands if cmd[2] == "pytest"]
    paths = {arg for cmd, _ in pytest_runs for arg in cmd if arg.startswith("tests/")}
    assert paths == {
        "tests/unit",
        "tests/integration",
        "tests/ui",
        "tests/rendering",
        "tests/e2e",
        "tests/visual",
    }
    ui = [cmd for cmd, _ in pytest_runs if "tests/ui" in cmd]
    assert len(ui) == 2
    assert {arg for cmd in ui for arg in cmd if arg.startswith("--group=")} == {
        "--group=1",
        "--group=2",
    }
    assert all("--splits=2" in cmd for cmd in ui)
    coverage_paths = [env["COVERAGE_FILE"] for _, env in pytest_runs if "COVERAGE_FILE" in env]
    assert len(set(coverage_paths)) == 4
    reports = [cmd for cmd, _ in commands if cmd[2:4] == ["coverage", "report"]]
    assert len(reports) == 2
    assert "--include=src/ethernity/*" in reports[0] and "--fail-under=85" in reports[0]
    assert "--include=tooling/document_inspector_app/*" in reports[1]
    assert "--fail-under=45" in reports[1]
    assert "Full local Python check:" in capsys.readouterr().out


def test_core_selection_includes_integration_and_identifies_partial_run(commands, tmp_path, capsys):
    assert check_tests.main(["core", "--results-dir", str(tmp_path)]) == 0
    assert len(commands) == 1
    command, _ = commands[0]
    assert "tests/unit" in command and "tests/integration" in command
    assert "Partial check: core only." in capsys.readouterr().out


def test_failed_core_does_not_run_coverage_or_hide_other_suites(commands, monkeypatch, tmp_path):
    successful_run = check_tests.subprocess.run

    def fail_core(command, **kwargs):
        result = successful_run(command, **kwargs)
        result.returncode = 1 if "tests/integration" in command else 0
        return result

    monkeypatch.setattr(check_tests.subprocess, "run", fail_core)
    assert check_tests.main(["--results-dir", str(tmp_path)]) == 1
    assert any("tests/visual" in cmd for cmd, _ in commands)
    assert any("tests/e2e" in cmd for cmd, _ in commands)
    assert not any(cmd[2] == "coverage" for cmd, _ in commands)


@pytest.mark.parametrize("threshold", [85, 45])
def test_either_coverage_failure_fails_full_run(commands, monkeypatch, tmp_path, threshold):
    successful_run = check_tests.subprocess.run

    def fail_gate(command, **kwargs):
        result = successful_run(command, **kwargs)
        result.returncode = 2 if f"--fail-under={threshold}" in command else 0
        return result

    monkeypatch.setattr(check_tests.subprocess, "run", fail_gate)
    assert check_tests.main(["--results-dir", str(tmp_path)]) == 1
    assert sum(cmd[2:4] == ["coverage", "report"] for cmd, _ in commands) == 2


def test_incomplete_coverage_cannot_pass_using_previous_combined_data(commands, tmp_path, capsys):
    (tmp_path / ".coverage").touch()
    for suite in ("core", "rendering", "ui-1"):
        (tmp_path / f".coverage.{suite}").touch()
    assert check_tests.main(["coverage", "--results-dir", str(tmp_path)]) == 1
    assert not commands
    assert "missing .coverage.ui-2" in capsys.readouterr().err


def test_full_check_stops_if_prerequisites_are_missing(commands, monkeypatch, tmp_path):
    monkeypatch.setattr(check_tests, "check_setup", lambda: False)
    assert check_tests.main(["--results-dir", str(tmp_path)]) == 1
    assert not commands


def test_setup_requires_generated_bundles_and_tools_that_tests_would_skip(monkeypatch, tmp_path):
    monkeypatch.setattr(check_tests, "ROOT", tmp_path)
    monkeypatch.setattr(check_tests.shutil, "which", lambda tool: f"/tools/{tool}")
    assert not check_tests.check_setup()
    (tmp_path / "kit/node_modules").mkdir(parents=True)
    for entry in check_tests.REQUIRED_KIT_ENTRIES:
        path = tmp_path / "src/ethernity" / entry
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    assert check_tests.check_setup()
    monkeypatch.setattr(
        check_tests.shutil, "which", lambda tool: None if tool == "node" else f"/tools/{tool}"
    )
    assert not check_tests.check_setup()


def test_snapshot_tests_cannot_contribute_to_coverage(commands, tmp_path):
    with pytest.raises(SystemExit) as error:
        check_tests.main(["visual", "--coverage", "--results-dir", str(tmp_path)])
    assert error.value.code == 2
    assert not commands
