from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from textual.worker import WorkerState

from ethernity.app.app_types import ActiveTask, TaskState
from ethernity.config import get_api_config_snapshot, resolve_config_snapshot_path
from ethernity.page_sizes import paper_size_display_name
from ethernity.render.recovery_kit_index import supports_recovery_kit_index_style
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import (
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskPreview,
    TaskValidation,
)
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.recovery_resources import RecoveryResourceRetry, recovery_resource_retry
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState


@dataclass(frozen=True, slots=True)
class ReviewDetail:
    """One label and value shown in the task review."""

    label: str
    value: str
    section: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewedConfig:
    """Exact validated config contents approved during final review."""

    source_path: Path
    contents: bytes = field(repr=False)

    @classmethod
    def capture(cls, path: Path | None) -> ReviewedConfig:
        source_path = resolve_config_snapshot_path(path)
        contents = source_path.read_bytes()
        with _temporary_config(
            contents,
            prefix="ethernity-config-validation-",
        ) as validation_path:
            snapshot = get_api_config_snapshot(validation_path)
            if snapshot.status != "valid":
                raise ValueError(f"Ethernity could not load the configuration ({snapshot.status}).")
        return cls(source_path=source_path, contents=contents)

    @contextmanager
    def temporary_path(self) -> Iterator[Path]:
        """Expose the captured bytes at a private path for path-based task APIs."""

        with _temporary_config(
            self.contents,
            prefix="ethernity-reviewed-config-",
        ) as config_path:
            yield config_path


@dataclass(frozen=True, slots=True)
class ReviewedTask:
    """The exact task state and plan approved for one execution attempt."""

    task: ActiveTask
    state_snapshot: TaskState = field(repr=False)
    validation: TaskValidation = field(repr=False)
    preview: TaskPreview = field(repr=False)
    plan: TaskExecutionPlan = field(repr=False)
    review_details: tuple[ReviewDetail, ...] = field(repr=False)
    reviewed_config: ReviewedConfig = field(repr=False)

    @classmethod
    def capture(cls, task: ActiveTask, state: TaskState) -> ReviewedTask:
        snapshot = state.model_copy(deep=True)
        reviewed_config = ReviewedConfig.capture(snapshot.config_path)
        with reviewed_config.temporary_path() as config_path:
            snapshot.config_path = config_path
            prepare_review = getattr(snapshot, "prepare_review", None)
            if callable(prepare_review):
                prepare_review()
            validation = snapshot.validate_task()
            preview = snapshot.preview()
            plan = snapshot.execution_plan()
        snapshot.config_path = reviewed_config.source_path
        review_details = build_review_details(task, snapshot, plan)
        return cls(
            task=task,
            state_snapshot=snapshot,
            validation=validation,
            preview=preview,
            plan=plan,
            review_details=review_details,
            reviewed_config=reviewed_config,
        )

    def execution_state(self) -> TaskState:
        """Return an isolated copy so retries preserve the reviewed snapshot."""

        return self.state_snapshot.model_copy(deep=True)

    def retry_with_higher_limits(self) -> ReviewedTask:
        """Raise limits only on a fresh copy of the failed restore's reviewed state."""

        state = self.execution_state()
        if (
            self.task != "restore"
            or not isinstance(state, RestoreTaskState)
            or state.resource_intensive_compatibility_recovery
        ):
            raise ValueError("higher limits are only available for a normal restore attempt")
        state.resource_intensive_compatibility_recovery = True
        return replace(self, state_snapshot=state)

    def execute(self) -> TaskExecutionResult:
        """Execute with the reviewed state and config, never their live counterparts."""

        state = self.execution_state()
        with self.reviewed_config.temporary_path() as config_path:
            state.config_path = config_path
            return state.execute()


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """A worker terminal state normalized for result presentation."""

    result: TaskExecutionResult
    error_message: str | None = None
    error_detail: str | None = None
    allow_retry: bool = True
    resource_retry: RecoveryResourceRetry | None = None


