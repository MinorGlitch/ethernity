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

import { bytesEqual, bytesToHex } from "../lib/encoding.js";
import { decodeAuthPayload } from "./frames_protocol.js";

function createDocumentRecord(docId) {
  return {
    docId,
    docIdHex: bytesToHex(docId),
    total: null,
    mainFrames: new Map(),
    duplicates: 0,
    conflicts: 0,
    authPayload: null,
    authDocHashHex: null,
    authSignPubHex: null,
    authSignatureHex: null,
    authDuplicates: 0,
    authConflicts: 0,
    authErrors: 0,
    authStatus: "missing",
    ciphertext: null,
    cipherDocHashHex: null,
  };
}

export function cloneDocumentRecord(record) {
  return {
    ...record,
    docId: record.docId.slice(),
    mainFrames: new Map(record.mainFrames),
  };
}

export function cloneDocuments(documents) {
  return new Map(
    Array.from(documents.entries(), ([docIdHex, record]) => [
      docIdHex,
      cloneDocumentRecord(record),
    ]),
  );
}

export function getOrCreateDocumentRecord(state, docId) {
  const docIdHex = bytesToHex(docId);
  let record = state.documents.get(docIdHex);
  if (!record) {
    record = createDocumentRecord(docId);
    state.documents.set(docIdHex, record);
  }
  return record;
}

export function addMainDocumentFrame(state, frame) {
  const record = getOrCreateDocumentRecord(state, frame.docId);
  if (!state.primaryDocIdHex) {
    state.primaryDocIdHex = record.docIdHex;
  }
  if (record.total === null) {
    record.total = frame.total;
  } else if (record.total !== frame.total) {
    record.conflicts += 1;
    syncLegacyDocumentFields(state);
    return false;
  }
  if (record.mainFrames.has(frame.index)) {
    const existing = record.mainFrames.get(frame.index);
    if (!bytesEqual(existing.data, frame.data) || existing.total !== frame.total) {
      record.conflicts += 1;
    } else {
      record.duplicates += 1;
    }
    syncLegacyDocumentFields(state);
    return false;
  }
  record.mainFrames.set(frame.index, frame);
  record.ciphertext = null;
  record.cipherDocHashHex = null;
  syncLegacyDocumentFields(state);
  return true;
}

export function addAuthDocumentFrame(state, frame) {
  const record = getOrCreateDocumentRecord(state, frame.docId);
  if (frame.total !== 1 || frame.index !== 0) {
    record.authErrors += 1;
    syncLegacyDocumentFields(state);
    return false;
  }
  let payload;
  try {
    payload = decodeAuthPayload(frame.data);
  } catch {
    record.authErrors += 1;
    record.authStatus = "invalid payload";
    syncLegacyDocumentFields(state);
    return false;
  }
  if (record.authPayload) {
    if (!authPayloadsEqual(record.authPayload, payload)) {
      record.authConflicts += 1;
      record.authStatus = "conflicting auth payloads";
      syncLegacyDocumentFields(state);
      return false;
    }
    record.authDuplicates += 1;
    syncLegacyDocumentFields(state);
    return true;
  }
  record.authPayload = payload;
  record.authDocHashHex = bytesToHex(payload.docHash);
  record.authSignPubHex = bytesToHex(payload.signPub);
  record.authSignatureHex = bytesToHex(payload.signature);
  record.authStatus = "pending";
  syncLegacyDocumentFields(state);
  return true;
}

export function syncLegacyDocumentFields(state) {
  const primary = primaryDocumentRecord(state);
  state.duplicates = sumDocumentField(state.documents, "duplicates");
  state.conflicts = sumDocumentField(state.documents, "conflicts");
  state.authDuplicates = sumDocumentField(state.documents, "authDuplicates");
  state.authConflicts = sumDocumentField(state.documents, "authConflicts");
  state.authErrors = sumDocumentField(state.documents, "authErrors");
  if (!primary) {
    state.docIdHex = null;
    state.total = null;
    state.mainFrames = new Map();
    state.authPayload = null;
    state.authDocIdHex = null;
    state.authDocHashHex = null;
    state.authSignPubHex = null;
    state.authSignatureHex = null;
    state.authStatus = "missing";
    state.ciphertext = null;
    state.cipherDocHashHex = null;
    return;
  }
  state.docIdHex = primary.docIdHex;
  state.total = primary.total;
  state.mainFrames = primary.mainFrames;
  state.authPayload = primary.authPayload;
  state.authDocIdHex = primary.authPayload ? primary.docIdHex : null;
  state.authDocHashHex = primary.authDocHashHex;
  state.authSignPubHex = primary.authSignPubHex;
  state.authSignatureHex = primary.authSignatureHex;
  state.authStatus = primary.authStatus;
  state.ciphertext = primary.ciphertext;
  state.cipherDocHashHex = primary.cipherDocHashHex;
}

export function primaryDocumentRecord(state) {
  if (!state.primaryDocIdHex) return null;
  return state.documents.get(state.primaryDocIdHex) ?? null;
}

export function completeDocumentRecords(state) {
  const records = [];
  for (const record of state.documents.values()) {
    if (record.total !== null && record.mainFrames.size === record.total) {
      records.push(record);
    }
  }
  return records;
}

export function incompleteDocumentRecords(state) {
  const records = [];
  for (const record of state.documents.values()) {
    if (record.total !== null && record.mainFrames.size !== record.total) {
      records.push(record);
    }
  }
  return records;
}

export function authOnlyDocumentRecords(state) {
  const records = [];
  for (const record of state.documents.values()) {
    if (record.total === null && (record.authPayload || record.authErrors > 0)) {
      records.push(record);
    }
  }
  return records;
}

function sumDocumentField(documents, key) {
  let total = 0;
  for (const record of documents.values()) {
    total += record[key] ?? 0;
  }
  return total;
}

function authPayloadsEqual(left, right) {
  return (
    left.version === right.version &&
    bytesEqual(left.docHash, right.docHash) &&
    bytesEqual(left.signPub, right.signPub) &&
    bytesEqual(left.signature, right.signature)
  );
}
