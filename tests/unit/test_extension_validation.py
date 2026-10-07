"""Inspector diagnostics come from the same validation used by recovery."""

from dataclasses import replace

import pytest
from tooling.document_inspector_app import analysis

from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.signing import AuthPayload, derive_public_key, encode_auth_payload, sign_auth
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.extensions import validation
from ethernity.extensions.build import _build_extension_document
from ethernity.extensions.chain import ExtensionReplayError
from ethernity.extensions.errors import ExtensionRecoveryError
from ethernity.extensions.recovery import ImportedRecoveryDocument, recover_chain_entries
from ethernity.formats.document_codec import build_manifest_and_payload, encode_backup_document
from ethernity.formats.extension_constants import CHUNK_ALGORITHM_FASTCDC
from ethernity.formats.extension_document import ExtensionChunkingProfile, ExtensionDocument
from ethernity.formats.extension_mode import UpdateMode
from ethernity.formats.manifest import BackupFile, BackupManifest
from ethernity.workflows.recovery.planning import RecoveryPlan
from ethernity.workflows.recovery.source_state import recovery_source_fields
from ethernity.workflows.shared.operation_types import InputFile

SIGNING_SEED = b"s" * 32


def _signed_document(
    plaintext: bytes,
    decoded: tuple[BackupManifest, bytes] | ExtensionDocument,
    *,
    signing_seed: bytes = SIGNING_SEED,
) -> analysis._DecodedMainDocument:
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(plaintext)
    sign_pub = derive_public_key(signing_seed)
    return analysis._DecodedMainDocument(
        doc_id=doc_id,
        frame_count=1,
        ciphertext=plaintext,
        doc_hash=doc_hash,
        reassembly_error=None,
        document_format_version=2,
        decoded=decoded,
        auth_payload=AuthPayload(
            version=1,
            doc_hash=doc_hash,
            sign_pub=sign_pub,
            signature=sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=signing_seed),
        ),
        auth_status="verified",
    )


@pytest.fixture
def root_document() -> analysis._DecodedMainDocument:
    manifest, payload = build_manifest_and_payload(
        (BackupFile("a.txt", b"original", 1),), signing_seed=SIGNING_SEED
    )
    return _signed_document(encode_backup_document(payload, manifest), (manifest, payload))


def _extension(
    root: analysis._DecodedMainDocument,
    index: int,
    parent_hash: bytes,
    *,
    update_mode: UpdateMode = UpdateMode.INCREMENTAL,
) -> analysis._DecodedMainDocument:
    assert root.doc_hash is not None
    built = _build_extension_document(
        index=index,
        parent_doc_hash=parent_hash,
        root_doc_hash=root.doc_hash,
        update_mode=update_mode,
        chunking=ExtensionChunkingProfile(CHUNK_ALGORITHM_FASTCDC, 16384, 4096, 65536),
        input_files=(InputFile(None, "a.txt", f"update {index}".encode(), index + 1),),
        existing_file_sizes={},
    )
    return _signed_document(built.document.encode(), built.document)


def _validate(
    root: analysis._DecodedMainDocument, extensions: list[analysis._DecodedMainDocument]
) -> validation.ChainValidationResult:
    assert isinstance(root.decoded, tuple) and root.doc_hash is not None
    manifest, payload = root.decoded
    inputs = []
    for extension in extensions:
        assert isinstance(extension.decoded, ExtensionDocument) and extension.doc_hash is not None
        inputs.append(
            validation.DecodedChainExtension(
                extension.doc_hash, extension.decoded, extension.auth_payload, extension.auth_status
            )
        )
    return validation.inspect_chain_validation(
        manifest,
        payload,
        root_doc_hash=root.doc_hash,
        root_auth_payload=root.auth_payload,
        root_auth_status=root.auth_status,
        extensions=inputs,
    )


def _plan(
    root: analysis._DecodedMainDocument, extensions: list[analysis._DecodedMainDocument]
) -> RecoveryPlan:
    imported = []
    for document in [root, *extensions]:
        assert document.auth_payload is not None
        auth = document.auth_payload
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=document.doc_id,
            index=0,
            total=1,
            data=encode_auth_payload(
                auth.doc_hash, sign_pub=auth.sign_pub, signature=auth.signature
            ),
        )
        imported.append(
            ImportedRecoveryDocument(
                document.doc_id, document.doc_hash, document.ciphertext, (frame,), "test"
            )
        )
    return RecoveryPlan(
        source=recovery_source_fields("test", None, (), ()),
        ciphertext=root.ciphertext,
        doc_id=root.doc_id,
        doc_hash=root.doc_hash,
        auth_payload=root.auth_payload,
        auth_status="verified",
        allow_unsigned=False,
        passphrase="test",
        output_path=None,
        import_documents=tuple(imported),
    )


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("hash", "AUTH_DOC_HASH_MISMATCH"),
        ("signature", "AUTH_SIGNATURE_INVALID"),
        ("key", "ROOT_SIGNING_KEY_MISMATCH"),
    ],
)
def test_verified_status_cannot_bypass_root_cryptography(root_document, failure, expected_code):
    assert root_document.auth_payload is not None
    auth = root_document.auth_payload
    if failure == "hash":
        auth = replace(auth, doc_hash=b"x" * 32)
    elif failure == "signature":
        auth = replace(auth, signature=b"x" * 64)
    else:
        foreign = _signed_document(
            root_document.ciphertext, root_document.decoded, signing_seed=b"f" * 32
        )
        auth = foreign.auth_payload
    root = replace(root_document, auth_payload=auth)
    result = root.root_validation
    assert result is not None and result.error is not None
    assert result.error.code == expected_code
    assert result.error.details["validated_head_index"] is None
    assert result.error.details["validated_head_doc_hash"] is None
    with pytest.raises(ExtensionRecoveryError) as raised:
        result.require_valid()
    assert raised.value is result.error
    document, files, diagnostic = analysis._inspect_decoded_documents([root])
    assert document is None and files == []
    assert diagnostic.code == expected_code