def build_review_details(
    task: ActiveTask,
    state: TaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    """Build concise task decisions without parsing preview or validation copy."""

    if task == "backup" and isinstance(state, BackupTaskState):
        return _backup_review_details(state, plan)
    if task == "restore" and isinstance(state, RestoreTaskState):
        return _restore_review_details(state, plan)
    if task == "add_files" and isinstance(state, AddFilesTaskState):
        return _add_files_review_details(state, plan)
    if task == "rebuild" and isinstance(state, RebuildTaskState):
        return _rebuild_review_details(state, plan)
    if task == "replace_recovery_docs" and isinstance(state, ReplaceRecoveryDocsTaskState):
        return _replacement_review_details(state, plan)
    if task == "kit" and isinstance(state, PrintKitTaskState):
        return _kit_review_details(state, plan)
    return ()


def infer_execution_failure_section(
    task: ActiveTask,
    outcome: ExecutionOutcome,
) -> str | None:
    """Map recognizable runtime failures back to a useful workflow section."""

    text = " ".join(
        part
        for part in (
            outcome.error_message,
            outcome.error_detail,
            outcome.result.message,
        )
        if part
    ).lower()
    if not text:
        return None

    if any(
        phrase in text
        for phrase in (
            "not writable",
            "permission denied",
            "read-only",
            "read only",
            "no space",
            "disk full",
            "output path",
            "output folder",
            "destination",
            "failed to write",
            "could not write",
            "writing file",
        )
    ):
        return "output"
    if any(phrase in text for phrase in ("passphrase", "decrypt", "unlock")):
        return "unlock"
    if any(phrase in text for phrase in ("signature", "authentication", "trust source")):
        return {
            "restore": "authentication",
            "replace_recovery_docs": "signature",
        }.get(task, "advanced")
    if any(
        phrase in text
        for phrase in (
            "scanned page",
            "scan input",
            "recovery text",
            "payload file",
            "backup source",
            "source documents",
        )
    ):
        return "source"
    return None


def _backup_review_details(
    state: BackupTaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    file_count = len(state.input_paths)
    folder_count = len(state.input_dirs)
    selected = _counted_items(file_count, "file", folder_count, "folder")
    recovery = (
        "One recovery phrase"
        if state.recovery_method == "single_phrase"
        else (
            "3 sheets, 2 needed to restore"
            if state.recovery_method == "recommended_shards"
            else f"{state.shard_count} sheets, {state.shard_threshold} needed to restore"
        )
    )
    signing = (
        "Encrypted in the backup documents"
        if state.signing_key_mode == "embedded"
        else "Stored on separate recovery sheets"
        if state.signing_key_mode == "sharded"
        else "Follows saved signing-key policy"
    )
    estimate = state.current_estimate()
    if estimate is not None and folder_count:
        selected = f"{_counted(estimate.file_count, 'file')} from {selected}"
    print_estimate = (
        (
            ReviewDetail(
                "Backup pages", f"About {_counted(estimate.backup_pages, 'page')} in the main PDF"
            ),
        )
        if estimate is not None
        else ()
    )
    return (
        ReviewDetail("Files", selected, "files"),
        ReviewDetail("Documents", _backup_document_summary(state)),
        *print_estimate,
        ReviewDetail("Recovery", recovery, "recovery"),
        ReviewDetail("Signing key", signing, "signature"),
        ReviewDetail("Layout", _layout_summary(state.paper_size, state.design), "layout"),
        ReviewDetail(
            "Destination",
            (
                "Automatic folder named for backup ID"
                if state.output_dir is None
                else _destination_summary(plan)
            ),
            "output",
        ),
    )


def _restore_review_details(
    state: RestoreTaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    source_request = state.source_assessment_request()
    if source_request is not None and source_request.source_kind == "recovery_inputs":
        source = "Mixed backup documents"
    elif state.source_paths:
        source = _counted(len(state.source_paths), "document input")
    elif state.recovery_text:
        source = "Pasted recovery text"
    elif state.recovery_text_file is not None:
        source = "Recovery text file"
    else:
        source = "Backup payload file"

    if state.target == "original":
        target = "Initial backup only"
    elif state.target == "specific_update":
        target = (
            f"Update {state.extension_index}"
            if state.extension_index is not None
            else "Specific fingerprint"
        )
    else:
        target = "Newest loaded version"

    signature = (
        "Unsigned legacy backups allowed" if state.allow_unsigned else "Trusted signature required"
    )
    return (
        ReviewDetail("Source", source, "source"),
        ReviewDetail("Files", "All files in the selected backup version"),
        ReviewDetail("Unlock", _unlock_summary(state), "unlock"),
        ReviewDetail("Version", target, "target"),
        ReviewDetail("Signature", signature, "authentication"),
        ReviewDetail("Destination", _destination_summary(plan), "output"),
    )


def _add_files_review_details(
    state: AddFilesTaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    source_request = state.source_assessment_request()
    if source_request is not None and source_request.source_kind == "recovery_inputs":
        source = "Mixed backup documents"
    elif state.source_paths:
        source = _counted(len(state.source_paths), "document input")
    elif state.recovery_text:
        source = "Pasted recovery text"
    elif state.recovery_text_file is not None:
        source = "Recovery text file"
    else:
        source = "Backup payload file"
    changes = (
        f"{_counted_items(len(state.input_paths), 'file', len(state.input_dirs), 'folder')}, "
        "replacing matching paths"
    )
    source_version = (
        "Will check trusted fingerprint"
        if state.expected_head_doc_hash is not None
        else "Newest loaded version accepted"
    )

    return (
        ReviewDetail("Backup", source, "source"),
        ReviewDetail("Changes", changes, "files"),
        ReviewDetail("Documents", "Update PDF and recovery guide"),
        ReviewDetail("Source version", source_version, "freshness"),
        ReviewDetail("Unlock", _unlock_summary(state), "unlock"),
        ReviewDetail("Recovery sheets", state.recovery_sheet_summary(), "recovery"),
        ReviewDetail("Destination", _destination_summary(plan), "output"),
    )


def _rebuild_review_details(
    state: RebuildTaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    source = (
        "Existing backup folder"
        if state.backup_folder is not None
        else _counted(len(state.source_paths), "document input")
    )
    if state.expected_head_doc_hash is not None:
        source_version = "Will check trusted fingerprint"
    else:
        source_version = "Latest loaded version accepted"
    return (
        ReviewDetail("Source", source, "source"),
        ReviewDetail("Documents", "Backup PDF and recovery guide"),
        ReviewDetail("Recovery sheets", "Follow the loaded backup's sheet policy"),
        ReviewDetail("Unlock", _unlock_summary(state), "unlock"),
        ReviewDetail("Source version", source_version, "freshness"),
        ReviewDetail("Layout", _layout_summary(state.paper_size, state.design), "layout"),
        ReviewDetail("Destination", _destination_summary(plan), "output"),
    )


def _replacement_review_details(
    state: ReplaceRecoveryDocsTaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    source_request = state.source_assessment_request()
    if source_request is not None and source_request.source_kind == "recovery_inputs":
        source = "Mixed backup documents"
    elif state.source_paths:
        source = _counted(len(state.source_paths), "document input")
    elif state.recovery_text:
        source = "Pasted recovery text"
    elif state.recovery_text_file is not None:
        source = "Recovery text file"
    else:
        source = "Backup payload file"

    recovery = (
        f"{state.recovery_document_count} new sheets ({state.recovery_threshold} needed to restore)"
    )
    if not state.create_passphrase_recovery:
        passphrase = "without passphrase sheets"
    elif state.passphrase_replacement_count is not None:
        passphrase = f"replacing {state.passphrase_replacement_count} passphrase sheets"
    else:
        passphrase = "with passphrase sheets"

    if not state._creates_signing_key_recovery():
        signing = "None"
    elif state.signing_key_replacement_count is not None:
        signing = f"Replace {state.signing_key_replacement_count} sheets"
    else:
        threshold = state.signing_key_recovery_threshold or state.recovery_threshold
        count = state.signing_key_recovery_count or state.recovery_document_count
        signing = f"{count} new sheets ({threshold} required)"
    return (
        ReviewDetail("Source", source, "source"),
        ReviewDetail("Unlock", _unlock_summary(state), "unlock"),
        ReviewDetail("Recovery sheets", f"{recovery}, {passphrase}", "recovery"),
        ReviewDetail("Signing-key sheets", signing, "signature"),
        ReviewDetail("Layout", _layout_summary(state.paper_size, state.design), "layout"),
        ReviewDetail("Destination", _destination_summary(plan), "output"),
    )


def _kit_review_details(
    state: PrintKitTaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    kit_type = "Scanner kit" if state.variant == "scanner" else "Lean offline kit"
    qr_sizing = "Automatic" if state.chunk_size is None else f"{state.chunk_size}-byte chunks"
    return (
        ReviewDetail("Documents", "1 rescue kit PDF"),
        ReviewDetail("Kit type", kit_type, "variant"),
        ReviewDetail("Layout", _layout_summary(state.paper_size, state.design), "layout"),
        ReviewDetail("QR sizing", qr_sizing, "qr"),
        ReviewDetail("Destination", _destination_summary(plan), "output"),
    )


def _unlock_summary(
    state: RestoreTaskState | AddFilesTaskState | RebuildTaskState | ReplaceRecoveryDocsTaskState,
) -> str:
    if state.passphrase:
        return "Passphrase"
    if state.recovery_documents:
        return _counted(len(state.recovery_documents), "recovery sheet")
    if state.recovery_payload_files:
        return _counted(len(state.recovery_payload_files), "recovery payload file")
    return "Not selected"


def _destination_summary(plan: TaskExecutionPlan) -> str:
    if not plan.writes_files:
        return "No files will be written"
    if not plan.output_paths:
        return "No destination"
    return "\n".join(str(path.expanduser().absolute()) for path in plan.output_paths)


def _backup_document_summary(state: BackupTaskState) -> str:
    documents = ["Backup PDF", "recovery guide"]
    request = state.to_backup_request()
    if request.shard_count is not None:
        documents.append(_counted(request.shard_count, "recovery sheet"))
        if request.signing_key_mode == "sharded":
            count = request.signing_key_shard_count or request.shard_count
            documents.append(_counted(count, "signing-key recovery sheet"))
    if supports_recovery_kit_index_style(state.design):
        documents.append("document inventory PDF")
    return ", ".join(documents)


def _layout_summary(paper_size: str, design: str) -> str:
    return f"{paper_size_display_name(paper_size)}, {design.title()}"


def _counted(count: int, singular: str) -> str:
    return f"{count} {singular if count == 1 else f'{singular}s'}"


def _counted_items(
    first_count: int,
    first_singular: str,
    second_count: int,
    second_singular: str,
) -> str:
    parts = []
    if first_count:
        parts.append(_counted(first_count, first_singular))
    if second_count:
        parts.append(_counted(second_count, second_singular))
    return " and ".join(parts) if parts else "Nothing selected"


def normalize_execution_outcome(
    state: WorkerState,
    *,
    value: object = None,
    error: BaseException | None = None,
) -> ExecutionOutcome:
    """Convert every worker terminal state into one result-screen value."""

    if state == WorkerState.SUCCESS:
        if isinstance(value, TaskExecutionResult):
            return ExecutionOutcome(result=value)
        actual_type = type(value).__qualname__
        return ExecutionOutcome(
            result=TaskExecutionResult(
                status="failed",
                message="Ethernity received an invalid task result.",
            ),
            error_detail=f"Expected TaskExecutionResult, got {actual_type}.",
        )

    if state == WorkerState.ERROR:
        if error is None:
            return ExecutionOutcome(
                result=TaskExecutionResult(status="failed", message="The task failed."),
                error_message="The task stopped without an error message.",
                error_detail="The execution worker exited without an exception.",
            )
        resource_retry = recovery_resource_retry(error)
        message = (
            "This backup exceeds the normal recovery work limit."
            if resource_retry is not None
            else str(error).strip() or "The task failed without an error message."
        )
        return ExecutionOutcome(
            result=TaskExecutionResult(status="failed", message="The task failed."),
            error_message=message,
            error_detail=f"{type(error).__qualname__}: {error}",
            resource_retry=resource_retry,
        )

    if state == WorkerState.CANCELLED:
        return ExecutionOutcome(
            result=TaskExecutionResult(
                status="failed",
                message="The write was cancelled before completion.",
            ),
            error_detail=(
                "The write thread has stopped. Check the destination before starting another write."
            ),
            allow_retry=False,
        )

    raise ValueError(f"Worker state {state!s} is not terminal.")


@contextmanager
def _temporary_config(contents: bytes, *, prefix: str) -> Iterator[Path]:
    with TemporaryDirectory(prefix=prefix) as directory:
        config_path = Path(directory) / "config.toml"
        config_path.write_bytes(contents)
        yield config_path
