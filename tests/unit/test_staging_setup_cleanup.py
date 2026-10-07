"""Staging ownership begins before render and debug setup can fail."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ethernity.config import AppConfig
from ethernity.core.models import DocumentPlan
from ethernity.crypto.signing import derive_public_key
from ethernity.qr.codec import QrConfig
from ethernity.render.types import DocumentOrigin
from ethernity.workflows.backup import execution as backup
from ethernity.workflows.replacement_recovery import service as replacement
from ethernity.workflows.shared.execution_control import OperationCancelled
from ethernity.workflows.shared.operation_types import InputFile
from ethernity.workflows.shared.requests import ReplacementRecoveryRequest


def _create_backup(parent: Path, config: AppConfig, debug_dir: Path | None = None):
    return backup.run_backup(
        input_files=[InputFile(None, "sample.txt", b"sample", 0)],
        base_dir=None,
        output_dir=parent,
        layout_debug_dir=debug_dir,
        plan=DocumentPlan(sealed=False),
        passphrase="test passphrase",
        config=config,
        render_origin=DocumentOrigin(kind="root_backup"),
        quiet=True,
    )


@pytest.fixture
def backup_config(monkeypatch):
    monkeypatch.setattr(
        backup, "_encrypt_backup_inputs", lambda *_args: (b"ciphertext", "test passphrase")
    )
    return AppConfig(
        design_name="sentinel", paper_size="A4", qr_config=QrConfig(), qr_chunk_size=1024
    )


@pytest.fixture(params=["backup", "replacement"])
def staged_workflow(request, tmp_path, monkeypatch, backup_config):
    parent = tmp_path / "outputs"
    parent.mkdir()
    (parent / "keep.txt").write_text("unrelated output")
    debug_file = tmp_path / "debug-file"
    debug_file.write_text("existing debug file")
    if request.param == "backup":
        module = backup

        def run(debug_dir=None):
            return _create_backup(parent, backup_config, debug_dir)
    else:
        module = replacement
        seed = b"s" * 32
        plan = SimpleNamespace(
            doc_id=b"d" * 8,
            doc_hash=b"h" * 32,
            passphrase="test passphrase",
            auth_payload=SimpleNamespace(sign_pub=derive_public_key(seed)),
        )
        monkeypatch.setattr(
            replacement,
            "_recover_replacement_chain",
            Mock(return_value=SimpleNamespace(manifest=SimpleNamespace(signing_seed=seed))),
        )

        def run(debug_dir=None):
            return replacement._replacement_from_plan(
                plan=plan,
                config=backup_config,
                args=ReplacementRecoveryRequest(
                    output_dir=parent / "replacement",
                    layout_debug_dir=debug_dir,
                    shard_threshold=2,
                    shard_count=3,
                    create_signing_key_shards=False,
                ),
                passphrase_shard_frames=[],
                signing_key_frames=[],
                debug=False,
            )

    return SimpleNamespace(run=run, module=module, parent=parent, debug_file=debug_file)


def _assert_clean(workflow) -> None:
    assert list(workflow.parent.iterdir()) == [workflow.parent / "keep.txt"]
    assert (workflow.parent / "keep.txt").read_text() == "unrelated output"
    assert workflow.debug_file.read_text() == "existing debug file"


def test_invalid_debug_destination_removes_staging(staged_workflow) -> None:
    with pytest.raises(ValueError, match="layout debug directory must be a directory"):
        staged_workflow.run(staged_workflow.debug_file)
    _assert_clean(staged_workflow)


@pytest.mark.parametrize("error", [RuntimeError("render setup failed"), OperationCancelled()])
def test_renderer_setup_failure_removes_staged_content(staged_workflow, monkeypatch, error) -> None:
    def fail_setup(*_args, **_kwargs):
        (stage,) = staged_workflow.parent.glob(".staging-*")
        (stage / "partial.pdf").write_bytes(b"partial document")
        raise error

    monkeypatch.setattr(staged_workflow.module, "RenderService", fail_setup)
    with pytest.raises(type(error)) as caught:
        staged_workflow.run()
    assert caught.value is error
    _assert_clean(staged_workflow)


@pytest.mark.parametrize("method", ["build_qr_payloads", "qr_inputs", "recovery_inputs"])
def test_backup_input_setup_failure_removes_staging(
    tmp_path, monkeypatch, method, backup_config
) -> None:
    error = RuntimeError(f"{method} failed")
    monkeypatch.setattr(backup.RenderService, method, Mock(side_effect=error))
    parent = tmp_path / "outputs"
    with pytest.raises(RuntimeError) as caught:
        _create_backup(parent, backup_config)
    assert caught.value is error
    assert list(parent.iterdir()) == []
