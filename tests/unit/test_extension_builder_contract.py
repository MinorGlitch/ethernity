# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

import ethernity.extensions as extension_api
import ethernity.extensions.build as build_module
from ethernity.cli.shared.input_scope import SelectedInputScope
from ethernity.cli.shared.types import InputFile
from ethernity.crypto.signing import AuthPayload, derive_public_key, sign_auth
from ethernity.extensions import (
    AuthenticatedExtensionChainLink,
    ValidatedChainState,
    VerifiedExtensionCandidate,
    build_extension,
)
from ethernity.extensions.build import _build_extension_document, build_virtual_chunk_source
from ethernity.extensions.chain import _replay_authenticated_chain_state
from ethernity.formats.envelope_codec import build_manifest_and_payload
from ethernity.formats.envelope_types import PayloadPart
from ethernity.formats.extension_envelope import ExtensionChunkingProfile
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC

ROOT_DOC_HASH = b"\x10" * 32
EXTENSION_DOC_HASH = b"\x20" * 32
SIGNING_SEED = b"\x30" * 32


def _profile() -> ExtensionChunkingProfile:
    return ExtensionChunkingProfile(
        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
        target_size=64 * 1024,
        min_size=16 * 1024,
        max_size=256 * 1024,
    )


def _auth(doc_hash: bytes) -> AuthPayload:
    sign_pub = derive_public_key(SIGNING_SEED)
    return AuthPayload(
        version=1,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        signature=sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=SIGNING_SEED),
    )


def _scope(data: bytes, *, mtime: int) -> SelectedInputScope:
    return SelectedInputScope(
        raw_files=("state.txt",),
        raw_directories=(),
        base_dir_arg=None,
        input_files=(
            InputFile(
                source_path=None,
                relative_path="state.txt",
                data=data,
                mtime=mtime,
            ),
        ),
        base_dir=None,
        input_origin="file",
        input_roots=(),
        exact_paths=("state.txt",),
        directory_prefixes=(),
    )


def test_public_builder_requires_authenticated_replay_state() -> None:
    assert "build_extension" in extension_api.__all__
    assert "build_extension_document" not in extension_api.__all__
    assert not hasattr(extension_api, "build_extension_document")

    with pytest.raises(TypeError, match="authenticated chain replay"):
        ValidatedChainState()

    forged = object.__new__(ValidatedChainState)
    with pytest.raises(TypeError, match="authenticated replay"):
        build_extension(forged, _scope(b"data", mtime=1))


def test_builder_replays_candidate_and_resolves_authenticated_historical_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_bytes = b"root version"
    latest_bytes = b"latest version"
    manifest, payload = build_manifest_and_payload(
        (PayloadPart(path="state.txt", data=root_bytes, mtime=1),),
        sealed=False,
        signing_seed=SIGNING_SEED,
        created_at=1.0,
        input_origin="file",
        input_roots=(),
    )
    profile = _profile()
    extension = _build_extension_document(
        index=1,
        parent_doc_hash=ROOT_DOC_HASH,
        root_doc_hash=ROOT_DOC_HASH,
        chunking=profile,
        input_files=(InputFile(None, "state.txt", latest_bytes, 2),),
        input_origin="file",
        input_roots=(),
        chunker=lambda data, _profile: ((0, len(data)),),
        existing_file_sizes={"state.txt": len(root_bytes)},
        existing_chunks=build_virtual_chunk_source(
            (root_bytes,),
            chunking=profile,
            chunker=lambda data, _profile: ((0, len(data)),),
        ),
        existing_logical_bytes=len(root_bytes),
    ).document
    sign_pub = derive_public_key(SIGNING_SEED)
    link = AuthenticatedExtensionChainLink(
        doc_hash=EXTENSION_DOC_HASH,
        document=extension,
        auth_payload=_auth(EXTENSION_DOC_HASH),
        expected_sign_pub=sign_pub,
    )
    chain = _replay_authenticated_chain_state(
        manifest,
        payload,
        root_doc_hash=ROOT_DOC_HASH,
        root_auth_payload=_auth(ROOT_DOC_HASH),
        expected_sign_pub=sign_pub,
        extensions=(link,),
        root_chunking=profile,
    )

    candidate = build_extension(chain, _scope(root_bytes, mtime=3))

    assert isinstance(candidate, VerifiedExtensionCandidate)
    assert candidate.stats.reused_chunks == 1
    assert candidate.stats.new_chunks == 0
    assert candidate.document.chunks == ()
    assert candidate.document.files[0].chunk_refs[0].chunk_id == hashlib.sha256(root_bytes).digest()
    assert candidate.resulting_state[0].data == root_bytes

    unresolved_ref = replace(
        candidate.document.files[0].chunk_refs[0],
        chunk_id=b"\xff" * 32,
    )
    unresolved_file = replace(
        candidate.document.files[0],
        chunk_refs=(unresolved_ref,),
    )
    unresolved_document = replace(candidate.document, files=(unresolved_file,))
    monkeypatch.setattr(
        build_module,
        "_build_extension_document",
        lambda **_kwargs: SimpleNamespace(
            document=unresolved_document,
            stats=candidate.stats,
        ),
    )

    with pytest.raises(ValueError, match="unresolved chunk_id"):
        build_extension(chain, _scope(root_bytes, mtime=3))
