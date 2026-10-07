"""Released documents and current documents normalize to the same recovery model."""

import gzip
from dataclasses import replace

import pytest

from ethernity.encoding.cbor import dumps_deterministic, loads_deterministic
from ethernity.encoding.varint import decode_uvarint, encode_uvarint
from ethernity.formats.document_codec import (
    build_manifest_and_payload,
    decode_document,
    encode_backup_document,
    extract_payloads,
)
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
    assert current[:3] == b"AY\x03"
    length, offset = decode_uvarint(current, 3)
    encoded_fields = loads_deterministic(current[offset : offset + length], label="manifest")
    assert not {"version", "sealed", "payload_raw_len"} & encoded_fields.keys()
    assert encoded_fields["path_encoding"] == ("prefix_table" if nested else "direct")
    for expected_version, document in [(1, legacy_document(manifest, stored)), (3, current)]:
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
        b"AY\x03" + encode_uvarint(len(encoded)) + encoded + encode_uvarint(len(payload)) + payload
    )
    with pytest.raises(ValueError, match="not allowed"):
        decode_document(document)
