# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from ethernity.config.types import DEFAULT_EXTENSION_CHUNKING_PROFILE
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.signing import AuthPayload
from ethernity.encoding.framing import VERSION, Frame, FrameType, encode_frame
from ethernity.extensions.chain import (
    _VALIDATED_CHAIN_STATE_SEAL,
    ReconstructedFile,
    ValidatedChainState,
)
from ethernity.extensions.staging import extension_output_directory_name
from ethernity.formats.extension_mode import UpdateMode
from ethernity.render.checks import RenderValidationError
from ethernity.render.fallback_labels import AUTH_FALLBACK_LABEL
from ethernity.render.types import FallbackSummary
from ethernity.workflows.add_files.document_validation import (
    validate_main_document,
    validate_recovery_document,
)
from ethernity.workflows.add_files.errors import AddFilesIssue, AddFilesWorkflowError
from ethernity.workflows.add_files.execution import assess_prepared_add_files
from ethernity.workflows.add_files.output_settings import ensure_add_files_layout_debug_dir_allowed
from ethernity.workflows.add_files.planning import (
    AppendParent,
    AppendSigningKey,
    ResolvedAddFilesPlan,
    ResolvedAddFilesState,
)
from ethernity.workflows.add_files.prepare import (
    assemble_prepared_extension_document,
    encrypt_prepared_extension_document,
    prepare_add_files_run,
    prepare_add_files_run_from_state,
)
from ethernity.workflows.add_files.request import AddFilesRequest
from ethernity.workflows.recovery.frame_inputs import FrameInputResult
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.input_scope import InputScopeDiff, SelectedInputScope
from ethernity.workflows.shared.operation_types import InputFile


def _validated_chain_state(
    current_state: tuple[ReconstructedFile, ...] = (),
) -> ValidatedChainState:
    state = object.__new__(ValidatedChainState)
    object.__setattr__(state, "root_doc_hash", b"\x22" * 32)
    object.__setattr__(state, "head_doc_hash", b"\x11" * 32)
    object.__setattr__(state, "head_index", 1)
    object.__setattr__(state, "update_mode", UpdateMode.CUMULATIVE)
    object.__setattr__(state, "root_files", current_state)
    object.__setattr__(state, "root_chunks", ())
    object.__setattr__(state, "chunking", DEFAULT_EXTENSION_CHUNKING_PROFILE)
    object.__setattr__(state, "files", current_state)
    object.__setattr__(state, "available_chunks", ())
    object.__setattr__(state, "links", ())
    object.__setattr__(state, "decoded_chunk_bytes", 0)
    object.__setattr__(state, "_seal", _VALIDATED_CHAIN_STATE_SEAL)
    return state


def _resolved_state(
    *,
    diff: InputScopeDiff | None,
    issues: tuple[AddFilesIssue, ...] = (),
) -> ResolvedAddFilesState:
    scope = SelectedInputScope(
        raw_files=("/tmp/source.txt",),
        raw_directories=(),
        base_dir_arg="/tmp",
        input_files=(
            InputFile(
                source_path=None,
                relative_path="source.txt",
                data=b"updated",
                mtime=1,
            ),
        ),
        base_dir=None,
        input_origin="file",
        input_roots=(),
        exact_paths=("source.txt",),
        directory_prefixes=(),
    )
    plan = None
    if diff is not None:
        plan = ResolvedAddFilesPlan(
            diff=diff,
            parent=AppendParent(
                root_doc_hash=b"\x22" * 32,
                head_index=1,
                head_doc_hash=b"\x11" * 32,
            ),
            signing_key=AppendSigningKey(
                signing_seed=b"\x44" * 32,
            ),
        )
    return ResolvedAddFilesState(
        inspection=mock.Mock(blocking_issues=issues),
        plan=plan,
        selected_input=scope,
        validated_chain=_validated_chain_state(),
        chain_document_count=2,
        chain_ciphertext_bytes=100,
        chain_decoded_chunk_bytes=0,
        resolved_passphrase="secret",
    )


def _changed_diff(**overrides: tuple[str, ...]) -> InputScopeDiff:
    values = {
        "new_paths": ("source.txt",),
        "changed_paths": (),
        "unchanged_paths": (),
        "missing_paths": (),
    }
    values.update(overrides)
    return InputScopeDiff(**values)


def _request() -> AddFilesRequest:
    return AddFilesRequest(
        output_dir="/tmp/root",
        input_paths=["/tmp/source.txt"],
    )


def _fallback_summary(*frames: Frame) -> FallbackSummary:
    return FallbackSummary(
        section_frame_digests=tuple(
            hashlib.sha256(encode_frame(frame)).hexdigest() for frame in frames
        ),
        section_titles=(AUTH_FALLBACK_LABEL, "Main Frame"),
        expected_section_count=len(frames),
        emitted_block_count=len(frames),
        emitted_line_count=len(frames),
        consumed_section_count=len(frames),
        fully_consumed=True,
        emitted_fallback_lines=("auth-line", "main-line"),
    )


