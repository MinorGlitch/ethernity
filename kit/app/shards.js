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

import { bytesToHex } from "../lib/bytes.js";
import { recoverSecretFromShards } from "../lib/shamir.js";
import { SHARD_KEY_PASSPHRASE, SHARD_KEY_SIGNING_SEED, textDecoder } from "./constants.js";
import { completeDocumentRecords } from "./documents/store.js";
import { ensureDocumentCiphertextAndHash } from "./frames_cipher.js";
import { setStatus } from "./state/initial.js";
import { setErrorStatus } from "./state_actions.js";

function setShardStatus(state, statusPrefix, line, type) {
  const lines = statusPrefix.length ? [...statusPrefix, line] : [line];
  setStatus(state, "shardStatus", lines, type);
}

export function autoRecoverShardSecret(state, statusPrefix = []) {
  clearRecoveredShardSecret(state);
  const candidates = recoveryCandidates(state);
  if (!candidates.length) {
    return false;
  }
  const missingHash = candidates.find(({ record }) => !record.docHashHex);
  if (missingHash) {
    state.activeShardSetKey = missingHash.key;
    setShardStatus(
      state,
      statusPrefix,
      "A recovery sheet is missing its backup fingerprint. Try another copy of that sheet.",
      "error",
    );
    return false;
  }

  let documentBindings;
  try {
    documentBindings = collectedDocumentBindings(state);
  } catch (err) {
    setErrorStatus(
      state,
      "shardStatus",
      err,
      "The backup could not be checked. Try another copy of its pages before using these recovery sheets.",
    );
    state.shardStatus.lines.unshift(...statusPrefix);
    return false;
  }
  if (!documentBindings.size) {
    setShardStatus(
      state,
      statusPrefix,
      "Add all backup pages first so the kit can check that these recovery sheets belong to them.",
      "warn",
    );
    return false;
  }

  const matchingCandidates = candidates
    .map(({ key, record }) => ({
      key,
      record,
      documentBinding: documentBindings.get(record.docHashHex) ?? null,
    }))
    .filter(({ documentBinding }) => documentBinding !== null);
  if (!matchingCandidates.length) {
    setShardStatus(
      state,
      statusPrefix,
      "These recovery sheets do not match the added backup. Check the document IDs.",
      "error",
    );
    return false;
  }

  const signingKeyMatches = matchingCandidates.filter(
    ({ record, documentBinding }) =>
      !documentBinding.authSignPubHex || record.signPubHex === documentBinding.authSignPubHex,
  );
  if (!signingKeyMatches.length) {
    state.activeShardSetKey = matchingCandidates[0].key;
    setShardStatus(
      state,
      statusPrefix,
      "The recovery sheets use a different signing key from the backup. Check that they belong together.",
      "error",
    );
    return false;
  }

  const unambiguousCandidates = signingKeyMatches.filter(
    ({ record }) => (record.conflicts ?? 0) === 0,
  );
  if (!unambiguousCandidates.length) {
    state.activeShardSetKey = signingKeyMatches[0].key;
    setShardStatus(
      state,
      statusPrefix,
      "Two copies of the same recovery sheet contain different data. Start over with one matching set.",
      "error",
    );
    return false;
  }

  const docIdCompatibleCandidates = unambiguousCandidates.filter(
    ({ record }) => !record.docIdHex || record.docIdHex === record.docHashHex.slice(0, 16),
  );
  if (!docIdCompatibleCandidates.length) {
    state.activeShardSetKey = unambiguousCandidates[0].key;
    setShardStatus(
      state,
      statusPrefix,
      "A recovery sheet has an incorrect document ID. Try another copy of that sheet.",
      "error",
    );
    return false;
  }

  const selected = selectRecoveryCandidate(docIdCompatibleCandidates);
  state.activeShardSetKey = selected.key;
  const { record } = selected;
  const unverified = Array.from(record.shardFrames.values()).filter(
    (payload) => payload.signatureVerified !== true,
  );
  if (unverified.length) {
    setShardStatus(
      state,
      statusPrefix,
      "The recovery sheets have not passed their signature checks. Try adding them again or use another browser.",
      "warn",
    );
    return false;
  }

  try {
    const shares = Array.from(record.shardFrames.values());
    const secretBytes = recoverSecretFromShards(shares);
    if (record.keyType === SHARD_KEY_SIGNING_SEED) {
      const recoveredHex = bytesToHex(secretBytes);
      state.recoveredShardSecret = recoveredHex;
    } else if (record.keyType === SHARD_KEY_PASSPHRASE) {
      const recoveredText = textDecoder.decode(secretBytes);
      state.recoveredShardSecret = recoveredText;
      if (!state.agePassphrase) {
        state.agePassphrase = recoveredText;
      }
    } else {
      state.recoveredShardSecret = bytesToHex(secretBytes);
    }
    const recovered = record.keyType === SHARD_KEY_PASSPHRASE ? "passphrase" : "signing key";
    setShardStatus(state, statusPrefix, `Recovered your ${recovered}.`, "ok");
  } catch (err) {
    setErrorStatus(
      state,
      "shardStatus",
      err,
      "The recovery sheets could not be combined. Check that they belong to the same set and try another copy.",
    );
    state.shardStatus.lines.unshift(...statusPrefix);
    return false;
  }
  return true;
}

function recoveryCandidates(state) {
  return Array.from(state.shardSets, ([key, record]) => ({ key, record })).filter(
    ({ record }) => record.threshold && record.shardFrames.size >= record.threshold,
  );
}

function collectedDocumentBindings(state) {
  const hashes = new Map();
  for (const record of completeDocumentRecords(state)) {
    const hash = ensureDocumentCiphertextAndHash(record);
    if (hash) {
      hashes.set(bytesToHex(hash), { authSignPubHex: verifiedAuthSignPubHex(record) });
    }
  }
  return hashes;
}

function verifiedAuthSignPubHex(record) {
  return record.authStatus === "verified" && record.authSignPubHex ? record.authSignPubHex : null;
}

function selectRecoveryCandidate(candidates) {
  return candidates.find(({ record }) => record.keyType === SHARD_KEY_PASSPHRASE) ?? candidates[0];
}

function clearRecoveredShardSecret(state) {
  const previous = state.recoveredShardSecret;
  state.recoveredShardSecret = "";
  if (previous && state.agePassphrase === previous) {
    state.agePassphrase = "";
  }
}
