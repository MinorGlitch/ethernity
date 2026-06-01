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

function shardSetIdHex(payload) {
  return payload.shardSetId ? bytesToHex(payload.shardSetId) : "";
}

function shardDocHashHex(payload) {
  return bytesToHex(payload.docHash);
}

function shardSignPubHex(payload) {
  return bytesToHex(payload.signPub);
}

function shardSetKey(docIdHex, payload) {
  return [
    docIdHex,
    payload.version,
    payload.keyType,
    payload.threshold,
    payload.shareCount,
    payload.secretLen,
    shardDocHashHex(payload),
    shardSignPubHex(payload),
    shardSetIdHex(payload),
  ].join(":");
}

function createShardSetRecord(docId, docIdHex, payload) {
  return {
    docId: docId.slice(),
    docIdHex,
    version: payload.version,
    threshold: payload.threshold,
    shareCount: payload.shareCount,
    keyType: payload.keyType,
    secretLen: payload.secretLen,
    docHashHex: shardDocHashHex(payload),
    signPubHex: shardSignPubHex(payload),
    shardSetIdHex: shardSetIdHex(payload),
    shardFrames: new Map(),
    duplicates: 0,
    conflicts: 0,
  };
}

export function cloneShardSets(shardSets) {
  return new Map(
    Array.from(shardSets.entries(), ([key, record]) => [
      key,
      {
        ...record,
        docId: record.docId.slice(),
        shardFrames: new Map(record.shardFrames),
      },
    ]),
  );
}

export function syncLegacyShardFields(state, preferredKey = state.activeShardSetKey) {
  if (!state.shardSets?.size) {
    return;
  }
  let key = preferredKey;
  let record = key ? state.shardSets.get(key) : null;
  if (!record) {
    [key, record] = state.shardSets.entries().next().value;
  }
  state.activeShardSetKey = key;
  state.shardFrames = record.shardFrames;
  state.shardDocIdHex = record.docIdHex;
  state.shardVersion = record.version;
  state.shardDocHashHex = record.docHashHex;
  state.shardSignPubHex = record.signPubHex;
  state.shardSetIdHex = record.shardSetIdHex || null;
  state.shardThreshold = record.threshold;
  state.shardShares = record.shareCount;
  state.shardKeyType = record.keyType;
  state.shardSecretLen = record.secretLen;
}

export function addShardPayloadFrame(state, frame, payload) {
  const docIdHex = bytesToHex(frame.docId);
  const key = shardSetKey(docIdHex, payload);
  let record = state.shardSets.get(key);
  if (!record) {
    record = createShardSetRecord(frame.docId, docIdHex, payload);
    state.shardSets.set(key, record);
  } else if (!shardPayloadMatchesRecord(record, payload)) {
    state.shardConflicts += 1;
    record.conflicts += 1;
    syncLegacyShardFields(state, key);
    return false;
  }

  const existing = record.shardFrames.get(payload.shareIndex);
  if (existing) {
    if (!bytesEqual(existing.share, payload.share)) {
      state.shardConflicts += 1;
      record.conflicts += 1;
    } else if (!bytesEqual(existing.signature, payload.signature)) {
      state.shardConflicts += 1;
      record.conflicts += 1;
    } else {
      state.shardDuplicates += 1;
      record.duplicates += 1;
    }
    syncLegacyShardFields(state, key);
    return false;
  }

  record.shardFrames.set(payload.shareIndex, payload);
  syncLegacyShardFields(state, key);
  return true;
}

export function shardSetRecords(state) {
  if (state.shardSets?.size) {
    return Array.from(state.shardSets.entries()).map(([key, record]) => ({ key, record }));
  }
  if (!state.shardFrames?.size) {
    return [];
  }
  return [
    {
      key: null,
      record: {
        docIdHex: state.shardDocIdHex,
        version: state.shardVersion,
        threshold: state.shardThreshold,
        shareCount: state.shardShares,
        keyType: state.shardKeyType,
        secretLen: state.shardSecretLen,
        docHashHex: state.shardDocHashHex,
        signPubHex: state.shardSignPubHex,
        shardSetIdHex: state.shardSetIdHex,
        shardFrames: state.shardFrames,
      },
    },
  ];
}

export function activateShardSet(state, key) {
  if (key === null) {
    return;
  }
  syncLegacyShardFields(state, key);
}

function shardPayloadMatchesRecord(record, payload) {
  return (
    record.version === payload.version &&
    record.threshold === payload.threshold &&
    record.shareCount === payload.shareCount &&
    record.keyType === payload.keyType &&
    record.secretLen === payload.secretLen &&
    record.docHashHex === shardDocHashHex(payload) &&
    record.signPubHex === shardSignPubHex(payload) &&
    record.shardSetIdHex === shardSetIdHex(payload)
  );
}
