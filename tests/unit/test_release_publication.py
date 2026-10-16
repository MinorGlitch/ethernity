"""Release failures and retries must never replace an existing public artifact."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from tooling.release import ci_plan, cli, github, homebrew, inventory, precheck, smoke
from tooling.release.publish import publish

TAG = "v1.2.0"
SHA = "a" * 40


class FakeGitHub(github.GitHub):
    def __init__(self, *, exists=True, draft=True, prerelease=False, assets=None):
        super().__init__("example/repo")
        self.exists = exists
        self.draft = draft
        self.prerelease = prerelease
        self.assets = assets or {}
        self.sha = SHA
        self.commands = []
        self.omit_upload = False

    def tag_sha(self, tag):
        return self.sha

    def release(self, tag):
        if not self.exists:
            return None
        return {
            "draft": self.draft,
            "prerelease": self.prerelease,
            "assets": [{"name": name} for name in self.assets],
        }

    def download(self, tag, name, directory):
        path = directory / name
        path.write_bytes(self.assets[name])
        return path

    def command(self, *args):
        self.commands.append(args)
        if args[0] == "create":
            self.exists = True
        if args[0] == "upload" and not self.omit_upload:
            for value in args[2:]:
                path = Path(value)
                self.assets[path.name] = path.read_bytes()
        if args[0] == "edit":
            self.draft = "--draft=true" in args
            self.prerelease = "--prerelease=true" in args
        return ""


@pytest.fixture
def files(tmp_path):
    paths = [tmp_path / "archive.zip", tmp_path / "archive.zip.sigstore.json"]
    for path in paths:
        path.write_bytes(path.name.encode())
    return paths


def test_new_release_is_completed_before_publication(files):
    remote = FakeGitHub(exists=False)
    publish(remote, TAG, files, sha=SHA)
    assert [cmd[0] for cmd in remote.commands] == ["create", "upload", "edit"]
    assert remote.assets == {path.name: path.read_bytes() for path in files}
    assert not remote.draft


def test_partial_draft_uploads_only_missing_files(files):
    remote = FakeGitHub(assets={files[0].name: files[0].read_bytes()})
    publish(remote, TAG, files, sha=SHA, draft=True)
    assert remote.commands[0] == ("upload", TAG, str(files[1]))
    assert remote.draft


def test_complete_published_retry_has_no_mutations(files):
    remote = FakeGitHub(draft=False, assets={path.name: path.read_bytes() for path in files})
    publish(remote, TAG, files, sha=SHA)
    assert remote.commands == []


@pytest.mark.parametrize("draft", [True, False])
def test_mismatched_existing_bytes_are_never_replaced(files, draft):
    remote = FakeGitHub(draft=draft, assets={path.name: b"different" for path in files})
    with pytest.raises(ValueError, match="mismatched"):
        publish(remote, TAG, files, sha=SHA)
    assert remote.commands == []


@pytest.mark.parametrize("state", ["unexpected", "incomplete", "prerelease", "draft-request"])
def test_invalid_published_release_is_not_modified(files, state):
    assets = {path.name: path.read_bytes() for path in files}
    if state == "unexpected":
        assets["surprise"] = b"data"
    if state == "incomplete":
        assets.pop(files[1].name)
    remote = FakeGitHub(draft=False, prerelease=state == "prerelease", assets=assets)
    with pytest.raises(ValueError):
        publish(remote, TAG, files, sha=SHA, draft=state == "draft-request")
    assert remote.commands == []


def test_incomplete_upload_never_publishes(files):
    remote = FakeGitHub()
    remote.omit_upload = True
    with pytest.raises(ValueError, match="incomplete after upload"):
        publish(remote, TAG, files, sha=SHA)
    assert not any(command[0] == "edit" for command in remote.commands)


def test_tag_moving_during_upload_never_publishes(files):
    remote = FakeGitHub()

    def recheck():
        if remote.assets:
            remote.sha = "b" * 40

    # The recheck catches branch/tag changes before the final publish.
    def move_tag(tag, name, directory):
        remote.sha = "b" * 40
        return FakeGitHub.download(remote, tag, name, directory)

    remote.assets = {files[0].name: files[0].read_bytes()}
    remote.download = move_tag
    with pytest.raises(ValueError, match="tag .*changed"):
        publish(remote, TAG, files, sha=SHA, recheck=recheck)
    assert not any(command[0] == "edit" for command in remote.commands)


@pytest.mark.parametrize(
    "version,prerelease",
    [
        ("1.2.0", False),
        ("1.2.0rc1", True),
        ("1.3.0b1", True),
        ("1.3.0.dev1", True),
        ("1.2.0.post1", False),
    ],
)
def test_python_version_classification(version, prerelease):
    assert inventory.validate_tag(f"v{version}", version).is_prerelease is prerelease


@pytest.mark.parametrize("tag", ["v1.3.0", "../1.2.0", "v1.2.0\nextra"])
def test_release_tag_must_match_project_version(tag):
    with pytest.raises(ValueError):
        inventory.validate_tag(tag, "1.2.0")


def test_inventory_rejects_extra_missing_and_empty_files(tmp_path):
    names = inventory.release_files(TAG)
    assert len(names) == 24
    for name in names:
        (tmp_path / name).write_bytes(b"contents")
    assert len(inventory.validate_files(tmp_path, names)) == 24
    (tmp_path / "extra").write_bytes(b"contents")
    with pytest.raises(ValueError, match="mismatch"):
        inventory.validate_files(tmp_path, names)
    (tmp_path / "extra").unlink()
    (tmp_path / names[0]).write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        inventory.validate_files(tmp_path, names)
    (tmp_path / names[0]).unlink()
    with pytest.raises(ValueError, match="mismatch"):
        inventory.validate_files(tmp_path, names)


def test_latest_exact_master_push_is_required():
    good = {
        "event": "push",
        "head_branch": "master",
        "head_sha": SHA,
        "status": "completed",
        "conclusion": "success",
        "run_number": 1,
    }
    assert precheck.ci_success([good], SHA)
    for field, value in [
        ("event", "pull_request"),
        ("head_branch", "dev"),
        ("head_sha", "other"),
        ("status", "in_progress"),
    ]:
        assert not precheck.ci_success([{**good, field: value}], SHA)
    with pytest.raises(ValueError, match="latest master CI failed"):
        precheck.ci_success([good, {**good, "run_number": 2, "conclusion": "failure"}], SHA)


@pytest.mark.parametrize(
    "stderr,absent",
    [
        ("gh: Not Found (HTTP 404)", True),
        ("HTTP 403 rate limit", False),
        ("connection failed", False),
    ],
)
def test_only_confirmed_not_found_can_create_a_release(monkeypatch, stderr, absent):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 1, "", stderr)
    )
    remote = github.GitHub("example/repo")
    if absent:
        assert remote.release(TAG) is None
    else:
        with pytest.raises(RuntimeError):
            remote.release(TAG)


@pytest.fixture
def bottle_payload(tmp_path):
    bottles = tmp_path / "bottles"
    bottles.mkdir()
    for platform in ("arm64_sonoma", "sequoia", "x86_64_linux"):
        (bottles / f"ethernity--1.2.0.{platform}.bottle.tar.gz").write_bytes(platform.encode())
    formula = tmp_path / "formula.rb"
    formula.write_text(
        'url "https://github.com/example/repo/releases/download/v1.2.0/source.tar.gz"\n'
    )
    directory = tmp_path / "publication"
    homebrew.assemble(directory, formula, bottles, tag=TAG, source_sha=SHA, tap_base=SHA)
    return directory


def test_fresh_homebrew_retry_keeps_bottle_origin_and_updates_current_tap_base(
    monkeypatch, bottle_payload, tmp_path
):
    remote = FakeGitHub(
        draft=False, assets={p.name: p.read_bytes() for p in bottle_payload.iterdir()}
    )
    new_base = "b" * 40
    monkeypatch.setattr(homebrew, "run", lambda *a, **kw: f"{new_base}\trefs/heads/master")
    directory = tmp_path / "download"
    base, reuse = homebrew.prepare(remote, TAG, SHA, directory)
    assert (base, reuse) == (new_base, True)
    assert homebrew.validate_payload(directory, tag=TAG, source_sha=SHA)["tap_base"] == SHA
    assert remote.commands == []


@pytest.mark.parametrize("corruption", ["bytes", "source", "extra", "traversal"])
def test_homebrew_reuse_rejects_corrupt_payload(bottle_payload, corruption):
    manifest_path = bottle_payload / homebrew.MANIFEST
    manifest = json.loads(manifest_path.read_text())
    if corruption == "bytes":
        (bottle_payload / homebrew.FORMULA).write_text("tampered")
    elif corruption == "source":
        manifest["source_sha"] = "b" * 40
    elif corruption == "traversal":
        manifest["files"]["../escape"] = "bad"
    else:
        (bottle_payload / "extra").write_text("bad")
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        homebrew.validate_payload(bottle_payload, tag=TAG, source_sha=SHA)


def test_formula_update_and_fresh_retry_use_fast_forward_guard(tmp_path, bottle_payload):
    remote = tmp_path / "tap.git"
    github.run("git", "init", "--bare", "--initial-branch=master", str(remote))
    checkout = tmp_path / "tap"
    github.run("git", "clone", str(remote), str(checkout))
    (checkout / "Formula").mkdir()
    (checkout / "Formula/ethernity.rb").write_text("old formula")
    github.run("git", "add", ".", cwd=checkout)
    github.run(
        "git",
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "initial",
        cwd=checkout,
    )
    github.run("git", "push", "origin", "master", cwd=checkout)
    base = github.run("git", "rev-parse", "HEAD", cwd=checkout)
    homebrew.publish_formula(checkout, bottle_payload, base, TAG)
    updated = github.run("git", "rev-parse", "HEAD", cwd=checkout)
    assert updated != base
    homebrew.publish_formula(checkout, bottle_payload, updated, TAG)
    assert github.run("git", "rev-parse", "HEAD", cwd=checkout) == updated
    with pytest.raises(ValueError, match="changed"):
        homebrew.publish_formula(checkout, bottle_payload, base, TAG)


def test_linux_baseline_rejects_newer_native_library(monkeypatch, tmp_path):
    (tmp_path / "libexample.so").write_bytes(b"\x7fELFpayload")
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: "GLIBC_2.17 GLIBC_2.35")
    smoke.check_glibc(tmp_path)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: "GLIBC_2.36")
    with pytest.raises(ValueError, match="newer than 2.35"):
        smoke.check_glibc(tmp_path)


def test_packaging_plan_keeps_all_test_gates():
    assert ci_plan.packaging_changes(["docs/format.md", "README.md"]) == (False, False)
    assert ci_plan.packaging_changes(["src/ethernity/formats/document.py"]) == (True, False)
    for path in (
        "uv.lock",
        "pyproject.toml",
        ".github/workflows/ci.yml",
        "ethernity.spec",
        "scripts/homebrew_ethernity_tap.rb",
    ):
        assert ci_plan.packaging_changes([path]) == (True, True)
    needs = {
        "kit-bundles": {"result": "success", "outputs": {"homebrew": "false"}},
        "homebrew-rehearsal": {"result": "skipped"},
        "test": {"result": "success"},
    }
    assert ci_plan.failures(needs) == []
    needs["test"]["result"] = "skipped"
    assert ci_plan.failures(needs) == ["test"]
    needs["kit-bundles"]["outputs"]["homebrew"] = "true"
    assert "homebrew-rehearsal" in ci_plan.failures(needs)


def test_published_precheck_requires_complete_inventory():
    remote = FakeGitHub(
        draft=False, assets={name: b"data" for name in inventory.release_files(TAG)}
    )
    assert precheck.published_release(remote, TAG, draft=False, prerelease=False)
    remote.assets.pop(next(iter(remote.assets)))
    with pytest.raises(ValueError, match="asset set"):
        precheck.published_release(remote, TAG, draft=False, prerelease=False)


def test_signing_verifies_exact_workflow_identity_and_issuer(monkeypatch, tmp_path):
    for name in inventory.release_files(TAG, signed=False):
        (tmp_path / name).write_bytes(b"content")
    workflow = "example/repo/.github/workflows/pyinstaller.yml@refs/tags/v1.2.0"
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", workflow)
    commands = []
    monkeypatch.setattr(cli, "run", lambda *args: commands.append(args))
    cli.sign(tmp_path, TAG)
    verification = [args for args in commands if args[1] == "verify-blob"]
    assert len(verification) == 12
    for args in verification:
        assert args[args.index("--certificate-identity") + 1] == f"https://github.com/{workflow}"
        assert (
            args[args.index("--certificate-oidc-issuer") + 1]
            == "https://token.actions.githubusercontent.com"
        )


def test_existing_release_retry_verifies_all_signatures_before_success(monkeypatch):
    remote = FakeGitHub(
        draft=False, assets={name: b"content" for name in inventory.release_files(TAG)}
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", remote.repo)
    monkeypatch.setenv("RELEASE_COMMIT_SHA", SHA)
    monkeypatch.setattr(cli, "GitHub", lambda repo: remote)
    checked = []
    monkeypatch.setattr(cli, "check_master", lambda tag, sha: checked.append((tag, sha)))
    commands = []
    monkeypatch.setattr(cli, "run", lambda *args: commands.append(args))
    cli.verify_published(TAG)
    assert checked == [(TAG, SHA), (TAG, SHA)]
    assert len(commands) == 12
    assert all(command[1] == "verify-blob" for command in commands)
    assert remote.commands == []


def test_existing_release_signature_failure_aborts_retry(monkeypatch):
    remote = FakeGitHub(
        draft=False, assets={name: b"content" for name in inventory.release_files(TAG)}
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", remote.repo)
    monkeypatch.setenv("RELEASE_COMMIT_SHA", SHA)
    monkeypatch.setattr(cli, "GitHub", lambda repo: remote)
    monkeypatch.setattr(cli, "check_master", lambda *args: None)

    def invalid_signature(*args):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(cli, "run", invalid_signature)
    with pytest.raises(subprocess.CalledProcessError):
        cli.verify_published(TAG)
