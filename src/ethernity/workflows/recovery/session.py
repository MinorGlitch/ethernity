"""Recovery input snapshots owned by one editing or execution session."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ethernity.core.execution_control import cancellation_point
from ethernity.crypto.signing import AuthPayload
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions import recovery as chain_recovery
from ethernity.workflows.recovery import inputs, root_selection
from ethernity.workflows.recovery.models import RecoveryInspection
from ethernity.workflows.recovery.source_state import LoadedRecoveryInputs, LoadedRecoverySource
from ethernity.workflows.shared.requests import RecoveryRequest
from ethernity.workflows.shared.source_files import source_files_version


def _path(value: str | Path | None) -> str | None:
    return str(Path(value).expanduser()) if value is not None else None


@dataclass(frozen=True)
class _SourceSelection:
    frames: tuple[Frame, ...]
    fallback_file: str | None
    payloads_file: str | None
    scans: tuple[str, ...]
    auth_frames: tuple[Frame, ...]
    auth_text_file: str | None
    auth_payloads_file: str | None
    allow_unsigned: bool
    files_version: str

    @classmethod
    def capture(cls, request: RecoveryRequest) -> _SourceSelection:
        scans = tuple(str(Path(path).expanduser()) for path in request.scan_paths)
        return cls(
            tuple(request.frames),
            _path(request.recovery_text_file),
            _path(request.payloads_file),
            scans,
            tuple(request.auth_frames),
            _path(request.auth_text_file),
            _path(request.auth_payloads_file),
            request.allow_unsigned,
            source_files_version(
                (
                    request.recovery_text_file,
                    request.payloads_file,
                    *scans,
                    request.auth_text_file,
                    request.auth_payloads_file,
                )
            ),
        )


@dataclass(frozen=True)
class _LoadedSource:
    selection: _SourceSelection
    source: LoadedRecoverySource


@dataclass(frozen=True)
class _ShardSelection:
    frames: tuple[Frame, ...]
    text_files: tuple[str, ...]
    payload_files: tuple[str, ...]
    scans: tuple[str, ...]
    files_version: str

    @classmethod
    def capture(cls, request: RecoveryRequest) -> _ShardSelection:
        text = tuple(str(Path(p).expanduser()) for p in request.shard_text_files)
        payloads = tuple(str(Path(p).expanduser()) for p in request.shard_payload_files)
        scans = tuple(str(Path(p).expanduser()) for p in request.shard_scan_paths)
        return cls(
            tuple(request.shard_frames),
            text,
            payloads,
            scans,
            source_files_version((*text, *payloads, *scans)),
        )


@dataclass(frozen=True)
class _PreparedInputs:
    loaded: LoadedRecoveryInputs
    passphrase: str | None
    allow_unsigned: bool
    inspection: RecoveryInspection


@dataclass(frozen=True)
class _ChainSelection:
    ciphertext: bytes
    doc_id: bytes
    doc_hash: bytes
    passphrase: str
    auth_payload: AuthPayload | None
    auth_status: str
    allow_unsigned: bool
    documents: tuple[chain_recovery.ImportedRecoveryDocument, ...]
    extension_index: int | None
    extension_doc_hash: str | None
    expected_head_doc_hash: str | None

    @classmethod
    def capture(cls, plan: chain_recovery.ChainRecoveryInputs) -> _ChainSelection:
        return cls(
            plan.ciphertext,
            plan.doc_id,
            plan.doc_hash,
            plan.passphrase,
            plan.auth_payload,
            plan.auth_status,
            plan.allow_unsigned,
            plan.import_documents,
            plan.extension_index,
            plan.extension_doc_hash,
            plan.expected_head_doc_hash,
        )


@dataclass
class RecoverySession:
    """Retain input work across compatible tasks without a process-wide cache.

    Source changes replace the snapshot. Output settings and credentials do not
    change carrier decoding; their own checks run after loading this snapshot.
    """

    _loaded: _LoadedSource | None = field(default=None, repr=False)
    _shards: tuple[_ShardSelection, LoadedRecoveryInputs] | None = field(default=None, repr=False)
    _prepared: _PreparedInputs | None = field(default=None, repr=False)
    _recovered: tuple[_ChainSelection, chain_recovery.ChainRecoveryResult] | None = field(
        default=None, repr=False
    )

    def load_source(self, request: RecoveryRequest) -> LoadedRecoverySource:
        cancellation_point()
        selection = _SourceSelection.capture(request)
        previous = self._loaded
        if previous is not None and previous.selection == selection:
            return previous.source
        self._prepared = None
        self._recovered = None
        frames, label, detail = inputs.load_recovery_frames(
            request,
            allow_unsigned=request.allow_unsigned,
            quiet=request.quiet,
            include_recovery_sheets=True,
        )
        auth = inputs.load_extra_auth_frames(
            request, allow_unsigned=request.allow_unsigned, quiet=request.quiet
        )
        recovery_frames = [frame for frame in frames if frame.frame_type != FrameType.KEY_DOCUMENT]
        documents = root_selection.import_recovery_documents(
            recovery_frames, auth, source_label=detail or label or "content import"
        )
        cancellation_point()
        if _SourceSelection.capture(request) != selection:
            raise ValueError("Backup sources changed while they were being read. Load them again.")
        source = LoadedRecoverySource(tuple(frames), tuple(auth), documents, label, detail)
        self._loaded = _LoadedSource(selection, source)
        self._shards = None
        self._prepared = None
        self._recovered = None
        return source

    def load(self, request: RecoveryRequest) -> LoadedRecoveryInputs:
        source = self.load_source(request)
        selection = _ShardSelection.capture(request)
        previous = self._shards
        if previous is not None and previous[0] == selection and previous[1].source == source:
            return previous[1]
        shards, fallback_files, payload_files, scans = inputs.load_shard_frames(
            request, quiet=request.quiet
        )
        cancellation_point()
        if _ShardSelection.capture(request) != selection:
            raise ValueError("Recovery sheets changed while they were being read. Load them again.")
        loaded = LoadedRecoveryInputs(
            source, tuple(shards), tuple(fallback_files), tuple(payload_files), tuple(scans)
        )
        self._shards = (selection, loaded)
        return loaded

    def prepared(
        self, loaded: LoadedRecoveryInputs, request: RecoveryRequest, *, strict: bool
    ) -> RecoveryInspection | None:
        cancellation_point()
        previous = self._prepared
        if previous is None or (
            previous.loaded != loaded
            or previous.passphrase != request.passphrase
            or previous.allow_unsigned != request.allow_unsigned
        ):
            self._recovered = None
            return None
        result = previous.inspection
        # Failed best-effort inspections are not substitutes for strict validation.
        if strict and (result.blocking_issues or not result.unlock.satisfied):
            return None
        return result

    def remember_preparation(
        self, loaded: LoadedRecoveryInputs, request: RecoveryRequest, result: RecoveryInspection
    ) -> None:
        cancellation_point()
        self._prepared = _PreparedInputs(loaded, request.passphrase, request.allow_unsigned, result)

    def authenticated_document(
        self, source: LoadedRecoverySource, doc_hash: bytes, *, allow_unsigned: bool
    ) -> RecoveryInspection | None:
        previous = self._prepared
        if (
            previous is not None
            and previous.loaded.source == source
            and previous.allow_unsigned == allow_unsigned
            and previous.inspection.doc_hash == doc_hash
            and previous.inspection.auth_status == "verified"
            and previous.inspection.auth_payload is not None
        ):
            return previous.inspection
        return None

    def recover_chain(
        self, plan: chain_recovery.ChainRecoveryInputs, *, debug: bool = False
    ) -> chain_recovery.ChainRecoveryResult:
        """Reuse a completed replay only for the same verified inputs and selected head."""
        cancellation_point()
        selection = _ChainSelection.capture(plan)
        previous = self._recovered
        if not debug and previous is not None and previous[0] == selection:
            return previous[1]
        self._recovered = None
        result = chain_recovery.recover_chain_entries(plan, debug=debug)
        cancellation_point()
        self._recovered = (selection, result)
        return result
