"""Both update models use the same authenticated build and replay APIs."""

import hashlib
from dataclasses import replace

import pytest

from ethernity.crypto.signing import AuthPayload, derive_public_key, sign_auth
from ethernity.extensions.build import build_extension
from ethernity.extensions.chain import AuthenticatedExtensionChainLink, replay_authenticated_chain
from ethernity.formats.document_codec import build_manifest_and_payload
from ethernity.formats.extension_document import (
    ExtensionChunkingProfile,
    ExtensionDocument,
    ExtensionHeader,
)
from ethernity.formats.extension_mode import UpdateMode
from ethernity.formats.manifest import BackupFile
from ethernity.workflows.shared.input_scope import SelectedInputScope
from ethernity.workflows.shared.operation_types import InputFile

SEED = b"s" * 32
ROOT_HASH = b"r" * 32
PROFILE = ExtensionChunkingProfile(1, 16384, 4096, 65536)


def _auth(doc_hash):
    public = derive_public_key(SEED)
    return AuthPayload(1, doc_hash, public, sign_auth(doc_hash, sign_pub=public, sign_priv=SEED))


def _link(document):
    doc_hash = hashlib.sha256(document.encode()).digest()
    return AuthenticatedExtensionChainLink(
        doc_hash, document, _auth(doc_hash), derive_public_key(SEED)
    )


def _scope(**files):
    return SelectedInputScope(
        raw_files=tuple(files),
        raw_directories=(),
        base_dir_arg=None,
        input_files=tuple(InputFile(None, path, data, 1) for path, data in files.items()),
        base_dir=None,
        input_origin="file",
        input_roots=(),
        exact_paths=tuple(files),
        directory_prefixes=(),
    )


@pytest.fixture
def replay():
    manifest, payload = build_manifest_and_payload(
        (BackupFile("original.txt", b"original", 1),),
        sealed=False,
        signing_seed=SEED,
        input_origin="file",
        input_roots=(),
    )

    def run(*links):
        return replay_authenticated_chain(
            manifest,
            payload,
            root_doc_hash=ROOT_HASH,
            root_auth_payload=_auth(ROOT_HASH),
            expected_sign_pub=derive_public_key(SEED),
            extensions=links,
            root_chunking=PROFILE,
        )

    return run


@pytest.mark.parametrize("mode", list(UpdateMode))
def test_three_updates_have_mode_specific_dependencies(replay, mode):
    first = _link(build_extension(replay(), _scope(codes=b"codes"), update_mode=mode).document)
    second = _link(build_extension(replay(first), _scope(**{"original.txt": b"changed"})).document)
    third = _link(build_extension(replay(first, second), _scope(notes=b"notes")).document)
    expected = {"original.txt": b"changed", "codes": b"codes", "notes": b"notes"}
    assert {item.path: item.data for item in replay(first, second, third).files} == expected
    assert third.document.header.update_mode == mode
    assert set(third.document.header.to_cbor()) == {2, 4, 5, 7, 10, 13}
    assert ExtensionDocument.decode(third.document.encode()) == third.document

    if mode == UpdateMode.CUMULATIVE:
        sparse = replay(third)
        assert sparse.head_index == 3
        assert {item.path: item.data for item in sparse.files} == expected
        assert replay(first, third).files == sparse.files
        fourth = build_extension(sparse, _scope(more=b"more")).document
        assert fourth.header.index == 4
        assert fourth.header.parent_doc_hash == ROOT_HASH
        assert {item.path for item in fourth.files} == {*expected, "more"}
    else:
        with pytest.raises(ValueError, match="index sequence"):
            replay(third)
        with pytest.raises(ValueError, match="index sequence"):
            replay(first, third)
        assert third.document.header.parent_doc_hash == second.doc_hash


def test_new_series_defaults_to_cumulative_and_can_revert_to_original(replay):
    first = _link(build_extension(replay(), _scope(**{"original.txt": b"changed"})).document)
    reverted = build_extension(replay(first), _scope(**{"original.txt": b"original"}))
    assert reverted.document.header.update_mode == UpdateMode.CUMULATIVE
    assert reverted.document.files == ()
    assert reverted.document.chunks == ()
    decoded = ExtensionDocument.decode(reverted.document.encode())
    assert replay(_link(decoded)).files == replay().files


@pytest.mark.parametrize("mode", list(UpdateMode))
def test_duplicate_input_paths_are_rejected_before_snapshot_merge(replay, mode):
    scope = _scope(a=b"one")
    scope = replace(scope, input_files=(*scope.input_files, InputFile(None, "a", b"two", 1)))
    with pytest.raises(ValueError, match="duplicate extension input paths"):
        build_extension(replay(), scope, update_mode=mode)


@pytest.mark.parametrize("mode", list(UpdateMode))
def test_mode_is_fixed_and_mixed_documents_are_rejected(replay, mode):
    first = _link(build_extension(replay(), _scope(a=b"a"), update_mode=mode).document)
    other = UpdateMode.INCREMENTAL if mode == UpdateMode.CUMULATIVE else UpdateMode.CUMULATIVE
    with pytest.raises(ValueError, match="mode is fixed"):
        build_extension(replay(first), _scope(b=b"b"), update_mode=other)
    second = build_extension(replay(first), _scope(b=b"b")).document
    mixed = replace(second, header=replace(second.header, update_mode=other))
    with pytest.raises(ValueError, match="mode is fixed"):
        replay(first, _link(mixed))


def test_cumulative_cannot_resolve_chunks_from_an_earlier_update(replay):
    first = _link(build_extension(replay(), _scope(a=b"carried data")).document)
    second = build_extension(replay(first), _scope(b=b"carried data")).document
    assert len(second.chunks) == 1  # Shared within the update, repeated across cumulative updates.
    assert len(second.files) == 2
    missing = _link(replace(second, chunks=()))
    with pytest.raises(ValueError, match="unresolved chunk_id"):
        replay(first, missing)


def test_cumulative_reuses_root_chunks_and_rejects_invalid_lineage(replay):
    first = _link(build_extension(replay(), _scope(copy=b"original")).document)
    assert first.document.chunks == ()
    assert replay(first).files[-1].data == b"original"
    for change, message in (
        ({"parent_doc_hash": b"x" * 32}, "parent_doc_hash"),
        ({"root_doc_hash": b"x" * 32}, "root_doc_hash"),
    ):
        bad = _link(replace(first.document, header=replace(first.document.header, **change)))
        with pytest.raises(ValueError, match=message):
            replay(bad)
    with pytest.raises(ValueError, match="index sequence"):
        replay(first, first)
    second = build_extension(replay(first), _scope(b=b"b")).document
    bad_profile = replace(PROFILE, target_size=8192)
    bad = _link(replace(second, header=replace(second.header, chunking=bad_profile)))
    with pytest.raises(ValueError, match="chunking profile"):
        replay(first, bad)


def test_unsupported_header_schema_is_rejected(replay):
    document = build_extension(replay(), _scope(a=b"a")).document
    header = document.header.to_cbor() | {1: 2}
    with pytest.raises(ValueError, match="unknown keys"):
        ExtensionHeader.from_cbor(header)


@pytest.mark.parametrize("mode", [None, "", "differential", 1, True])
def test_schema_one_requires_a_recognized_mode(replay, mode):
    document = build_extension(replay(), _scope(a=b"a")).document
    header = document.header.to_cbor()
    if mode is None:
        del header[13]
    else:
        header[13] = mode
    with pytest.raises(ValueError):
        ExtensionHeader.from_cbor(header)