def test_prepare_requires_an_explicit_input_scope() -> None:
    with pytest.raises(AddFilesWorkflowError) as caught:
        prepare_add_files_run(AddFilesRequest(output_dir="/tmp/root"))
    assert caught.value.code == issue_codes.ADD_FILES_INPUT_REQUIRED


def test_prepare_returns_the_first_typed_planning_issue() -> None:
    issue = AddFilesIssue(code="CHAIN_INVALID", message="broken ancestry")
    with pytest.raises(AddFilesWorkflowError) as caught:
        prepare_add_files_run_from_state(
            _request(),
            _resolved_state(diff=_changed_diff(), issues=(issue,)),
        )
    assert caught.value.code == "CHAIN_INVALID"
    assert str(caught.value) == "broken ancestry"


def test_prepare_rejects_a_noop_diff() -> None:
    with pytest.raises(AddFilesWorkflowError) as noop:
        prepare_add_files_run_from_state(
            _request(),
            _resolved_state(diff=_changed_diff(new_paths=())),
        )
    assert noop.value.code == issue_codes.ADD_FILES_NO_CHANGES


def test_prepare_returns_the_exact_typed_chain_and_diff() -> None:
    prepared = prepare_add_files_run_from_state(
        _request(),
        _resolved_state(
            diff=_changed_diff(
                new_paths=("new.txt",),
                changed_paths=("changed.txt",),
                unchanged_paths=("same.txt",),
            )
        ),
    )
    assert prepared.new_paths == ("new.txt",)
    assert prepared.changed_paths == ("changed.txt",)
    assert prepared.unchanged_paths == ("same.txt",)
    assert prepared.validated_chain.head_doc_hash == b"\x11" * 32


def test_prepare_names_automatic_destination_from_verified_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    request = replace(_request(), output_dir=None, scan_paths=("misleading-backup-name.pdf",))
    prepared = prepare_add_files_run_from_state(request, _resolved_state(diff=_changed_diff()))

    assert prepared.request.output_dir == str(tmp_path / "backup-2222222222222222-update-02")
    assert request.output_dir is None
    assert not list(tmp_path.iterdir())


def test_prepare_preserves_custom_destination() -> None:
    request = replace(_request(), output_dir="chosen/place/custom-name")
    prepared = prepare_add_files_run_from_state(request, _resolved_state(diff=_changed_diff()))

    assert prepared.request.output_dir == request.output_dir


def test_existing_automatic_destination_blocks_before_encryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    prepared = prepare_add_files_run_from_state(
        replace(_request(), output_dir=None), _resolved_state(diff=_changed_diff())
    )
    assert prepared.request.output_dir is not None
    destination = Path(prepared.request.output_dir)
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("existing output")
    monkeypatch.setattr(
        "ethernity.workflows.add_files.execution.add_files_output_settings.resolve_add_files_output_settings",
        lambda *_args, **_kwargs: None,
    )
    encrypted = mock.Mock()
    monkeypatch.setattr(
        "ethernity.workflows.add_files.execution.encrypt_prepared_extension_document", encrypted
    )

    with pytest.raises(AddFilesWorkflowError) as caught:
        assess_prepared_add_files(prepared)

    assert caught.value.code == issue_codes.EXTENSION_PUBLISH_TARGET_INVALID
    encrypted.assert_not_called()
    assert marker.read_text() == "existing output"


@pytest.mark.parametrize("index", [0, -1, True])
def test_update_directory_name_rejects_invalid_index(index: int) -> None:
    with pytest.raises(ValueError):
        extension_output_directory_name(b"r" * 32, index)


def test_update_directory_name_rejects_short_root_fingerprint() -> None:
    with pytest.raises(ValueError):
        extension_output_directory_name(b"r" * 8, 1)


def test_assemble_uses_the_validated_chain_and_selected_scope() -> None:
    prepared = prepare_add_files_run_from_state(
        _request(),
        _resolved_state(diff=_changed_diff()),
    )
    candidate = object()
    with (
        mock.patch(
            "ethernity.workflows.add_files.prepare.require_chain_resource_limits"
        ) as require_limits,
        mock.patch(
            "ethernity.workflows.add_files.prepare.build_extension",
            return_value=candidate,
        ) as build_extension,
    ):
        assert assemble_prepared_extension_document(prepared) is candidate
    require_limits.assert_called_once()
    build_extension.assert_called_once_with(
        prepared.validated_chain,
        prepared.selected_input,
        update_mode=prepared.plan.update_mode,
    )