@pytest.mark.parametrize("failure", ["missing", "signature", "hash", "key"])
def test_extension_trust_failure_reports_root_without_claiming_preceding_update(
    root_document, failure
):
    root = root_document
    first = _extension(root, 1, root.doc_hash)
    second = _extension(root, 2, first.doc_hash)
    auth = second.auth_payload
    if failure == "missing":
        auth = None
    elif failure == "signature":
        auth = replace(auth, signature=b"x" * 64)
    elif failure == "hash":
        auth = replace(auth, doc_hash=b"x" * 32)
    else:
        auth = _signed_document(
            second.ciphertext, second.decoded, signing_seed=b"f" * 32
        ).auth_payload
    second = replace(second, auth_payload=auth)
    result = _validate(root, [first, second])
    assert result.state is None
    assert isinstance(result.error, ExtensionReplayError)
    assert result.error.failure_phase == "auth"
    assert result.error.failing_index == 2
    assert result.error.last_validated_head_index == 0
    with pytest.raises(ExtensionReplayError) as raised:
        result.require_state()
    assert raised.value is result.error
    document, files, diagnostic = analysis._inspect_decoded_documents([root, first, second])
    assert document is None and files == []
    assert diagnostic.details["failure_stage"] == result.error.failure_phase
    assert diagnostic.details["failure_head_doc_hash"] == second.doc_hash.hex()
    assert diagnostic.details["validated_head_index"] == 0
    assert diagnostic.details["validated_head_doc_hash"] == root.doc_hash.hex()


@pytest.mark.parametrize("failing_index", [1, 2])
def test_inspector_reports_last_replayed_head_on_lineage_failure(
    root_document, failing_index, monkeypatch
):
    root = root_document
    first = _extension(root, 1, b"x" * 32 if failing_index == 1 else root.doc_hash)
    second = _extension(root, 2, b"x" * 32 if failing_index == 2 else first.doc_hash)
    result = _validate(root, [first, second])
    assert isinstance(result.error, ExtensionReplayError)
    assert result.error.failure_phase == "lineage"
    assert result.error.failing_index == failing_index
    assert result.error.last_validated_head_index == failing_index - 1
    document, files, diagnostic = analysis._inspect_decoded_documents([second, root, first])
    assert document is None and files == []
    assert diagnostic.details["failure_stage"] == "lineage"
    assert diagnostic.details["failure_head_index"] == failing_index
    assert diagnostic.details["validated_head_index"] == result.error.last_validated_head_index
    assert (
        diagnostic.details["validated_head_doc_hash"] == result.error.last_validated_head_hash.hex()
    )
    monkeypatch.setattr(
        "ethernity.extensions.recovery.decrypt_bytes",
        lambda data, *, passphrase, debug=False: data,
    )
    with pytest.raises(ExtensionRecoveryError) as recovery_error:
        recover_chain_entries(_plan(root, [first, second]))
    for key in (
        "failure_stage",
        "failure_head_index",
        "validated_head_index",
        "validated_head_doc_hash",
    ):
        assert recovery_error.value.details[key] == diagnostic.details[key]


@pytest.mark.parametrize("mode", [UpdateMode.INCREMENTAL, UpdateMode.CUMULATIVE])
def test_inspection_and_recovery_reconstruct_same_state(root_document, mode, monkeypatch):
    root = root_document
    first = _extension(root, 1, root.doc_hash, update_mode=mode)
    second = _extension(
        root,
        2,
        root.doc_hash if mode == UpdateMode.CUMULATIVE else first.doc_hash,
        update_mode=mode,
    )
    extensions = [second] if mode == UpdateMode.CUMULATIVE else [first, second]
    result = _validate(root, extensions)
    state = result.require_state()
    assert state.head_index == 2
    document, files, diagnostic = analysis._inspect_decoded_documents([*reversed(extensions), root])
    assert {record.path: record.data for record in files} == {
        item.path: item.data for item in state.files
    }
    assert document["latest_state"]["file_count"] == len(state.files)
    assert diagnostic.status == "ok"
    assert diagnostic.details["validated_head_doc_hash"] == state.head_doc_hash.hex()
    monkeypatch.setattr(
        "ethernity.extensions.recovery.decrypt_bytes",
        lambda data, *, passphrase, debug=False: data,
    )
    recovered = recover_chain_entries(_plan(root, extensions))
    assert {entry.path: data for entry, data in recovered.extracted} == {
        record.path: record.data for record in files
    }
