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

from dataclasses import replace
from pathlib import Path

import pytest

from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.crypto import decrypt_bytes, encrypt_bytes_with_passphrase
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.signing import (
    decode_auth_payload,
    derive_public_key,
    encode_auth_payload,
    sign_auth,
)
from ethernity.encoding.chunking import chunk_payload, reassemble_payload
from ethernity.encoding.framing import Frame, FrameType
from ethernity.formats.document_codec import (
    build_manifest_and_payload,
    decode_backup_document,
    encode_backup_document,
)
from ethernity.formats.extension_mode import UpdateMode
from ethernity.formats.manifest import BackupFile
from ethernity.workflows.add_files.errors import AddFilesWorkflowError
from ethernity.workflows.add_files.planning import inspect_add_files, resolve_add_files_state
from ethernity.workflows.add_files.prepare import prepare_add_files_run_from_state
from ethernity.workflows.add_files.request import AddFilesRequest
from ethernity.workflows.recovery.frame_inputs import frames_from_payloads
from ethernity.workflows.shared import issue_codes

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "v1_2" / "extension_golden"
GZIP_CHAIN = FIXTURE_ROOT / "base64" / "gzip_replacement_chain"
RAW_CHAIN = FIXTURE_ROOT / "raw" / "large_raw_two_extension_chain"
PASSPHRASE = "stable-v1_2-extension-passphrase"


def _frames(root: Path = GZIP_CHAIN, name: str = "chain") -> tuple[Frame, ...]:
    return tuple(frames_from_payloads(str(root / f"{name}_payloads.txt")))


def _ciphertext(frames: tuple[Frame, ...]) -> bytes:
    return reassemble_payload(
        tuple(frame for frame in frames if frame.frame_type == FrameType.MAIN_DOCUMENT)
    )


def _hash(frames: tuple[Frame, ...]) -> str:
    return doc_id_and_hash_from_ciphertext(_ciphertext(frames))[1].hex()


def _request(**kwargs) -> AddFilesRequest:
    values = {
        "config_path": str(DEFAULT_CONFIG_PATH),
        "frames": _frames(),
        "passphrase": PASSPHRASE,
        "allow_stale_head": True,
    }
    values.update(kwargs)
    return AddFilesRequest(**values)


def _signed_frames(plaintext: bytes, signing_seed: bytes) -> tuple[Frame, ...]:
    ciphertext, _ = encrypt_bytes_with_passphrase(plaintext, passphrase=PASSPHRASE)
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    sign_pub = derive_public_key(signing_seed)
    auth_data = encode_auth_payload(
        doc_hash,
        sign_pub=sign_pub,
        signature=sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=signing_seed),
    )
    return (
        *chunk_payload(ciphertext, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT),
        Frame(1, FrameType.AUTH, doc_id, 0, 1, auth_data),
    )


def _issue_codes(inspection) -> set[str]:
    return {issue.code for issue in inspection.blocking_issues}


def test_inspection_requires_recovery_inputs() -> None:
    with pytest.raises(AddFilesWorkflowError) as exc_info:
        inspect_add_files(_request(frames=()))
    assert exc_info.value.code == issue_codes.INPUT_REQUIRED


def test_existing_series_rejects_mode_change_before_publication() -> None:
    resolved = resolve_add_files_state(_request(update_mode=UpdateMode.INCREMENTAL))
    assert any("mode is fixed" in issue.message for issue in resolved.blocking_issues)
    assert resolved.validated_chain is not None
    assert resolved.validated_chain.update_mode == UpdateMode.CUMULATIVE


def test_shuffled_duplicate_frames_resolve_the_authenticated_chain() -> None:
    root_frames = _frames(name="root")
    extension_frames = _frames(name="extension_01")
    supplied = tuple(reversed((*extension_frames, *root_frames, *extension_frames)))

    resolved = resolve_add_files_state(_request(frames=supplied))
    inspection = resolved.inspection

    assert not inspection.blocking_issues
    assert inspection.root_doc_hash == _hash(root_frames)
    assert inspection.available_extension_indices == (1,)
    assert inspection.validated_head_index == 1
    assert inspection.validated_head_doc_hash == _hash(extension_frames)
    assert inspection.ancestry_valid is True
    assert inspection.root_auth_status == "verified"
    assert inspection.validated_head_auth_status == "verified"
    assert inspection.validated_head_root_signing_key_verified is True
    assert inspection.signing_key == {
        "available": True,
        "satisfied": True,
        "source": "embedded_seed",
    }
    assert resolved.chain_document_count == 2
    assert resolved.validated_chain is not None
    assert {item.path for item in resolved.validated_chain.files} == {
        "alpha.txt",
        "empty-at-root.txt",
        "nested/inherited.txt",
        "new-empty.txt",
    }
    assert resolved.source_frames == supplied


