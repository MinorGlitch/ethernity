/* Copyright (C) 2026 Alex Stoyanov
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
import { readUvarint } from "../lib/encoding.js";
import {
  DOCUMENT_MAGIC,
  LEGACY_BACKUP_DOCUMENT_VERSION,
  SUPPORTED_DOCUMENT_VERSIONS,
  DOCUMENT_KIND_BACKUP,
  DOCUMENT_KIND_UPDATE,
} from "./constants.js";

export function readDocumentHeader(bytes) {
  if (bytes.length < DOCUMENT_MAGIC.length + 1) throw new Error("document too short");
  if (bytes[0] !== DOCUMENT_MAGIC[0] || bytes[1] !== DOCUMENT_MAGIC[1]) {
    throw new Error("invalid document magic");
  }
  const { value: version, offset } = readUvarint(bytes, DOCUMENT_MAGIC.length);
  if (!SUPPORTED_DOCUMENT_VERSIONS.has(version)) {
    throw new Error(`unsupported document version: ${version}`);
  }
  if (version === LEGACY_BACKUP_DOCUMENT_VERSION) {
    return { version, kind: DOCUMENT_KIND_BACKUP, bodyOffset: offset };
  }
  const { value: kind, offset: bodyOffset } = readUvarint(bytes, offset);
  if (kind !== DOCUMENT_KIND_BACKUP && kind !== DOCUMENT_KIND_UPDATE) {
    throw new Error(`unsupported document kind: ${kind}`);
  }
  return { version, kind, bodyOffset };
}
