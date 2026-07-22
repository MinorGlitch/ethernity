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

import { cloneShardFrames, cloneShardSets } from "../shard_store.js";
import { cloneDocuments } from "../documents/store.js";
import { readEmbeddedKitMetadata } from "../kit_anchor.js";

export function createBaseState() {
  const kitMetadata = readEmbeddedKitMetadata();
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
    expectedHeadDocHashText: kitMetadata?.anchored ? kitMetadata.expectedLatestHeadHashHex : "",
    freshnessUnknownAcknowledged: false,
    trustedKitAnchored: kitMetadata?.anchored === true,
    decryptStatus: { lines: [], type: "" },
    decryptRequestId: 0,
    isDecrypting: false,
    intensiveRecoveryTarget: null,
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
  const shardSets = cloneShardSets(state.shardSets);
  const activeShardSet = state.activeShardSetKey ? shardSets.get(state.activeShardSetKey) : null;
  return {
    ...state,
    documents: cloneDocuments(state.documents),
    shardSets,
    mainFrames: new Map(state.mainFrames),
    shardFrames: activeShardSet ? activeShardSet.shardFrames : cloneShardFrames(state.shardFrames),
    extractedFiles: state.extractedFiles.slice(),
    frameStatus: { ...state.frameStatus },
    shardStatus: { ...state.shardStatus },
    extractStatus: { ...state.extractStatus },
    decryptStatus: { ...state.decryptStatus },
  };
}