def test_text_payload_import_matches_preloaded_frame_import() -> None:
    from_frames = inspect_add_files(_request())
    from_text = inspect_add_files(
        _request(frames=(), payloads_file=str(GZIP_CHAIN / "chain_payloads.txt"))
    )

    assert not from_text.blocking_issues
    assert from_text.root_doc_hash == from_frames.root_doc_hash
    assert from_text.validated_head_doc_hash == from_frames.validated_head_doc_hash
    assert from_text.available_extension_indices == from_frames.available_extension_indices
    assert from_text.available_extensions == from_frames.available_extensions


def test_extra_auth_frames_are_matched_by_document_identity() -> None:
    frames = _frames()
    main_frames = tuple(frame for frame in frames if frame.frame_type == FrameType.MAIN_DOCUMENT)
    auth_frames = tuple(frame for frame in frames if frame.frame_type == FrameType.AUTH)

    inspection = inspect_add_files(
        _request(frames=tuple(reversed(main_frames)), auth_frames=tuple(reversed(auth_frames)))
    )

    assert not inspection.blocking_issues
    assert inspection.validated_head_doc_hash == _hash(_frames(name="extension_01"))


@pytest.mark.parametrize("name", ["root", "chain"])
def test_source_freshness_requires_a_pin_or_explicit_acknowledgement(name: str) -> None:
    inspection = inspect_add_files(_request(frames=_frames(name=name), allow_stale_head=False))

    assert issue_codes.RECOVERY_HEAD_UNTRUSTED in _issue_codes(inspection)


def test_expected_head_pin_is_normalized_and_enforced() -> None:
    head_hash = _hash(_frames(name="extension_01"))
    pinned = inspect_add_files(
        _request(expected_head_doc_hash=f"  {head_hash.upper()}  ", allow_stale_head=False)
    )
    wrong = inspect_add_files(_request(expected_head_doc_hash="00" * 32))

    assert not pinned.blocking_issues
    assert pinned.validated_head_doc_hash == head_hash
    assert issue_codes.RECOVERY_HEAD_UNTRUSTED in _issue_codes(wrong)


def test_missing_ancestor_cannot_be_used_as_an_append_source() -> None:
    frames = (*_frames(RAW_CHAIN, "root"), *_frames(RAW_CHAIN, "extension_02"))

    inspection = inspect_add_files(_request(frames=frames))

    assert issue_codes.RECOVERY_HEAD_UNTRUSTED in _issue_codes(inspection)
    assert inspection.ancestry_valid is not True


def test_authenticated_forks_cannot_be_used_as_an_append_source() -> None:
    root_manifest, _ = decode_backup_document(
        decrypt_bytes(_ciphertext(_frames(name="root")), passphrase=PASSPHRASE)
    )
    assert root_manifest.signing_seed is not None
    extension_plaintext = decrypt_bytes(
        _ciphertext(_frames(name="extension_01")), passphrase=PASSPHRASE
    )
    fork = _signed_frames(extension_plaintext, root_manifest.signing_seed)

    inspection = inspect_add_files(_request(frames=(*_frames(), *fork)))

    assert issue_codes.RECOVERY_HEAD_UNTRUSTED in _issue_codes(inspection)
    assert inspection.ancestry_valid is not True


@pytest.mark.parametrize("role", ["root", "extension_01"])
def test_invalid_authentication_cannot_be_used_as_an_append_source(role: str) -> None:
    doc_id = bytes.fromhex(_hash(_frames(name=role))[:16])
    frames = []
    for frame in _frames():
        if frame.frame_type == FrameType.AUTH and frame.doc_id == doc_id:
            auth = decode_auth_payload(frame.data)
            signature = bytes([auth.signature[0] ^ 1]) + auth.signature[1:]
            frame = replace(
                frame,
                data=encode_auth_payload(
                    auth.doc_hash, sign_pub=auth.sign_pub, signature=signature
                ),
            )
        frames.append(frame)

    inspection = inspect_add_files(_request(frames=tuple(frames)))

    assert inspection.blocking_issues
    assert inspection.ancestry_valid is not True
    assert inspection.validated_head_root_signing_key_verified is not True


def test_sealed_root_cannot_be_used_as_an_append_source() -> None:
    manifest, payload = build_manifest_and_payload(
        (BackupFile("sealed.txt", b"sealed root", 1),), sealed=True, created_at=1.0
    )
    frames = _signed_frames(encode_backup_document(payload, manifest), b"s" * 32)

    inspection = inspect_add_files(_request(frames=frames))

    assert issue_codes.SEALED_ROOT_CANNOT_ACCEPT_UPDATES in _issue_codes(inspection)
    assert inspection.signing_key["satisfied"] is False


def test_embedded_seed_must_match_authenticated_root_signing_key() -> None:
    manifest, payload = build_manifest_and_payload(
        (BackupFile("root.txt", b"unsealed root", 1),),
        signing_seed=b"a" * 32,
        created_at=1.0,
    )
    frames = _signed_frames(encode_backup_document(payload, manifest), b"b" * 32)

    inspection = inspect_add_files(_request(frames=frames))

    assert issue_codes.ROOT_SIGNING_KEY_MISMATCH in _issue_codes(inspection)
    assert inspection.signing_key["satisfied"] is False


