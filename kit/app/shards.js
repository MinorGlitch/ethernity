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

import { bytesToHex } from "../lib/encoding.js";
import { recoverSecretFromShards } from "../lib/shamir.js";
import { SHARD_KEY_PASSPHRASE, SHARD_KEY_SIGNING_SEED, textDecoder } from "./constants.js";
import { completeDocumentRecords } from "./document_store.js";
import { ensureCiphertextAndHash, ensureDocumentCiphertextAndHash } from "./frames_cipher.js";
import { activateShardSet, shardSetRecords } from "./shard_store.js";
import { setStatus } from "./state/initial.js";

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
    activateShardSet(state, missingHash.key);
    setShardStatus(
      state,
      statusPrefix,
      "Shard recovery blocked: shard payload hash is missing.",
      "error",
    );
    return false;
  }

  let documentBindings;
  try {
    documentBindings = collectedDocumentBindings(state);
  } catch (err) {
    setShardStatus(state, statusPrefix, `Shard recovery blocked: ${String(err)}`, "error");
    return false;
  }
  if (!documentBindings.size) {
    setShardStatus(
      state,
      statusPrefix,
      "Shard recovery blocked: collect main frames to derive ciphertext hash.",
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
      "Shard recovery blocked: shard hash does not match collected ciphertext.",
      "error",
    );
    return false;
  }

  const authorityCompatibleCandidates = matchingCandidates.filter(
    ({ record, documentBinding }) =>
      !documentBinding.authSignPubHex || record.signPubHex === documentBinding.authSignPubHex,
  );
  if (!authorityCompatibleCandidates.length) {
    activateShardSet(state, matchingCandidates[0].key);
    setShardStatus(
      state,
      statusPrefix,
      "Shard recovery blocked: shard signing key does not match verified document AUTH.",
      "error",
    );
    return false;
  }

  const unambiguousCandidates = authorityCompatibleCandidates.filter(
    ({ record }) => (record.conflicts ?? 0) === 0,
  );
  if (!unambiguousCandidates.length) {
    activateShardSet(state, authorityCompatibleCandidates[0].key);
    setShardStatus(
      state,
      statusPrefix,
      "Shard recovery blocked: conflicting shard frames for the selected shard set.",
      "error",
    );
    return false;
  }

  const docIdCompatibleCandidates = unambiguousCandidates.filter(
    ({ record }) => !record.docIdHex || record.docIdHex === record.docHashHex.slice(0, 16),
  );
  if (!docIdCompatibleCandidates.length) {
    activateShardSet(state, unambiguousCandidates[0].key);
    setShardStatus(
      state,
      statusPrefix,
      "Shard recovery blocked: shard frame doc_id does not match shard hash.",
      "error",
    );
    return false;
  }

  const selected = selectRecoveryCandidate(docIdCompatibleCandidates);
  activateShardSet(state, selected.key);
  const { record } = selected;
  const unverified = Array.from(record.shardFrames.values()).filter(
    (payload) => payload.signatureVerified !== true,
  );
  if (unverified.length) {
    setShardStatus(
      state,
      statusPrefix,
      "Shard recovery blocked: verify shard signatures first.",
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
    setShardStatus(state, statusPrefix, "Recovered shard secret from shard documents.", "ok");
  } catch (err) {
    setShardStatus(state, statusPrefix, String(err), "error");
    return false;
  }
  return true;
}

function recoveryCandidates(state) {
  return shardSetRecords(state).filter(
    ({ record }) => record.threshold && record.shardFrames.size >= record.threshold,
  );
}

function collectedDocumentBindings(state) {
  if (!state.documents?.size) {
    const cipherHash = ensureCiphertextAndHash(state);
    return cipherHash
      ? new Map([[bytesToHex(cipherHash), { authSignPubHex: verifiedAuthSignPubHex(state) }]])
      : new Map();
  }
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
