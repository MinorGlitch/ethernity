from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from random import Random

import pytest
from pypdf import PdfReader

from ethernity.app.backup_estimate_controller import BackupEstimateController
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.backup_estimate import BackupEstimate, estimate_backup
from ethernity.workflows.execution import BackupRequest


def test_backup_estimate_counts_nested_files_and_uses_compression_without_encryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = tmp_path / "records" / "year"
    nested.mkdir(parents=True)
    (nested / "a.txt").write_bytes(b"a" * 5000)
    (nested / "b.txt").write_bytes(b"b" * 4000)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Print estimation must not encrypt, generate secrets, or write PDFs")

    monkeypatch.setattr("ethernity.crypto.age_runtime._encrypt_with_pyrage", forbidden)
    monkeypatch.setattr("ethernity.crypto.signing.generate_signing_keypair", forbidden)
    monkeypatch.setattr("ethernity.render.direct_pdf.surface.FpdfSurface.output", forbidden)
    state = BackupTaskState(input_dirs=[tmp_path / "records"])
    request = state.estimate_request()
    assert request is not None

    estimate = estimate_backup(request)

    assert estimate.file_count == 2
    assert estimate.input_bytes == 9000
    assert estimate.document_bytes < estimate.input_bytes
    assert estimate.backup_pages == 1
    assert estimate.qr_count == 2
    assert sorted(path.name for path in nested.iterdir()) == ["a.txt", "b.txt"]


def test_print_choices_change_estimated_pagination_and_execution_request(tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(Random(17).randbytes(6000))
    state = BackupTaskState(input_paths=[path], qr_chunk_size=256)
    sentinel_request = state.estimate_request()
    assert sentinel_request is not None
    sentinel = estimate_backup(sentinel_request)
    state.design = "maritime"
    state.paper_size = "LETTER"
    maritime_request = state.estimate_request()
    assert maritime_request is not None
    maritime = estimate_backup(maritime_request)

    assert sentinel.qr_count == maritime.qr_count
    assert sentinel.backup_pages != maritime.backup_pages
    assert state.to_backup_request().design == "maritime"
    assert state.to_backup_request().paper_size == "LETTER"


def test_estimate_cache_ignores_recovery_secrets_and_rejects_stale_print_settings() -> None:
    state = BackupTaskState(input_paths=[Path("note.txt")], passphrase="secret")
    request = state.estimate_request()
    assert request is not None
    assert request.passphrase is None
    estimate = BackupEstimate(1, 32, 240, 1, 2)
    assert state.store_estimate(request, estimate)
    state.output_dir = Path("elsewhere")
    state.passphrase = "new secret"
    state.recovery_method = "custom_shards"
    state.shard_count = 5
    assert state.current_estimate() == estimate

    state.paper_size = "LETTER"
    assert state.current_estimate() is None
    assert not state.store_estimate(request, estimate)


def test_estimate_matches_generated_main_pages_and_result_reports_final_counts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "records.bin"
    path.write_bytes(Random(37).randbytes(6000))
    state = BackupTaskState(
        input_paths=[path],
        output_dir=tmp_path / "documents",
        recovery_method="single_phrase",
        passphrase="fixture recovery passphrase",
        design="maritime",
        paper_size="LETTER",
        qr_chunk_size=256,
    )
    request = state.estimate_request()
    assert request is not None
    estimate = estimate_backup(request)

    result = state.execute()

    page_counts = {path: len(PdfReader(path).pages) for path in result.output_paths}
    main_path = next(path for path in result.output_paths if path.name == "qr_document.pdf")
    details = {detail.key: detail.value for detail in result.details}
    assert page_counts[main_path] == estimate.backup_pages == details["backup_pages"]
    assert details["printed_pages"] == sum(page_counts.values())
    assert details["documents"] == len(result.output_paths)


class _EstimateHost:
    active_task = "backup"
    is_running = True

    def __init__(self) -> None:
        self.backup_state = BackupTaskState(input_paths=[Path("first.txt")])
        self.tasks: list[asyncio.Task[None]] = []
        self.refreshes = 0
        self.controller = BackupEstimateController(self)

    def run_worker(self, work, **kwargs: object) -> None:
        self.tasks.append(asyncio.create_task(work))

    def refresh_task_view(self) -> None:
        self.refreshes += 1
        self.controller.refresh()


def test_estimate_controller_coalesces_edits_and_keeps_stale_results_out_of_ui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[BackupRequest] = []

    def fake_estimate(request: BackupRequest) -> BackupEstimate:
        calls.append(request)
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
        return BackupEstimate(1, 10 * len(calls), 200, 1, 2)

    monkeypatch.setattr("ethernity.app.backup_estimate_controller.estimate_backup", fake_estimate)

    async def run() -> None:
        host = _EstimateHost()
        host.controller.refresh()
        try:
            assert await asyncio.to_thread(started.wait, 3)
            host.backup_state.input_paths = [Path("second.txt")]
            host.controller.refresh()
            host.backup_state.input_paths = [Path("third.txt")]
            host.controller.refresh()
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(*host.tasks), 3)

        assert [request.input_paths for request in calls] == [
            (Path("first.txt"),),
            (Path("third.txt"),),
        ]
        assert host.refreshes == 1
        assert host.backup_state.current_estimate() == BackupEstimate(1, 20, 200, 1, 2)
        host.controller.refresh()
        assert len(host.tasks) == 1

    asyncio.run(run())


def test_estimate_controller_reports_read_errors_without_repeating_failed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_estimate(request: BackupRequest) -> BackupEstimate:
        nonlocal calls
        calls += 1
        raise OSError("The selected file is unreadable")

    monkeypatch.setattr("ethernity.app.backup_estimate_controller.estimate_backup", fake_estimate)

    async def run() -> None:
        host = _EstimateHost()
        host.controller.refresh()
        await asyncio.wait_for(asyncio.gather(*host.tasks), 3)
        assert host.backup_state.estimate_error() == "The selected file is unreadable"
        assert host.backup_state.current_estimate() is None
        host.controller.refresh()
        assert calls == 1
        assert host.refreshes == 1

    asyncio.run(run())


def test_estimate_controller_does_not_refresh_during_app_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def fake_estimate(request: BackupRequest) -> BackupEstimate:
        started.set()
        assert release.wait(3)
        return BackupEstimate(1, 10, 200, 1, 2)

    monkeypatch.setattr("ethernity.app.backup_estimate_controller.estimate_backup", fake_estimate)

    async def run() -> None:
        host = _EstimateHost()
        host.controller.refresh()
        try:
            assert await asyncio.to_thread(started.wait, 3)
            host.is_running = False
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(*host.tasks), 3)

        assert host.refreshes == 0
        assert host.backup_state.current_estimate() is None

    asyncio.run(run())
