"""Released documents and current documents normalize to the same recovery model."""

import gzip
from dataclasses import replace

import pytest

from ethernity.encoding.cbor import dumps_deterministic, loads_deterministic
from ethernity.encoding.varint import decode_uvarint, encode_uvarint
from ethernity.formats.document_codec import (
    build_manifest_and_payload,
    decode_backup_document,
    decode_document,
    encode_backup_document,
    extract_payloads,
)
from ethernity.formats.document_constants import DocumentKind
from ethernity.formats.document_header import read_document_header
from ethernity.formats.extension_document import ExtensionDocument
from ethernity.formats.manifest import BackupFile


def legacy_document(manifest, payload, **overrides):
    """Build released v1 bytes only in tests; production has no legacy writer."""
    fields = manifest.to_cbor()
    fields.update(version=1, sealed=manifest.sealed)
    if manifest.payload_codec == "gzip":
        fields["payload_raw_len"] = manifest.payload_raw_len
    fields.update(overrides)
    encoded = dumps_deterministic(fields)
    return (
        b"AY\x01" + encode_uvarint(len(encoded)) + encoded + encode_uvarint(len(payload)) + payload
    )


@pytest.mark.parametrize("sealed", [True, False])
@pytest.mark.parametrize("codec", ["raw", "gzip"])
@pytest.mark.parametrize("nested", [True, False])
def test_released_and_current_documents_share_recovery(sealed, codec, nested):
    parts = [
        BackupFile(
            path=f"long/shared/directory/file-{i}.txt" if nested else f"file-{i}.txt",
            data=b"backup contents\n" * 20,
            mtime=i,
        )
        for i in range(20 if nested else 1)
    ]
    manifest, raw = build_manifest_and_payload(
        parts,
        sealed=sealed,
        signing_seed=None if sealed else b"s" * 32,
        created_at=123,
        input_origin="directory" if nested else "file",
        input_roots=("directory",) if nested else (),
    )
    manifest = replace(manifest, payload_codec=codec)
    stored = gzip.compress(raw, mtime=0) if codec == "gzip" else raw
    current = encode_backup_document(stored, manifest)
    assert current[:4] == b"AY\x02\x01"
    length, offset = decode_uvarint(current, 4)
    encoded_fields = loads_deterministic(current[offset : offset + length], label="manifest")
    assert not {"version", "sealed", "payload_raw_len"} & encoded_fields.keys()
    assert encoded_fields["path_encoding"] == ("prefix_table" if nested else "direct")
    for expected_version, document in [(1, legacy_document(manifest, stored)), (2, current)]:
        version, decoded = decode_document(document)
        actual, payload = decoded
        assert version == expected_version
        assert actual == manifest
        assert dict((entry.path, data) for entry, data in extract_payloads(actual, payload)) == {
            part.path: part.data for part in parts
        }
        # Re-encoding a decoded older backup always produces the current format.
        assert encode_backup_document(payload, actual) == current


@pytest.mark.parametrize(
    "overrides",
    [
        {"version": 2},
        {"sealed": True},
        {"payload_raw_len": 99},
        {"payload_raw_len": None},
    ],
)
def test_legacy_inconsistencies_are_rejected_before_normalizing(overrides):
    manifest, raw = build_manifest_and_payload(
        [BackupFile("file.txt", b"contents", None)],
        signing_seed=b"s" * 32,
    )
    manifest = replace(manifest, payload_codec="gzip")
    with pytest.raises(ValueError):
        decode_document(legacy_document(manifest, gzip.compress(raw), **overrides))


@pytest.mark.parametrize("key", ["version", "sealed", "payload_raw_len"])
def test_current_documents_reject_removed_fields(key):
    manifest, payload = build_manifest_and_payload(
        [BackupFile("file.txt", b"contents", None)],
        sealed=True,
    )
    fields = manifest.to_cbor()
    fields[key] = None
    encoded = dumps_deterministic(fields)
    document = (
        b"AY\x02\x01"
        + encode_uvarint(len(encoded))
        + encoded
        + encode_uvarint(len(payload))
        + payload
    )
    with pytest.raises(ValueError, match="not allowed"):
        decode_document(document)


@pytest.mark.parametrize(
    "prefix",
    [
        b"",
        b"AY",
        b"ZZ\x02\x01",
        b"AY\x00",
        b"AY\x03",
        b"AY\x82\x00\x01",  # Noncanonical version.
        b"AY\x02",  # Missing kind.
        b"AY\x02\x00",
        b"AY\x02\x03",
        b"AY\x02\x81\x00",  # Noncanonical backup kind.
        b"AY\x02\x82\x00",  # Noncanonical update kind.
        b"AY\x02" + b"\xff" * 10 + b"\x01",  # Kind overflows uint64.
    ],
)
def test_document_readers_reject_invalid_prefixes(prefix):
    for reader in (
        read_document_header,
        decode_document,
        decode_backup_document,
        ExtensionDocument.decode,
    ):
        with pytest.raises(ValueError):
            reader(prefix)


def test_v1_header_does_not_consume_a_kind():
    header = read_document_header(b"AY\x01\x02")
    assert header.version == 1
    assert header.kind == DocumentKind.BACKUP
    assert header.body_offset == 3


def test_backup_header_dispatch_and_wrong_kind_rejection():
    manifest, payload = build_manifest_and_payload(
        [BackupFile("f", b"contents", None)], sealed=True
    )
    encoded = encode_backup_document(payload, manifest)
    header = read_document_header(encoded)
    assert (header.version, header.kind, header.body_offset) == (2, DocumentKind.BACKUP, 4)
    with pytest.raises(ValueError, match="expected update document kind"):
        ExtensionDocument.decode(encoded)
    # A changed kind must select its own decoder, never fall back to the valid backup body.
    with pytest.raises(ValueError):
        decode_document(b"AY\x02\x02" + encoded[4:])
    with pytest.raises(ValueError, match="expected update document kind"):
        ExtensionDocument.decode(legacy_document(manifest, payload))
