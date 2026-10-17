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

import { RecoveryError } from "../lib/errors.js";
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
  documentCounts,
} from "./documents/store.js";
import {
  documentIdentityFromCiphertext,
  documentIdentityFromDocHash,
} from "./documents/identity.js";

export function reassembleCiphertext(source) {
  if (source.total === null || source.mainFrames.size !== source.total) {
    throw new Error("Add all parts of this backup before continuing.");
  }
  const chunks = [];
  for (let i = 0; i < source.total; i += 1) {
    const frame = source.mainFrames.get(i);
    if (!frame)
      throw new Error(`A backup part is missing (data index ${i}). Add the remaining pages.`);
    chunks.push(frame.data);
  }
  const totalLen = chunks.reduce((sum, arr) => sum + arr.length, 0);
  if (totalLen > MAX_CIPHERTEXT_BYTES) {
    throw new Error(
      `This backup is too large for the kit (${totalLen} bytes; limit ${MAX_CIPHERTEXT_BYTES}). Use the Ethernity app to recover it.`,
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
  for (const record of state.documents.values()) {
    try {
      ensureDocumentCiphertextAndHash(record);
    } catch {
      // leave ciphertext unset if reassembly fails
    }
  }
}

// Shared by the controls and recovery action. This inspects collection readiness;
// ciphertext identity, resource limits, and signatures are still checked during recovery.
export function inspectCollectedDocuments(
  state,
  { allowIncomplete = false, allowAuthOnly = false } = {},
) {
  const counts = documentCounts(state);
  const complete = completeDocumentRecords(state);
  const incomplete = incompleteDocumentRecords(state);
  const authOnly = authOnlyDocumentRecords(state);
  let error = null;
  if (counts.conflicts) {
    error = new RecoveryError(
      "DOCUMENT_INVALID",
      "Two copies of the same backup part contain different data. Start over with one matching page set.",
    );
  } else if (counts.authConflicts) {
    error = new RecoveryError("AUTH_CONFLICT", "conflicting AUTH frames detected");
  } else if (counts.authErrors) {
    error = new RecoveryError("AUTH_PAYLOAD_INVALID", "invalid AUTH frames detected");
  } else if (incomplete.length && !allowIncomplete) {
    error = new Error(
      `Add the missing pages for these documents: ${incomplete.map((record) => record.docIdHex).join(", ")}.`,
    );
  } else if (authOnly.length && !allowAuthOnly) {
    error = new Error(
      `Add the MAIN section for these documents: ${authOnly.map((record) => record.docIdHex).join(", ")}. Only their AUTH section has been added.`,
    );
  } else if (!complete.length) {
    error = new RecoveryError("INPUT_REQUIRED", "Collected ciphertext not available yet.");
  }
  return { complete, incomplete, authOnly, error };
}

export function collectedRecoveryDocuments(state, options) {
  const selection = inspectCollectedDocuments(state, options);
  if (selection.error) throw selection.error;
  const documents = [];
  for (const record of selection.complete) {
    const docHash = ensureDocumentCiphertextAndHash(record);
    const identity = documentIdentityFromDocHash(docHash);
    documents.push({
      ...identity,
      ciphertext: record.ciphertext,
      authPayload: record.authPayload,
    });
  }
  enforceRecoveryDocumentBudget(documents);
  return documents;
}

export function enforceRecoveryDocumentBudget(
  documents,
  { byteField = "ciphertext", byteLabel = "ciphertext" } = {},
) {
  if (documents.length > MAX_RECOVERY_DOCUMENTS) {
    throw new RecoveryError(
      "RECOVERY_RESOURCE_LIMIT",
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
      throw new RecoveryError(
        "RECOVERY_RESOURCE_LIMIT",
        `collected ${byteLabel} exceeds MAX_CIPHERTEXT_BYTES (${MAX_CIPHERTEXT_BYTES}): ${bytes.length} bytes`,
      );
    }
    totalBytes += bytes.length;
  }
  if (totalBytes > MAX_RECOVERY_CIPHERTEXT_BYTES) {
    throw new RecoveryError(
      "RECOVERY_RESOURCE_LIMIT",
      `collected ${byteLabel} exceeds MAX_RECOVERY_CIPHERTEXT_BYTES (${MAX_RECOVERY_CIPHERTEXT_BYTES}): ${totalBytes} bytes`,
    );
  }
}

function enforceDerivedDocId(record, identity) {
  if (!record.docIdHex) {
    return;
  }
  if (identity.docIdHex !== record.docIdHex) {
    throw new Error(
      "The document ID does not match the backup data. Start over with another copy of the matching pages.",
    );
  }
}
