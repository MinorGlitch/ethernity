"""Documentation changes must skip expensive work without hiding failed checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from tooling.release import ci_plan, github


@pytest.mark.parametrize(
    "path",
    (
        "README.md",
        "README_PYPI.md",
        "CONTRIBUTING.md",
        "AGENTS.md",
        "docs/format.md",
        "docs/releases/1.2.0.md",
        "images/readme/backup_flow.gif",
        "images/readme/terminal_app_preview.svg",
        "images/ethernity-animated.png",
        "images/ICONS.md",
        "tooling/demos/README.md",
    ),
)
def test_documentation_and_readme_media_need_only_light_checks(path):
    for event in ("push", "pull_request"):
        assert ci_plan.selection([path], event=event) == {
            "full": "false",
            "native": "false",
            "homebrew": "false",
        }


@pytest.mark.parametrize(
    "path",
    (
        "src/ethernity/main.py",
        "src/ethernity/resources/icons/app.png",
        "src/ethernity/resources/kit/recovery_kit.bundle.html",
        "tests/fixtures/README.md",
        "kit/app/main.js",
        "browser/package-lock.json",
        "images/ethernity.ico",
        "images/ethernity-logo.svg",
        "images/ethernity-app.svg",
        "tooling/demos/record_backup.py",
        "tooling/demos/render_logo.mjs",
        "tooling/demos/backup.tape",
        "docs/build.py",
        "docs/format_rationale.md",
        "images/readme/build.sh",
        "unknown.txt",
    ),
)
def test_unknown_or_executable_inputs_keep_full_checks_even_with_docs(path):
    assert ci_plan.selection(["README.md", path])["full"] == "true"
    assert ci_plan.selection([path])["native"] == "true"


@pytest.mark.parametrize(
    "path",
    ("uv.lock", "pyproject.toml", ".github/workflows/ci.yml", "ethernity.spec", "scripts/brew.rb"),
)
def test_packaging_inputs_keep_both_rehearsals(path):
    assert ci_plan.selection([path]) == {"full": "true", "native": "true", "homebrew": "true"}


def test_source_changes_preserve_existing_homebrew_selection():
    assert ci_plan.selection(["src/ethernity/formats/document.py"]) == {
        "full": "true",
        "native": "true",
        "homebrew": "false",
    }
    assert ci_plan.selection(["src/ethernity/formats/document.py"], event="push") == {
        "full": "true",
        "native": "true",
        "homebrew": "true",
    }


@pytest.mark.parametrize("paths", (None, []))
def test_unknown_or_empty_diff_keeps_every_check(paths):
    assert ci_plan.selection(paths) == {"full": "true", "native": "true", "homebrew": "true"}


def commit() -> str:
    github.run("git", "add", "--all")
    github.run("git", "-c", "commit.gpgsign=false", "commit", "-qm", "test change")
    return github.run("git", "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    github.run("git", "init", "-q", "--initial-branch=master")
    github.run("git", "config", "user.name", "Test")
    github.run("git", "config", "user.email", "test@example.com")
    (tmp_path / "README.md").write_text("Original documentation\n", encoding="utf-8")
    (tmp_path / "code.py").write_text("print('example')\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.0"\n', encoding="utf-8")
    return commit()


@pytest.mark.parametrize("event", ("pull_request", "push"))
def test_diff_includes_all_commits_and_both_sides_of_renames(repository, event):
    Path("README.md").write_text("Updated documentation\n", encoding="utf-8")
    commit()
    assert ci_plan.changed_paths(event, repository) == ["README.md"]
    Path("docs").mkdir()
    Path("code.py").rename("docs/code.md")
    commit()
    paths = ci_plan.changed_paths(event, repository)
    assert set(paths or []) == {"README.md", "code.py", "docs/code.md"}
    assert ci_plan.selection(paths)["full"] == "true"


def test_diff_does_not_quote_or_truncate_filenames(repository):
    Path("docs").mkdir()
    # GitHub path filters truncate long file lists; the local diff must not.
    for number in range(310):
        Path(f"docs/page {number}.md").touch()
    Path("z-runtime.py").touch()
    commit()
    paths = ci_plan.changed_paths("push", repository)
    assert len(paths or []) == 311
    assert "docs/page 0.md" in (paths or [])
    assert ci_plan.selection(paths)["full"] == "true"


@pytest.mark.parametrize(
    ("event", "base"),
    (
        ("schedule", "HEAD"),
        ("workflow_dispatch", "HEAD"),
        ("push", ""),
        ("push", "0" * 40),
        ("push", "f" * 40),
    ),
)
def test_forced_runs_and_unavailable_bases_do_not_skip_checks(repository, event, base):
    assert ci_plan.selection(ci_plan.changed_paths(event, base)) == {
        "full": "true",
        "native": "true",
        "homebrew": "true",
    }


def needs_context(full: bool) -> dict:
    needs = {name: {"result": "success" if full else "skipped"} for name in ci_plan.FULL_JOBS}
    needs["plan"] = {
        "result": "success",
        "outputs": ci_plan.selection(None if full else ["README.md"]),
    }
    needs["documentation-checks"] = {"result": "skipped" if full else "success"}
    return needs


@pytest.mark.parametrize("full", (True, False))
def test_gate_accepts_selected_successes_but_never_failure_cancellation_or_missing_jobs(full):
    needs = needs_context(full)
    assert ci_plan.failures(needs) == []
    for name in needs:
        for result in ("failure", "cancelled"):
            changed = {**needs, name: {**needs[name], "result": result}}
            assert name in ci_plan.failures(changed)
        assert name in ci_plan.failures({key: value for key, value in needs.items() if key != name})
    needs["new-check"] = {"result": "skipped"}
    assert ci_plan.failures(needs) == ["new-check"]


def test_full_gate_requires_every_test_coverage_and_audit_job():
    needs = needs_context(True)
    for name in ci_plan.FULL_JOBS:
        assert ci_plan.failures({**needs, name: {"result": "skipped"}}) == [name]


@pytest.mark.parametrize(
    ("job", "flag"), (("native-packages", "native"), ("homebrew-rehearsal", "homebrew"))
)
def test_only_explicitly_unselected_packaging_can_be_skipped_in_full_ci(job, flag):
    needs = needs_context(True)
    needs[job]["result"] = "skipped"
    assert ci_plan.failures(needs) == [job]
    needs["plan"]["outputs"][flag] = "false"
    assert ci_plan.failures(needs) == []


@pytest.mark.parametrize("full", (True, False))
def test_missing_invalid_or_inconsistent_plan_outputs_fail_closed(full):
    needs = needs_context(full)
    for flag in ("full", "native", "homebrew"):
        value = needs["plan"]["outputs"].pop(flag)
        assert "plan" in ci_plan.failures(needs)
        needs["plan"]["outputs"][flag] = "invalid"
        assert "plan" in ci_plan.failures(needs)
        needs["plan"]["outputs"][flag] = value
    needs["plan"]["outputs"].update(full="false", native="true")
    assert "plan" in ci_plan.failures(needs)


def test_documentation_gate_requires_spelling_check():
    needs = needs_context(False)
    needs["documentation-checks"]["result"] = "skipped"
    assert ci_plan.failures(needs) == ["documentation-checks"]


def test_workflow_entry_points_emit_plan_and_enforce_gate(repository, tmp_path, monkeypatch):
    Path("README.md").write_text("Changed documentation\n", encoding="utf-8")
    commit()
    outputs = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("BASE_SHA", repository)
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    monkeypatch.setattr(sys, "argv", ["ci_plan"])
    ci_plan.main()
    assert dict(line.split("=", 1) for line in outputs.read_text().splitlines()) == {
        "tag": "v1.2.0",
        "full": "false",
        "native": "false",
        "homebrew": "false",
    }
    needs = needs_context(False)
    monkeypatch.setattr(sys, "argv", ["ci_plan", "gate"])
    monkeypatch.setenv("NEEDS_CONTEXT", json.dumps(needs))
    ci_plan.main()
    needs["documentation-checks"]["result"] = "failure"
    monkeypatch.setenv("NEEDS_CONTEXT", json.dumps(needs))
    with pytest.raises(SystemExit, match="documentation-checks"):
        ci_plan.main()
