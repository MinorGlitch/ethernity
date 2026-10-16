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

import { bytesEqual, bytesToHex } from "../lib/bytes.js";

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
        shardFrames: cloneShardFrames(record.shardFrames),
      },
    ]),
  );
}

export function cloneShardFrames(shardFrames) {
  return new Map(
    Array.from(shardFrames.entries(), ([shareIndex, payload]) => [
      shareIndex,
      cloneShardPayload(payload),
    ]),
  );
}

export function cloneShardPayload(payload) {
  return {
    ...payload,
    share: cloneOptionalBytes(payload.share),
    docHash: cloneOptionalBytes(payload.docHash),
    signPub: cloneOptionalBytes(payload.signPub),
    signature: cloneOptionalBytes(payload.signature),
    shardSetId: cloneOptionalBytes(payload.shardSetId),
  };
}

function cloneOptionalBytes(value) {
  return value instanceof Uint8Array ? value.slice() : value;
}

export function activeShardSetRecord(state) {
  return state.shardSets.get(state.activeShardSetKey) ?? null;
}

export function shardCounts(state) {
  let duplicates = 0;
  let conflicts = 0;
  for (const record of state.shardSets.values()) {
    duplicates += record.duplicates;
    conflicts += record.conflicts;
  }
  return { duplicates, conflicts, errors: state.shardErrors };
}

export function addShardPayloadFrame(state, frame, payload) {
  const docIdHex = bytesToHex(frame.docId);
  const key = shardSetKey(docIdHex, payload);
  let record = state.shardSets.get(key);
  if (!record) {
    record = createShardSetRecord(frame.docId, docIdHex, payload);
    state.shardSets.set(key, record);
  } else if (!shardPayloadMatchesRecord(record, payload)) {
    record.conflicts += 1;
    state.activeShardSetKey = key;
    return false;
  }

  const existing = record.shardFrames.get(payload.shareIndex);
  if (existing) {
    if (!bytesEqual(existing.share, payload.share)) {
      record.conflicts += 1;
    } else if (!bytesEqual(existing.signature, payload.signature)) {
      record.conflicts += 1;
    } else {
      record.duplicates += 1;
    }
    state.activeShardSetKey = key;
    return false;
  }

  record.shardFrames.set(payload.shareIndex, payload);
  state.activeShardSetKey = key;
  return true;
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
