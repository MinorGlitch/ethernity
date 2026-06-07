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

import { bumpError, cloneState, setStatus } from "./state/initial.js";
import { cloneDocuments } from "./document_store.js";
import { cloneShardFrames, cloneShardSets } from "./shard_store.js";

export function dispatchState(dispatch, state) {
  dispatch({
    type: "MUTATE_STATE",
    baseRevision: state.revision,
    mutate(next) {
      for (const key of Object.keys(next)) {
        if (key === "revision") {
          continue;
        }
        next[key] = state[key];
      }
      next.documents = cloneDocuments(state.documents);
      next.shardSets = cloneShardSets(state.shardSets);
      next.activeShardSetKey = state.activeShardSetKey;
      next.mainFrames = new Map(state.mainFrames);
      next.shardFrames = clonedLegacyShardFrames(state, next.shardSets);
      next.extractedFiles = state.extractedFiles.slice();
      next.frameStatus = { ...state.frameStatus };
      next.shardStatus = { ...state.shardStatus };
      next.extractStatus = { ...state.extractStatus };
      next.decryptStatus = { ...state.decryptStatus };
    },
  });
}

export function dispatchReset(dispatch) {
  dispatch({ type: "RESET" });
}

export function dispatchPatch(dispatch, getState, patch) {
  const current = getState();
  dispatch({ type: "PATCH_STATE", patch, baseRevision: current.revision });
}

export function dispatchMutate(dispatch, getState, mutate) {
  const current = getState();
  dispatch({ type: "MUTATE_STATE", mutate, baseRevision: current.revision });
}

export function cloneLatest(getState) {
  return cloneState(getState());
}

export function copyAuthAndCipherFields(target, source) {
  target.documents = cloneDocuments(source.documents);
  target.primaryDocIdHex = source.primaryDocIdHex;
  target.mainFrames = new Map(source.mainFrames);
  target.total = source.total;
  target.docIdHex = source.docIdHex;
  target.authPayload = source.authPayload;
  target.authDocIdHex = source.authDocIdHex;
  target.authDocHashHex = source.authDocHashHex;
  target.authSignPubHex = source.authSignPubHex;
  target.authSignatureHex = source.authSignatureHex;
  target.authStatus = source.authStatus;
  target.ciphertext = source.ciphertext;
  target.cipherDocHashHex = source.cipherDocHashHex;
}

export function copyShardAsyncFields(target, source) {
  target.shardSets = cloneShardSets(source.shardSets);
  target.activeShardSetKey = source.activeShardSetKey;
  target.shardFrames = clonedLegacyShardFrames(source, target.shardSets);
  target.shardDocIdHex = source.shardDocIdHex;
  target.shardVersion = source.shardVersion;
  target.shardDocHashHex = source.shardDocHashHex;
  target.shardSignPubHex = source.shardSignPubHex;
  target.shardSetIdHex = source.shardSetIdHex;
  target.shardThreshold = source.shardThreshold;
  target.shardShares = source.shardShares;
  target.shardKeyType = source.shardKeyType;
  target.shardSecretLen = source.shardSecretLen;
  target.shardDuplicates = source.shardDuplicates;
  target.shardConflicts = source.shardConflicts;
  target.shardErrors = source.shardErrors;
  target.recoveredShardSecret = source.recoveredShardSecret;
  target.agePassphrase = source.agePassphrase;
  target.shardStatus = { ...source.shardStatus };
  target.documents = cloneDocuments(source.documents);
  target.ciphertext = source.ciphertext;
  target.cipherDocHashHex = source.cipherDocHashHex;
}

function clonedLegacyShardFrames(source, clonedShardSets) {
  const active = source.activeShardSetKey ? clonedShardSets.get(source.activeShardSetKey) : null;
  return active ? active.shardFrames : cloneShardFrames(source.shardFrames);
}

export function setLineStatus(state, key, line, type = "") {
  setStatus(state, key, [line], type);
}

export function setErrorStatus(state, key, err) {
  setLineStatus(state, key, String(err), "error");
}

export function parseTextWithErrors(state, text, parseFn, errorKey) {
  let added = 0;
  let failed = false;
  try {
    added += parseFn(state, text);
  } catch {
    bumpError(state, errorKey);
    failed = true;
  }
  return { added, failed };
}

export function clearRecoveredOutput(state) {
  state.extractedFiles = [];
  setStatus(state, "extractStatus", []);
}

export function clearDecryptedEnvelope(state) {
  state.decryptedEnvelope = null;
  state.decryptedEnvelopeSource = "";
}

export function clearRecoveryResult(state) {
  clearRecoveredOutput(state);
  clearDecryptedEnvelope(state);
  state.recoveryComplete = false;
  setStatus(state, "decryptStatus", []);
}

export function cancelDecryptRequest(state) {
  if (!state.isDecrypting) {
    return;
  }
  state.isDecrypting = false;
  state.decryptRequestId += 1;
}

export function applyExtractResult(state, result) {
  state.extractedFiles = result.files;
  setLineStatus(state, "extractStatus", `${result.files.length} file(s) ready.`, "ok");
}
