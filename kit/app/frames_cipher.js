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

import { blake2b256 } from "../lib/blake2b.js";
import { bytesToHex, hexToBytes } from "../lib/encoding.js";
import { DOC_ID_LEN, MAX_CIPHERTEXT_BYTES } from "./constants.js";
import {
  authOnlyDocumentRecords,
  completeDocumentRecords,
  incompleteDocumentRecords,
  primaryDocumentRecord,
  syncLegacyDocumentFields,
} from "./document_store.js";

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
    const hash = blake2b256(record.ciphertext);
    enforceDerivedDocId(record, hash);
    record.cipherDocHashHex = bytesToHex(hash);
    return hash;
  }
  const hash = hexToBytes(record.cipherDocHashHex);
  enforceDerivedDocId(record, hash);
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
    const docId = docHash.slice(0, DOC_ID_LEN);
    documents.push({
      docId,
      docIdHex: bytesToHex(docId),
      docHash,
      docHashHex: bytesToHex(docHash),
      ciphertext: record.ciphertext,
      authPayload: record.authPayload,
    });
  }
  syncLegacyDocumentFields(state);
  return documents;
}

function enforceDerivedDocId(record, docHash) {
  if (!record.docIdHex) {
    return;
  }
  const derivedDocId = docHash.slice(0, DOC_ID_LEN);
  if (bytesToHex(derivedDocId) !== record.docIdHex) {
    throw new Error("document doc_id does not match derived ciphertext hash");
  }
}
