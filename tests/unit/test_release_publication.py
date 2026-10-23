"""Release failures and retries must never replace an existing public artifact."""

from __future__ import annotations

import json
import re
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
        self.body = ""

    def tag_sha(self, tag):
        return self.sha

    def release(self, tag):
        if not self.exists:
            return None
        return {
            "draft": self.draft,
            "prerelease": self.prerelease,
            "assets": [{"name": name} for name in self.assets],
            "body": self.body,
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
            if "--notes-file" in args:
                self.body = Path(args[args.index("--notes-file") + 1]).read_text()
            else:
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
        ("1.2.0a1", True),
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


def test_release_version_must_match_the_normalized_wheel_name():
    with pytest.raises(ValueError, match="canonical Python version"):
        inventory.validate_tag("v1.2.0-beta.1", "1.2.0-beta.1")


def test_inventory_rejects_extra_missing_and_empty_files(tmp_path):
    names = inventory.release_files(TAG)
    assert len(names) == 30
    assert not any("macos-x64" in name for name in names)
    for name in names:
        (tmp_path / name).write_bytes(b"contents")
    assert len(inventory.validate_files(tmp_path, names)) == 30
    extra = tmp_path / f"ethernity-{TAG}-macos-x64.tar.gz"
    extra.write_bytes(b"contents")
    with pytest.raises(ValueError, match="mismatch"):
        inventory.validate_files(tmp_path, names)
    extra.unlink()
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
    for platform in ("arm64_sonoma", "x86_64_linux"):
        (bottles / f"ethernity--1.2.0.{platform}.bottle.tar.gz").write_bytes(platform.encode())
    formula = tmp_path / "formula.rb"
    formula.write_text(
        'url "https://github.com/example/repo/releases/download/v1.2.0/source.tar.gz"\n'
    )
    directory = tmp_path / "publication"
    homebrew.assemble(directory, formula, bottles, tag=TAG, source_sha=SHA, tap_base=SHA)
    return directory


@pytest.mark.parametrize("invalid", ["missing", "extra", "duplicate"])
def test_homebrew_assembly_requires_two_distinct_bottles(tmp_path, invalid):
    names = ["arm64_sonoma", "x86_64_linux"]
    if invalid == "missing":
        names.pop()
    elif invalid == "extra":
        names.append("sequoia")
    else:
        names[1] = names[0]
    bottles = tmp_path / "bottles"
    for index, platform in enumerate(names):
        directory = bottles / str(index)
        directory.mkdir(parents=True)
        (directory / f"ethernity--1.2.0.{platform}.bottle.tar.gz").write_bytes(b"bottle")
    formula = tmp_path / "formula.rb"
    formula.write_text("formula")
    with pytest.raises(ValueError, match="two distinct bottle tarballs"):
        homebrew.assemble(
            tmp_path / "publication", formula, bottles, tag=TAG, source_sha=SHA, tap_base=SHA
        )


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


@pytest.mark.parametrize("corruption", ["bytes", "source", "extra", "traversal", "extra_bottle"])
def test_homebrew_reuse_rejects_corrupt_payload(bottle_payload, corruption):
    manifest_path = bottle_payload / homebrew.MANIFEST
    manifest = json.loads(manifest_path.read_text())
    if corruption == "bytes":
        (bottle_payload / homebrew.FORMULA).write_text("tampered")
    elif corruption == "source":
        manifest["source_sha"] = "b" * 40
    elif corruption == "traversal":
        manifest["files"]["../escape"] = "bad"
    elif corruption == "extra_bottle":
        bottle = bottle_payload / "ethernity--1.2.0.sequoia.bottle.tar.gz"
        bottle.write_bytes(b"intel")
        manifest["files"][bottle.name] = homebrew.digest(bottle)
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
    assert sorted(Path(args[-1]).name for args in verification) == sorted(
        inventory.release_files(TAG, signed=False)
    )
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
    monkeypatch.setattr(cli, "check_release_commit", lambda tag, sha: checked.append((tag, sha)))
    commands = []
    monkeypatch.setattr(cli, "run", lambda *args: commands.append(args))
    cli.verify_published(TAG)
    assert checked == [(TAG, SHA), (TAG, SHA)]
    assert sorted(Path(command[-1]).name for command in commands) == sorted(
        inventory.release_files(TAG, signed=False)
    )
    assert all(command[1] == "verify-blob" for command in commands)
    assert remote.commands == []


def test_existing_release_signature_failure_aborts_retry(monkeypatch):
    remote = FakeGitHub(
        draft=False, assets={name: b"content" for name in inventory.release_files(TAG)}
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", remote.repo)
    monkeypatch.setenv("RELEASE_COMMIT_SHA", SHA)
    monkeypatch.setattr(cli, "GitHub", lambda repo: remote)
    monkeypatch.setattr(cli, "check_release_commit", lambda *args: None)

    def invalid_signature(*args):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(cli, "run", invalid_signature)
    with pytest.raises(subprocess.CalledProcessError):
        cli.verify_published(TAG)


@pytest.mark.parametrize("tag", ["v1.2.0a1", "v1.2.0b1", "v1.2.0rc1", "v1.2.0.dev1"])
def test_branch_prerelease_rechecks_tag_without_master_ancestry(monkeypatch, tag):
    commands = []

    def run(*args):
        commands.append(args)
        return SHA

    monkeypatch.setattr(precheck, "run", run)
    precheck.check_release_commit(tag, SHA)
    assert ("git", "rev-parse", "FETCH_HEAD^{commit}") in commands
    assert not any("merge-base" in args for args in commands)
    commands.clear()
    precheck.check_release_commit(TAG, SHA)
    assert ("git", "merge-base", "--is-ancestor", SHA, "refs/remotes/origin/master") in commands


def test_prerelease_rejects_changed_tag(monkeypatch):
    monkeypatch.setattr(precheck, "run", lambda *args: "different")
    with pytest.raises(ValueError, match="tag changed"):
        precheck.check_release_commit("v1.2.0b1", SHA)


@pytest.mark.parametrize("event", ["push", "pull_request", "workflow_dispatch"])
def test_prerelease_requires_latest_ci_for_exact_commit(event):
    good = {
        "event": event,
        "head_branch": "dev/test",
        "head_sha": SHA,
        "status": "completed",
        "conclusion": "success",
        "run_number": 1,
    }
    assert precheck.ci_success([good], SHA, prerelease=True)
    assert not precheck.ci_success([{**good, "head_sha": "other"}], SHA, prerelease=True)
    assert not precheck.ci_success([{**good, "status": "in_progress"}], SHA, prerelease=True)
    with pytest.raises(ValueError, match="latest commit CI failed"):
        precheck.ci_success(
            [good, {**good, "run_attempt": 2, "conclusion": "failure"}], SHA, prerelease=True
        )


@pytest.fixture
def prerelease_request(monkeypatch):
    remote = FakeGitHub(exists=False)
    for name, value in {
        "GITHUB_REPOSITORY": remote.repo,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/dev/preview",
        "GITHUB_REF_NAME": "dev/preview",
        "REQUESTED_TAG": "v1.2.0b1",
        "REQUESTED_CI_EXCEPTION": "",
        "REQUESTED_PRERELEASE": "false",
        "REQUESTED_DRAFT": "false",
    }.items():
        monkeypatch.setenv(name, value)
    state = {"version": "1.2.0b1", "head": SHA, "waited": [], "checked": []}

    def run(*args):
        if args[:2] == ("git", "show"):
            return f'[project]\nversion = "{state["version"]}"'
        return state["head"]

    monkeypatch.setattr(precheck, "GitHub", lambda repo: remote)
    monkeypatch.setattr(precheck, "run", run)
    monkeypatch.setattr(
        precheck, "check_release_commit", lambda *args: state["checked"].append(args)
    )
    monkeypatch.setattr(
        precheck, "wait_for_ci", lambda *args, **kwargs: state["waited"].append(kwargs)
    )
    monkeypatch.setattr(precheck, "output", lambda **values: state.update(values))
    return state


def test_manual_branch_prerelease_requires_ci_by_default(prerelease_request):
    precheck.main()
    assert prerelease_request["prerelease"] == "true"
    assert prerelease_request["channels"] == "false"
    assert prerelease_request["environment"] == "prerelease"
    assert prerelease_request["waited"] == [{"prerelease": True}]


def test_manual_prerelease_exception_is_explicit(prerelease_request, monkeypatch):
    monkeypatch.setenv("REQUESTED_CI_EXCEPTION", "Known navigation failures; testing build.")
    precheck.main()
    assert prerelease_request["ci_exception"] == "Known navigation failures; testing build."
    assert prerelease_request["waited"] == []
    assert prerelease_request["checked"] == [("v1.2.0b1", SHA)]
    assert prerelease_request["channels"] == "false"


def test_stable_flag_cannot_authorize_branch_release(prerelease_request, monkeypatch):
    prerelease_request["version"] = "1.2.0"
    monkeypatch.setenv("REQUESTED_TAG", TAG)
    monkeypatch.setenv("REQUESTED_PRERELEASE", "true")
    with pytest.raises(ValueError, match="stable releases must dispatch from master"):
        precheck.main()


@pytest.mark.parametrize(
    "version,ref,event,exception,error",
    [
        ("1.2.0", "refs/heads/master", "workflow_dispatch", "skip", "CI exceptions require"),
        ("1.2.0b1", "refs/tags/v1.2.0b1", "push", "skip", "CI exceptions require"),
        ("1.2.0b1", "refs/heads/dev/preview", "workflow_dispatch", "one\ntwo", "one line"),
    ],
)
def test_invalid_ci_exception_fails_closed(
    prerelease_request, monkeypatch, version, ref, event, exception, error
):
    prerelease_request["version"] = version
    for name, value in {
        "GITHUB_REF": ref,
        "GITHUB_REF_NAME": f"v{version}",
        "GITHUB_EVENT_NAME": event,
        "REQUESTED_TAG": f"v{version}",
        "REQUESTED_CI_EXCEPTION": exception,
    }.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=error):
        precheck.main()


def test_branch_dispatch_must_match_tag_commit(prerelease_request):
    prerelease_request["head"] = "different"
    with pytest.raises(ValueError, match="tag must match the dispatched commit"):
        precheck.main()


def test_ci_exception_is_disclosed_before_publication_and_on_retry(files):
    remote = FakeGitHub(exists=False)
    publish(
        remote,
        "v1.2.0b1",
        files,
        sha=SHA,
        prerelease=True,
        draft=True,
        ci_exception="Known UI failure.",
    )
    assert "Known UI failure." in remote.body
    assert remote.commands[-2][2] == "--notes-file"
    assert "--latest=false" in remote.commands[-1]
    publish(remote, "v1.2.0b1", files, sha=SHA, prerelease=True, ci_exception="Known UI failure.")
    assert remote.body.count("## Testing status") == 1
    assert not remote.draft


def test_stable_publication_rejects_ci_exception(files):
    remote = FakeGitHub()
    with pytest.raises(ValueError, match="stable releases cannot"):
        publish(remote, TAG, files, sha=SHA, ci_exception="skip")
    assert remote.commands == []


@pytest.mark.parametrize("tag,branch_allowed", [(TAG, False), ("v1.2.0b1", True)])
def test_retry_signature_policy_keeps_stable_restricted(monkeypatch, tag, branch_allowed):
    remote = FakeGitHub(
        draft=False,
        prerelease=branch_allowed,
        assets={name: b"content" for name in inventory.release_files(tag)},
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", remote.repo)
    monkeypatch.setenv("RELEASE_COMMIT_SHA", SHA)
    monkeypatch.setattr(cli, "GitHub", lambda repo: remote)
    monkeypatch.setattr(cli, "check_release_commit", lambda *args: None)
    commands = []
    monkeypatch.setattr(cli, "run", lambda *args: commands.append(args))
    cli.verify_published(tag)
    pattern = commands[0][commands[0].index("--certificate-identity-regexp") + 1]
    prefix = "https://github.com/example/repo/.github/workflows/pyinstaller.yml@refs/"
    assert re.fullmatch(pattern, prefix + "heads/master")
    assert re.fullmatch(pattern, prefix + f"tags/{tag}")
    assert bool(re.fullmatch(pattern, prefix + "heads/dev/preview")) is branch_allowed
    assert not re.fullmatch(pattern, prefix + "tags/v0.0.0")
    assert not re.fullmatch(
        pattern, prefix.replace("example/repo", "attacker/repo") + "heads/dev/preview"
    )
