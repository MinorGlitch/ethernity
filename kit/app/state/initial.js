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

import { cloneShardSets } from "../shard_store.js";
import { cloneDocuments } from "../documents/store.js";
import { readEmbeddedKitMetadata } from "../kit_metadata.js";

export function createBaseState() {
  readEmbeddedKitMetadata();
  return {
    revision: 0,
    documents: new Map(),
    primaryDocIdHex: null,
    ignored: 0,
    errors: 0,
    authParseErrors: 0,
    shardSets: new Map(),
    activeShardSetKey: null,
    shardErrors: 0,
    recoveredShardSecret: "",
    decryptedBackup: null,
    extractedFiles: [],
    frameStatus: { lines: [], type: "" },
    shardStatus: { lines: [], type: "" },
    extractStatus: { lines: [], type: "" },
    payloadText: "",
    shardPayloadText: "",
    agePassphrase: "",
    extensionTargetText: "latest",
    expectedHeadDocHashText: "",
    freshnessUnknownAcknowledged: false,
    decryptStatus: { lines: [], type: "" },
    decryptRequestId: 0,
    isDecrypting: false,
    frameRequestId: 0,
    shardRequestId: 0,
    isAddingFrames: false,
    isAddingShards: false,
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
  Object.assign(state, createInitialState());
}

export function bumpError(state, key) {
  state[key] += 1;
}

export function cloneState(state) {
  return {
    ...state,
    documents: cloneDocuments(state.documents),
    shardSets: cloneShardSets(state.shardSets),
    extractedFiles: state.extractedFiles.slice(),
    frameStatus: { ...state.frameStatus },
    shardStatus: { ...state.shardStatus },
    extractStatus: { ...state.extractStatus },
    decryptStatus: { ...state.decryptStatus },
  };
}