def test_encrypt_returns_identity_for_the_assessed_payload() -> None:
    prepared = prepare_add_files_run_from_state(
        _request(),
        _resolved_state(diff=_changed_diff()),
    )
    document = SimpleNamespace(encode=lambda: b"plain", inline_chunk_raw_bytes=7)
    built = SimpleNamespace(document=document)
    with (
        mock.patch(
            "ethernity.workflows.add_files.prepare.assemble_prepared_extension_document",
            return_value=built,
        ),
        mock.patch(
            "ethernity.workflows.add_files.prepare.encrypt_bytes_with_passphrase",
            return_value=(b"ciphertext", "secret"),
        ),
    ):
        encrypted = encrypt_prepared_extension_document(prepared)
    expected_id, expected_hash = doc_id_and_hash_from_ciphertext(b"ciphertext")
    assert encrypted.plaintext == b"plain"
    assert encrypted.ciphertext == b"ciphertext"
    assert encrypted.doc_id == expected_id
    assert encrypted.doc_hash == expected_hash


def test_layout_debug_must_be_outside_selected_output(tmp_path: Path) -> None:
    output_dir = tmp_path / "backup" / "extensions"
    with pytest.raises(AddFilesWorkflowError):
        ensure_add_files_layout_debug_dir_allowed(
            output_dir / "debug",
            output_dir=str(output_dir),
        )
    ensure_add_files_layout_debug_dir_allowed(tmp_path / "debug", output_dir=str(output_dir))
    ensure_add_files_layout_debug_dir_allowed(
        tmp_path / "source" / "extensions" / "debug", output_dir=str(output_dir)
    )


def test_main_carrier_rejects_missing_auth() -> None:
    ciphertext = b"enc:extension"
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    main = Frame(VERSION, FrameType.MAIN_DOCUMENT, doc_id, 0, 1, ciphertext)
    with mock.patch(
        "ethernity.workflows.add_files.document_validation.recovery_frames_from_scan",
        return_value=FrameInputResult(frames=(main,)),
    ):
        with pytest.raises(AddFilesWorkflowError) as caught:
            validate_main_document(
                path=Path("recovery.pdf"),
                expected_doc_id=doc_id,
                expected_doc_hash=doc_hash,
                expected_sign_pub=b"\x44" * 32,
                require_auth=True,
            )
    assert caught.value.code == issue_codes.EXTENSION_MAIN_CARRIER_INVALID
    assert "missing auth payload" in str(caught.value)


def test_recovery_document_validates_the_fallback_summary() -> None:
    ciphertext = b"enc:extension"
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    auth = Frame(VERSION, FrameType.AUTH, doc_id, 0, 1, b"auth")
    main = Frame(VERSION, FrameType.MAIN_DOCUMENT, doc_id, 0, 1, ciphertext)
    reader = object()
    with (
        mock.patch(
            "ethernity.workflows.add_files.document_validation._validate_recovery_document_pdf",
            return_value=reader,
        ),
        mock.patch(
            "ethernity.workflows.add_files.document_validation.validate_fallback_text_in_pdf"
        ) as validate_text,
        mock.patch(
            "ethernity.workflows.add_files.document_validation.resolve_required_auth_payload",
            return_value=(
                AuthPayload(1, doc_hash, b"\x44" * 32, b"\x55" * 64),
                "verified",
            ),
        ),
    ):
        validate_recovery_document(
            path=Path("recovery.pdf"),
            frames=(auth, main),
            fallback_summary=_fallback_summary(auth, main),
            expected_doc_id=doc_id,
            expected_doc_hash=doc_hash,
            expected_sign_pub=b"\x44" * 32,
            require_auth=True,
        )
    assert validate_text.call_args.kwargs["reader"] is reader


def test_recovery_document_requires_a_fallback_summary() -> None:
    ciphertext = b"enc:extension"
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    main = Frame(VERSION, FrameType.MAIN_DOCUMENT, doc_id, 0, 1, ciphertext)
    with mock.patch(
        "ethernity.workflows.add_files.document_validation._validate_recovery_document_pdf",
        return_value=object(),
    ):
        with pytest.raises(AddFilesWorkflowError) as caught:
            validate_recovery_document(
                path=Path("recovery.pdf"),
                frames=(main,),
                fallback_summary=None,
                expected_doc_id=doc_id,
                expected_doc_hash=doc_hash,
                expected_sign_pub=b"\x44" * 32,
                require_auth=True,
            )
    assert caught.value.code == issue_codes.EXTENSION_MAIN_CARRIER_INVALID
    assert "missing fallback render summary" in str(caught.value)


def test_recovery_document_wraps_pdf_validation_errors() -> None:
    with (
        mock.patch(
            "ethernity.workflows.add_files.document_validation.validate_pdf_has_pages",
            side_effect=RenderValidationError("invalid PDF"),
        ),
        pytest.raises(AddFilesWorkflowError) as caught,
    ):
        validate_recovery_document(
            path=Path("recovery.pdf"),
            frames=(),
            fallback_summary=None,
            expected_doc_id=b"d" * 8,
            expected_doc_hash=b"h" * 32,
            expected_sign_pub=b"p" * 32,
            require_auth=True,
        )
    assert caught.value.code == issue_codes.EXTENSION_MAIN_CARRIER_INVALID
    assert "invalid PDF" in str(caught.value)
