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

export function createBaseState() {
  return {
    revision: 0,
    documents: new Map(),
    primaryDocIdHex: null,
    mainFrames: new Map(),
    docIdHex: null,
    total: null,
    duplicates: 0,
    conflicts: 0,
    ignored: 0,
    errors: 0,
    shardSets: new Map(),
    activeShardSetKey: null,
    shardFrames: new Map(),
    shardDocIdHex: null,
    shardVersion: null,
    shardDocHashHex: null,
    shardSignPubHex: null,
    shardSetIdHex: null,
    shardThreshold: null,
    shardShares: null,
    shardKeyType: null,
    shardSecretLen: null,
    shardDuplicates: 0,
    shardConflicts: 0,
    shardErrors: 0,
    recoveredShardSecret: "",
    authPayload: null,
    authDocIdHex: null,
    authDocHashHex: null,
    authSignPubHex: null,
    authSignatureHex: null,
    authStatus: "missing",
    authDuplicates: 0,
    authConflicts: 0,
    authErrors: 0,
    cipherDocHashHex: null,
    ciphertext: null,
    decryptedEnvelope: null,
    decryptedEnvelopeSource: "",
    extractedFiles: [],
    frameStatus: { lines: [], type: "" },
    shardStatus: { lines: [], type: "" },
    extractStatus: { lines: [], type: "" },
    payloadText: "",
    shardPayloadText: "",
    agePassphrase: "",
    extensionTargetText: "latest",
    expectedHeadDocHashText: "",
    decryptStatus: { lines: [], type: "" },
    decryptRequestId: 0,
    isDecrypting: false,
    isAddingFrames: false,
    isAddingShards: false,
    recoveryComplete: false,
  };
}

export function createInitialState() {
  const state = createBaseState();
  setStatus(state, "frameStatus", ["State cleared."]);
  setStatus(state, "shardStatus", ["Shard state cleared."]);
  setStatus(state, "extractStatus", []);
  setStatus(state, "decryptStatus", []);
  return state;
}

export function setStatus(state, key, lines, type = "") {
  state[key] = { lines, type };
}

export function resetState(state) {
  Object.assign(state, createBaseState());
  setStatus(state, "frameStatus", ["State cleared."]);
  setStatus(state, "shardStatus", ["Shard state cleared."]);
  setStatus(state, "extractStatus", []);
  setStatus(state, "decryptStatus", []);
}

export function bumpError(state, key) {
  state[key] += 1;
}

export function cloneState(state) {
  return {
    ...state,
    documents: new Map(
      Array.from(state.documents.entries(), ([docIdHex, record]) => [
        docIdHex,
        {
          ...record,
          docId: record.docId.slice(),
          mainFrames: new Map(record.mainFrames),
        },
      ]),
    ),
    shardSets: new Map(
      Array.from(state.shardSets.entries(), ([key, record]) => [
        key,
        {
          ...record,
          docId: record.docId.slice(),
          shardFrames: new Map(record.shardFrames),
        },
      ]),
    ),
    mainFrames: new Map(state.mainFrames),
    shardFrames: new Map(state.shardFrames),
    extractedFiles: state.extractedFiles.slice(),
    frameStatus: { ...state.frameStatus },
    shardStatus: { ...state.shardStatus },
    extractStatus: { ...state.extractStatus },
    decryptStatus: { ...state.decryptStatus },
  };
}
