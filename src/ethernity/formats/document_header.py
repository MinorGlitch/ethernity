"""Shared document prefix, with an implicit backup kind for released v1 documents."""

from dataclasses import dataclass

from ethernity.encoding.varint import decode_uvarint, encode_uvarint
from ethernity.formats.document_constants import (
    LEGACY_VERSION,
    MAGIC,
    SUPPORTED_DOCUMENT_VERSIONS,
    VERSION,
    DocumentKind,
)


@dataclass(frozen=True)
class DocumentHeader:
    version: int
    kind: DocumentKind
    body_offset: int


def encode_document_header(kind: DocumentKind) -> bytes:
    return MAGIC + encode_uvarint(VERSION) + encode_uvarint(DocumentKind(kind))


def read_document_header(data: bytes) -> DocumentHeader:
    if len(data) < len(MAGIC) + 1:
        raise ValueError("document too short")
    if data[: len(MAGIC)] != MAGIC:
        raise ValueError("invalid document magic")
    version, offset = decode_uvarint(data, len(MAGIC))
    if version not in SUPPORTED_DOCUMENT_VERSIONS:
        raise ValueError(f"unsupported document version: {version}")
    kind = DocumentKind.BACKUP
    if version != LEGACY_VERSION:
        value, offset = decode_uvarint(data, offset)
        try:
            kind = DocumentKind(value)
        except ValueError:
            raise ValueError(f"unsupported document kind: {value}") from None
    return DocumentHeader(version, kind, offset)
