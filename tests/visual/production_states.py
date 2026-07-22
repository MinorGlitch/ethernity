"""Deterministic real-app states for production TUI screenshots."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from ethernity.app.app_types import ActiveTask, TaskState
from ethernity.app.application import EthernityApp
from ethernity.app.workflow_presenter import is_guided_task
from ethernity.app.workflow_registry import workflow_definition
from ethernity.page_sizes import paper_size_names
from ethernity.tasks.models import TaskExecutionResult, TaskIssue, TaskResultDetail
from ethernity.tasks.settings import SettingsTaskState

VISUAL_CONFIG_PATH = Path("/visual-fixtures/config/ethernity.toml")
VISUAL_ARCHIVE = Path(
    "/visual-fixtures/family-records/long-archive-name-for-responsive-layout-testing"
)
VISUAL_KIT_OUTPUT = Path("/visual-fixtures/outputs/recovery-kit.pdf")
VISUAL_SECRET = "visual-snapshot-secret-must-never-render"
VisualTheme = Literal["ethernity-dark", "ethernity-light"]
VISUAL_DARK_THEME: VisualTheme = "ethernity-dark"


@dataclass(frozen=True, slots=True)
class ProductionSnapshotCase:
    """One workflow state and its expected presentation position."""

    key: str
    task: ActiveTask
    state_updates: dict[str, object]
    active_step: str | None
    expected_ready: bool
    advanced_focus: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewSnapshotCase:
    """A valid workflow state and the decisions that must stay visible in review."""

    key: str
    workflow_case_key: str
    expected_fact_labels: tuple[str, ...]
    expected_fact_values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResultSnapshotCase:
    """One deterministic post-run outcome at an intentionally selected viewport."""

    key: str
    task: ActiveTask
    title: str
    terminal_size: tuple[int, int]
    result: TaskExecutionResult
    error: str | None = None
    error_detail: str | None = None
    recoverable_errors: tuple[TaskIssue, ...] = ()
    reviewed_workflow_case_key: str | None = None
    return_section: str | None = None
    expected_first_view_ids: tuple[str, ...] = ()
    expected_action_ids: tuple[str, ...] = ()


PRODUCTION_SNAPSHOT_CASES: tuple[ProductionSnapshotCase, ...] = (
    ProductionSnapshotCase("backup-empty", "backup", {}, None, False),
    ProductionSnapshotCase(
        "backup-ready",
        "backup",
        {
            "input_paths": [VISUAL_ARCHIVE / "records" / "family-tree.ged"],
            "input_dirs": [VISUAL_ARCHIVE / "photos"],
            "output_dir": VISUAL_ARCHIVE / "backup-8d44f129",
            "recovery_method": "custom_shards",
            "shard_threshold": 3,
            "shard_count": 5,
            "passphrase": VISUAL_SECRET,
            "paper_size": "LETTER",
            "design": "forge",
            "signing_key_mode": "sharded",
            "signing_key_shard_threshold": 2,
            "signing_key_shard_count": 3,
        },
        None,
        True,
    ),
    ProductionSnapshotCase("restore-empty", "restore", {}, "source", False),
    ProductionSnapshotCase(
        "restore-ready",
        "restore",
        {
            "payloads_file": VISUAL_ARCHIVE / "exports" / "recovery-payloads.bin",
            "passphrase": VISUAL_SECRET,
            "output_path": VISUAL_ARCHIVE / "restored-files",
        },
        "destination",
        True,
    ),
    ProductionSnapshotCase("add-files-empty", "add_files", {}, "source", False),
    ProductionSnapshotCase(
        "add-files-ready",
        "add_files",
        {
            "backup_folder": VISUAL_ARCHIVE / "backup-8d44f129",
            "input_dirs": [VISUAL_ARCHIVE / "new-family-photos-and-records"],
            "passphrase": VISUAL_SECRET,
        },
        "output",
        True,
    ),
    ProductionSnapshotCase("rebuild-empty", "rebuild", {}, "source", False),
    ProductionSnapshotCase(
        "rebuild-warning",
        "rebuild",
        {
            "source_paths": [VISUAL_ARCHIVE / "scans" / "latest-recovery-pages.pdf"],
            "passphrase": VISUAL_SECRET,
            "allow_stale_head": True,
            "output_dir": VISUAL_ARCHIVE / "rebuilt-backup",
        },
        "output",
        True,
    ),
    ProductionSnapshotCase(
        "replacement-empty",
        "replace_recovery_docs",
        {},
        "source",
        False,
    ),
    ProductionSnapshotCase(
        "replacement-warning",
        "replace_recovery_docs",
        {
            "payloads_file": VISUAL_ARCHIVE / "exports" / "recovery-payloads.bin",
            "passphrase": VISUAL_SECRET,
            "output_dir": VISUAL_ARCHIVE / "replacement-recovery-sheets",
            "recovery_threshold": 2,
            "recovery_document_count": 4,
        },
        "recovery",
        True,
    ),
    ProductionSnapshotCase(
        "replacement-dense",
        "replace_recovery_docs",
        {
            "payloads_file": VISUAL_ARCHIVE / "exports" / "recovery-payloads.bin",
            "passphrase": VISUAL_SECRET,
            "recovery_documents": [
                VISUAL_ARCHIVE / "current-recovery" / "recovery-sheet-01.pdf",
            ],
            "signing_key_recovery_payload_files": [
                VISUAL_ARCHIVE / "current-recovery" / "signing-key-payloads.bin",
            ],
            "output_dir": VISUAL_ARCHIVE / "replacement-recovery-sheets",
            "recovery_threshold": 3,
            "recovery_document_count": 5,
            "passphrase_replacement_count": 3,
            "signing_key_replacement_count": 2,
        },
        "output",
        True,
        "#workspace-replace-signing-key-select",
    ),
    ProductionSnapshotCase(
        "kit-default",
        "kit",
        {"output_path": VISUAL_KIT_OUTPUT},
        None,
        True,
    ),
    ProductionSnapshotCase(
        "kit-warning",
        "kit",
        {
            "output_path": VISUAL_KIT_OUTPUT,
            "chunk_size": 384,
        },
        None,
        True,
    ),
)


REVIEW_SNAPSHOT_CASES: tuple[ReviewSnapshotCase, ...] = (
    ReviewSnapshotCase(
        "backup-review",
        "backup-ready",
        ("Files", "Recovery", "Signing key", "Layout", "Destination"),
    ),
    ReviewSnapshotCase(
        "restore-review",
        "restore-ready",
        ("Source", "Unlock", "Version", "Signature", "Destination"),
    ),
    ReviewSnapshotCase(
        "add-files-review",
        "add-files-ready",
        ("Backup", "Changes", "Source version", "Unlock", "Recovery sheets", "Destination"),
        ("From settings",),
    ),
    ReviewSnapshotCase(
        "rebuild-review",
        "rebuild-warning",
        ("Source", "Unlock", "Source version", "Layout", "Destination"),
    ),
    ReviewSnapshotCase(
        "replacement-review",
        "replacement-warning",
        (
            "Source",
            "Unlock",
            "Recovery sheets",
            "Signing-key sheets",
            "Layout",
            "Destination",
        ),
    ),
    ReviewSnapshotCase(
        "kit-review",
        "kit-warning",
        ("Kit type", "Layout", "QR sizing", "Destination"),
    ),
)


RESULT_SNAPSHOT_CASES: tuple[ResultSnapshotCase, ...] = (
    ResultSnapshotCase(
        key="restore-success",
        task="restore",
        title="Restore files",
        terminal_size=(120, 32),
        result=TaskExecutionResult(
            ok=True,
            message="Restore completed successfully.",
            output_paths=(
                VISUAL_ARCHIVE / "restored-files" / "photos" / "family-portrait.jpg",
                VISUAL_ARCHIVE / "restored-files" / "records" / "birth-certificate.pdf",
            ),
            next_steps=("Open a few important files and confirm they are readable.",),
        ),
        expected_first_view_ids=("result-outcome", "result-context-actions"),
        expected_action_ids=("result-copy-paths", "result-open-folder", "result-close"),
    ),
    ResultSnapshotCase(
        key="restore-failure",
        task="restore",
        title="Restore files",
        terminal_size=(120, 32),
        result=TaskExecutionResult(
            ok=False,
            message="Restore stopped before every file was written.",
            output_paths=(VISUAL_ARCHIVE / "restored-files" / "partial" / "family-portrait.jpg",),
        ),
        error="Could not finish restoring files.",
        error_detail="PermissionError: visual fixture denied write access to the destination",
        recoverable_errors=(
            TaskIssue(
                code="RESTORE_OUTPUT_NOT_WRITABLE",
                message="Choose a writable destination folder, then review the restore again.",
                section="output",
            ),
        ),
        reviewed_workflow_case_key="restore-ready",
        return_section="output",
        expected_first_view_ids=("result-remediation", "result-context-actions"),
        expected_action_ids=("result-copy-paths", "result-open-folder", "result-return"),
    ),
    ResultSnapshotCase(
        key="backup-success",
        task="backup",
        title="Create backup",
        terminal_size=(160, 48),
        result=TaskExecutionResult(
            ok=True,
            message="Backup and recovery documents were created.",
            output_paths=(
                VISUAL_ARCHIVE / "backup-8d44f129" / "backup-document.pdf",
                VISUAL_ARCHIVE / "backup-8d44f129" / "recovery-sheet-01.pdf",
                VISUAL_ARCHIVE / "backup-8d44f129" / "recovery-sheet-02.pdf",
            ),
            details=(
                TaskResultDetail(
                    key="doc_hash",
                    label="Backup fingerprint",
                    value="a03d5be1c1416b59d15df38aa8762cd8023843e848fa1969e1b5bff62b8f5d4a",
                ),
            ),
        ),
        expected_first_view_ids=("result-outcome", "result-context-actions"),
        expected_action_ids=(
            "result-copy-fingerprint",
            "result-copy-paths",
            "result-open-folder",
            "result-close",
        ),
    ),
    ResultSnapshotCase(
        key="rebuild-partial",
        task="rebuild",
        title="Rebuild backup",
        terminal_size=(80, 24),
        result=TaskExecutionResult(
            ok=False,
            message="Rebuild stopped after creating some documents.",
            output_paths=(VISUAL_ARCHIVE / "rebuilt-backup" / "partial" / "backup-document.pdf",),
        ),
        error="The destination became read-only during the rebuild.",
        error_detail="OSError: visual fixture changed to a read-only destination",
        recoverable_errors=(
            TaskIssue(
                code="REBUILD_OUTPUT_NOT_WRITABLE",
                message="Choose a writable destination and review the rebuild again.",
                section="output",
            ),
        ),
        reviewed_workflow_case_key="rebuild-warning",
        return_section="output",
        expected_first_view_ids=("result-remediation", "result-context-actions"),
        expected_action_ids=("result-copy-paths", "result-open-folder", "result-return"),
    ),
)


def production_case(key: str) -> ProductionSnapshotCase:
    """Return a named production case without duplicating lookup logic in tests."""

    return next(case for case in PRODUCTION_SNAPSHOT_CASES if case.key == key)


def visual_settings_state() -> SettingsTaskState:
    """Build full, host-independent settings values and option catalogs."""

    state = SettingsTaskState(
        config_path=VISUAL_CONFIG_PATH,
        values={},
        options={
            "render_styles": ("sentinel", "forge"),
            "page_sizes": paper_size_names(),
            "qr_error_correction": ("L", "M", "Q", "H"),
            "signing_key_modes": ("embedded", "sharded"),
            "payload_codecs": ("auto", "raw", "gzip"),
            "qr_payload_codecs": ("raw", "base64"),
            "extension_unlock_policies": ("self-contained", "reuse-root-recovery"),
            "extension_signing_key_modes": ("not-stored", "sharded"),
        },
        save_status="Saved",
    )
    state.reset_all()
    return state


class ProductionVisualApp(EthernityApp):
    """Real application shell initialized from one deterministic visual case."""

    CSS_PATH = Path(inspect.getfile(EthernityApp)).with_name("theme.tcss")

    def __init__(
        self,
        case: ProductionSnapshotCase,
        *,
        theme: VisualTheme = VISUAL_DARK_THEME,
    ) -> None:
        self.visual_case = case
        super().__init__(
            settings_state=visual_settings_state(),
        )
        self.theme = theme
        definition = workflow_definition(case.task)
        initial_state = cast(TaskState, getattr(self, definition.state_attribute))
        payload = initial_state.model_dump(mode="python")
        payload.update(case.state_updates)
        state = initial_state.__class__.model_validate(payload)
        setattr(self, definition.state_attribute, state)

    @property
    def visual_state(self) -> TaskState:
        definition = workflow_definition(self.visual_case.task)
        return cast(TaskState, getattr(self, definition.state_attribute))

    def on_mount(self) -> None:
        super().on_mount()
        case = self.visual_case
        if case.active_step is not None:
            ui_state = self.workflow_ui_states[case.task]
            ui_state.activate(case.active_step)
        self._show_task(case.task)
        if is_guided_task(case.task):
            self.call_after_refresh(self._focus_guided_active_step)
        else:
            self.call_after_refresh(self._focus_active_task, case.task)


class SettingsVisualApp(EthernityApp):
    """Real settings workspace with deterministic values and theme."""

    CSS_PATH = Path(inspect.getfile(EthernityApp)).with_name("theme.tcss")

    def __init__(self, *, theme: VisualTheme = VISUAL_DARK_THEME) -> None:
        super().__init__(settings_state=visual_settings_state())
        self.theme = theme

    def on_mount(self) -> None:
        super().on_mount()
        self._show_task("settings")
        self.call_after_refresh(self._focus_active_task, "settings")
