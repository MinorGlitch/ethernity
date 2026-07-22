/*
 * Copyright (C) 2026 Alex Stoyanov
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along with this program.
 * If not, see <https://www.gnu.org/licenses/>.
 */

import { hexToBytes } from "../lib/bytes.js";
import {
  MAX_CIPHERTEXT_BYTES,
  MAX_RECOVERY_CIPHERTEXT_BYTES,
  MAX_RECOVERY_DOCUMENTS,
} from "./constants.js";
import {
  authOnlyDocumentRecords,
  completeDocumentRecords,
  incompleteDocumentRecords,
  primaryDocumentRecord,
  syncLegacyDocumentFields,
} from "./documents/store.js";
import {
  documentIdentityFromCiphertext,
  documentIdentityFromDocHash,
} from "./documents/identity.js";

export function reassembleCiphertext(source) {
  if (source.total === null || source.mainFrames.size !== source.total) {
    throw new Error("missing frames");
  }
  const chunks = [];
  for (let i = 0; i < source.total; i += 1) {
    const frame = source.mainFrames.get(i);
    if (!frame) throw new Error(`missing frame ${i}`);
    chunks.push(frame.data);
  }
  const totalLen = chunks.reduce((sum, arr) => sum + arr.length, 0);
  if (totalLen > MAX_CIPHERTEXT_BYTES) {
    throw new Error(
      `reassembled payload exceeds MAX_CIPHERTEXT_BYTES (${MAX_CIPHERTEXT_BYTES}): ${totalLen} bytes`,
    );
  }
  const out = new Uint8Array(totalLen);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

export function ensureCiphertextAndHash(state) {
  const primary = primaryDocumentRecord(state);
  if (!primary) {
    return ensureDocumentCiphertextAndHash(state);
  }
  const docHash = ensureDocumentCiphertextAndHash(primary);
  syncLegacyDocumentFields(state);
  return docHash;
}

export function ensureDocumentCiphertextAndHash(record) {
  if (!record.total || record.mainFrames.size !== record.total) {
    return null;
  }
  if (!record.ciphertext) {
    record.ciphertext = reassembleCiphertext(record);
  }
  if (!record.cipherDocHashHex) {
    const identity = documentIdentityFromCiphertext(record.ciphertext);
    enforceDerivedDocId(record, identity);
    record.cipherDocHashHex = identity.docHashHex;
    return identity.docHash;
  }
  const hash = hexToBytes(record.cipherDocHashHex);
  enforceDerivedDocId(record, documentIdentityFromDocHash(hash));
  return hash;
}

export function syncCollectedCiphertext(state) {
  if (!state.documents.size) {
    try {
      ensureDocumentCiphertextAndHash(state);
    } catch {
      // leave ciphertext unset if reassembly fails
    }
    return;
  }
  for (const record of state.documents.values()) {
    try {
      ensureDocumentCiphertextAndHash(record);
    } catch {
      // leave ciphertext unset if reassembly fails
    }
  }
  syncLegacyDocumentFields(state);
}

export function collectedRecoveryDocuments(
  state,
  { allowIncomplete = false, allowAuthOnly = false } = {},
) {
  const incomplete = incompleteDocumentRecords(state);
  if (incomplete.length && !allowIncomplete) {
    const docIds = incomplete.map((record) => record.docIdHex).join(", ");
    throw new Error(`incomplete backup document(s): ${docIds}`);
  }
  const authOnly = authOnlyDocumentRecords(state);
  if (authOnly.length && !allowAuthOnly) {
    const docIds = authOnly.map((record) => record.docIdHex).join(", ");
    throw new Error(`AUTH frame(s) without MAIN document: ${docIds}`);
  }
  const documents = [];
  for (const record of completeDocumentRecords(state)) {
    const docHash = ensureDocumentCiphertextAndHash(record);
    const identity = documentIdentityFromDocHash(docHash);
    documents.push({
      ...identity,
      ciphertext: record.ciphertext,
      authPayload: record.authPayload,
    });
  }
  enforceRecoveryDocumentBudget(documents);
  syncLegacyDocumentFields(state);
  return documents;
}

export function enforceRecoveryDocumentBudget(
  documents,
  { byteField = "ciphertext", byteLabel = "ciphertext" } = {},
) {
  if (documents.length > MAX_RECOVERY_DOCUMENTS) {
    throw new Error(
      `collected backup documents exceed MAX_RECOVERY_DOCUMENTS (${MAX_RECOVERY_DOCUMENTS}): ${documents.length}`,
    );
  }
  let totalBytes = 0;
  for (const document of documents) {
    const bytes = document[byteField];
    if (!(bytes instanceof Uint8Array)) {
      continue;
    }
    if (bytes.length > MAX_CIPHERTEXT_BYTES) {
      throw new Error(
        `collected ${byteLabel} exceeds MAX_CIPHERTEXT_BYTES (${MAX_CIPHERTEXT_BYTES}): ${bytes.length} bytes`,
      );
    }
    totalBytes += bytes.length;
  }
  if (totalBytes > MAX_RECOVERY_CIPHERTEXT_BYTES) {
    throw new Error(
      `collected ${byteLabel} exceeds MAX_RECOVERY_CIPHERTEXT_BYTES (${MAX_RECOVERY_CIPHERTEXT_BYTES}): ${totalBytes} bytes`,
    );
  }
}

function enforceDerivedDocId(record, identity) {
  if (!record.docIdHex) {
    return;
  }
  if (identity.docIdHex !== record.docIdHex) {
    throw new Error("document doc_id does not match derived ciphertext hash");
  }
}