def test_root_shards_unlock_a_multi_extension_source_without_a_passphrase() -> None:
    shards = tuple(frames_from_payloads(str(RAW_CHAIN / "root_shard_payloads_threshold.txt")))

    resolved = resolve_add_files_state(
        _request(frames=_frames(RAW_CHAIN), passphrase=None, shard_frames=shards)
    )

    assert not resolved.blocking_issues
    assert resolved.inspection.unlock["mode"] == "shards"
    assert resolved.inspection.unlock["satisfied"] is True
    assert resolved.inspection.unlock["validated_shard_count"] == 2
    assert resolved.inspection.available_extension_indices == (1, 2)
    assert resolved.inspection.validated_head_index == 2
    assert resolved.resolved_passphrase == PASSPHRASE


def test_wrong_passphrase_does_not_produce_append_authority() -> None:
    request = _request(passphrase="wrong passphrase")
    resolved = resolve_add_files_state(request)

    assert resolved.blocking_issues
    assert resolved.inspection.unlock["satisfied"] is False
    assert resolved.plan is None
    assert resolved.validated_chain is None
    assert resolved.source_frames == request.frames


@pytest.mark.parametrize(("existing_path", "selected_path"), [("a", "a/b"), ("a/b", "a")])
def test_conflicting_update_paths_require_a_new_backup(
    tmp_path: Path, existing_path: str, selected_path: str
) -> None:
    seed = b"a" * 32
    manifest, payload = build_manifest_and_payload(
        (BackupFile(existing_path, b"root", 1),), signing_seed=seed, created_at=1.0
    )
    selected = tmp_path / selected_path
    selected.parent.mkdir(parents=True, exist_ok=True)
    selected.write_bytes(b"new file")
    request = _request(
        frames=_signed_frames(encode_backup_document(payload, manifest), seed),
        input_paths=(str(selected),),
        base_directory=str(tmp_path),
    )
    resolved = resolve_add_files_state(request)

    issue = next(
        item for item in resolved.blocking_issues if item.details.get("stage") == "file_tree"
    )
    assert issue.code == issue_codes.DELETE_NOT_SUPPORTED
    assert "Create a new backup" in issue.message
    with pytest.raises(AddFilesWorkflowError) as exc_info:
        prepare_add_files_run_from_state(request, resolved)
    assert exc_info.value.code == issue_codes.DELETE_NOT_SUPPORTED


def test_selected_file_diff_uses_latest_reconstructed_content(tmp_path: Path) -> None:
    selected = tmp_path / "alpha.txt"
    selected.write_bytes(b"next alpha")

    resolved = resolve_add_files_state(_request(input_paths=(str(selected),)))

    assert not resolved.blocking_issues
    assert resolved.plan is not None
    assert resolved.plan.diff.changed_paths == ("alpha.txt",)
    assert resolved.plan.diff.new_paths == ()
    assert resolved.selected_input is not None
    assert resolved.selected_input.input_files[0].data == b"next alpha"
    assert resolved.plan.parent.head_index == 1
    assert resolved.plan.parent.head_doc_hash.hex() == _hash(_frames(name="extension_01"))


def test_directory_scope_omissions_remain_a_domain_error(tmp_path: Path) -> None:
    selected = tmp_path / "selected"
    selected.mkdir()
    (selected / "alpha.txt").write_bytes(b"next alpha")

    inspection = inspect_add_files(
        _request(input_directories=(str(selected),), base_directory=str(selected))
    )

    assert issue_codes.DELETE_NOT_SUPPORTED in _issue_codes(inspection)
    assert inspection.diff_summary is not None
    assert inspection.diff_summary["missing_paths"] == [
        "empty-at-root.txt",
        "nested/inherited.txt",
        "new-empty.txt",
    ]


def test_ambiguous_backup_paths_still_require_an_explicit_base_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    selected = nested / "inherited.txt"
    selected.write_bytes(b"next inherited")

    inspection = inspect_add_files(_request(input_paths=(str(selected),)))

    assert issue_codes.INVALID_INPUT in _issue_codes(inspection)
    assert inspection.diff_summary is not None


@pytest.mark.parametrize("existing_chain", [False, True])
def test_chunking_configuration_only_changes_a_new_chain(
    tmp_path: Path, existing_chain: bool
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[defaults.backup]\nqr_payload_codec = "raw"\n\n'
        "[extension.chunking]\ntarget_size = 32768\nmin_size = 8192\nmax_size = 131072\n",
        encoding="utf-8",
    )
    frames = _frames(name="chain" if existing_chain else "root")

    resolved = resolve_add_files_state(_request(config_path=str(config), frames=frames))

    assert not resolved.blocking_issues
    assert resolved.validated_chain is not None
    profile = resolved.validated_chain.chunking
    assert (profile.target_size, profile.min_size, profile.max_size) == (
        (16 * 1024, 4 * 1024, 64 * 1024) if existing_chain else (32768, 8192, 131072)
    )
