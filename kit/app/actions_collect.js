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

import { clearRecoveryResult, dispatchPatch } from "./state_actions.js";
import { cancelActiveDecryptWork } from "./actions_recover.js";
import { updateAuthStatus } from "./auth.js";
import { syncCollectedCiphertext } from "./frames_cipher.js";
import {
  parseAutoPayload,
  parseAutoShard,
  parseScannedPayload,
  parseScannedShard,
} from "./frames_parse.js";
import { verifyCollectedShardSignatures } from "./shard_auth.js";
import { autoRecoverShardSecret } from "./shards.js";
import { cloneState, setStatus, bumpError } from "./state/initial.js";
import { documentCounts } from "./documents/store.js";
import { shardCounts } from "./shard_store.js";

let collectionQueue = Promise.resolve();

const RECOVERY_INPUT_FIELDS = new Set([
  "payloadText",
  "shardPayloadText",
  "agePassphrase",
  "extensionTargetText",
  "expectedHeadDocHashText",
  "freshnessUnknownAcknowledged",
]);

const BACKUP_COLLECTION = {
  text: "payloadText",
  busy: "isAddingFrames",
  request: "frameRequestId",
  status: "frameStatus",
  error: "errors",
  counts: documentCounts,
  parse: parseAutoPayload,
  scan: parseScannedPayload,
  issues: ["errors", "conflicts", "ignored", "authErrors", "authConflicts"],
};
const SHARD_COLLECTION = {
  text: "shardPayloadText",
  busy: "isAddingShards",
  request: "shardRequestId",
  status: "shardStatus",
  error: "shardErrors",
  counts: shardCounts,
  parse: parseAutoShard,
  scan: parseScannedShard,
  issues: ["errors", "conflicts"],
};

function collectionStatus(collection, added, failed, counts, before, scanned) {
  const shard = collection === SHARD_COLLECTION;
  const item = shard ? "recovery sheet" : "backup part";
  // AUTH copies count as parsed input, but do not add a new backup part.
  const newParts = added - ((counts.authDuplicates ?? 0) - (before.authDuplicates ?? 0));
  const lines = newParts > 0 ? [`Added ${newParts} ${item}${newParts === 1 ? "" : "s"}.`] : [];
  let type = "";
  if (counts.conflicts || counts.authConflicts) {
    lines.push(
      "Two copies of the same part contain different data. Start over with one matching page set.",
    );
    type = "error";
  } else if (counts.authErrors) {
    lines.push(
      "An AUTH section could not be read. Start over and add it again from the matching backup.",
    );
    type = "error";
  } else if (failed) {
    lines.push(
      scanned
        ? `This QR code could not be read as ${shard ? "a recovery sheet" : "backup data"}. Try scanning it again or paste the text from the page.`
        : `Some text could not be read. Copy the complete ${shard ? "recovery sheet" : "backup"} text and try again.`,
    );
    type = "error";
  } else if (counts.ignored > before.ignored) {
    lines.push("This QR code is not backup data. Use the codes from your backup pages.");
    type = "warn";
  }
  if (!lines.length) {
    const duplicates =
      counts.duplicates -
      before.duplicates +
      ((counts.authDuplicates ?? 0) - (before.authDuplicates ?? 0));
    lines.push(
      duplicates > 0
        ? "Already added. Continue with the next page or QR code."
        : `Paste the ${shard ? "recovery sheet" : "backup"} text first.`,
    );
  }
  return { lines, type };
}

async function collect(dispatch, getState, collection, scanned) {
  if (getState()[collection.busy]) return;
  const parsed = cloneState(getState());
  const before = collection.counts(parsed);
  const fromScan = scanned !== undefined;
  const { added, failed } = fromScan
    ? { added: collection.scan(parsed, scanned), failed: false }
    : parseTextWithErrors(parsed, parsed[collection.text], collection.parse, collection.error);
  const counts = collection.counts(parsed);
  const hasIssues = collection.issues.some((key) => counts[key] !== before[key]);
  if (added > 0 || failed || hasIssues) {
    cancelRecoveryDecrypt(parsed);
    clearRecoveryResult(parsed);
  }
  if (added > 0 && !hasIssues) parsed[collection.text] = "";
  parsed[collection.busy] = true;
  const requestId = parsed.revision + 1;
  parsed[collection.request] = requestId;
  const status = collectionStatus(
    collection,
    added,
    failed || counts.errors > before.errors,
    counts,
    before,
    fromScan,
  );
  setStatus(parsed, collection.status, status.lines, status.type);
  dispatchPatch(dispatch, getState, parsed);
  // Collection verification owns the document and shard records. A later collection
  // verifies the latest records, so an older snapshot never needs to be merged into it.
  const run = collectionQueue.then(() =>
    finishCollection(dispatch, getState, collection, requestId, status),
  );
  collectionQueue = run.catch(() => {});
  try {
    await run;
  } finally {
    if (getState()[collection.request] === requestId) {
      dispatchPatch(dispatch, getState, { [collection.busy]: false });
    }
  }
}

async function finishCollection(dispatch, getState, collection, requestId, status) {
  const base = getState();
  if (base[collection.request] !== requestId) return;
  const work = cloneState(base);
  await updateAuthStatus(work);
  syncCollectedCiphertext(work);
  const shard = collection === SHARD_COLLECTION;
  await verifyAndRecoverShardSecret(work, shard ? status.lines : [], shard ? status.type : "");
  const current = getState();
  if (
    current[collection.request] !== requestId ||
    current.documents !== base.documents ||
    current.shardSets !== base.shardSets
  )
    return;

  const patch = {
    documents: work.documents,
    shardSets: work.shardSets,
    activeShardSetKey: work.activeShardSetKey,
    recoveredShardSecret: work.recoveredShardSecret,
    shardStatus: work.shardStatus,
  };
  // A user-entered passphrase always wins over a recovery that finished later.
  if (current.agePassphrase === base.agePassphrase && work.agePassphrase !== base.agePassphrase) {
    cancelRecoveryDecrypt(patch, current);
    clearRecoveryResult(patch);
    patch.agePassphrase = work.agePassphrase;
  }
  dispatchPatch(dispatch, getState, patch);
}

function parseTextWithErrors(state, text, parse, errorKey) {
  try {
    return { added: parse(state, text), failed: false };
  } catch {
    bumpError(state, errorKey);
    return { added: 0, failed: true };
  }
}

export function addPayloads(dispatch, getState) {
  return collect(dispatch, getState, BACKUP_COLLECTION);
}

export function addScannedPayload(dispatch, getState, scanned) {
  return collect(dispatch, getState, BACKUP_COLLECTION, scanned);
}

export function addShardPayloads(dispatch, getState) {
  return collect(dispatch, getState, SHARD_COLLECTION);
}

export function addScannedShardPayload(dispatch, getState, scanned) {
  return collect(dispatch, getState, SHARD_COLLECTION, scanned);
}

async function verifyAndRecoverShardSecret(work, baseStatusLines = [], baseStatusType = "") {
  const signatureLines = [];
  let signatureType = "";
  try {
    const result = await verifyCollectedShardSignatures(work);
    if (result.invalid) {
      signatureLines.push(
        `Could not verify ${result.invalid} recovery ${result.invalid === 1 ? "sheet" : "sheets"}. Use another copy; these were not used.`,
      );
      signatureType = "warn";
    }
  } catch {
    signatureLines.push(
      "The kit could not check the recovery sheets' signatures. Try another browser.",
    );
    signatureType = "warn";
  }

  const combinedLines = [...baseStatusLines, ...signatureLines];
  const previousShardStatus = work.shardStatus;
  const recovered = autoRecoverShardSecret(work, combinedLines);
  if (!recovered && work.shardStatus === previousShardStatus && combinedLines.length) {
    setStatus(work, "shardStatus", combinedLines, signatureType || baseStatusType);
  }
  if (recovered && (signatureType || baseStatusType)) {
    work.shardStatus.type = baseStatusType || signatureType;
  }
}

export function updateField(dispatch, getState, key, value) {
  const current = getState();
  const patch = { [key]: value };
  if (RECOVERY_INPUT_FIELDS.has(key) && current[key] !== value) {
    clearRecoveryResult(patch);
  }
  if (current.isDecrypting && RECOVERY_INPUT_FIELDS.has(key)) {
    cancelRecoveryDecrypt(patch, current);
  }
  dispatchPatch(dispatch, getState, patch);
}

export function resetAll(dispatch) {
  cancelActiveDecryptWork();
  dispatch({ type: "RESET" });
}

function cancelRecoveryDecrypt(patch, current = patch) {
  if (!current.isDecrypting) return;
  cancelActiveDecryptWork();
  patch.isDecrypting = false;
  patch.decryptRequestId = current.decryptRequestId + 1;
}

export async function copyRecoveredSecret(dispatch, getState) {
  const current = getState();
  const text = current.recoveredShardSecret;
  if (!text) return;

  let statusLines = [];
  let statusType = "ok";
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      statusLines = ["Copied to clipboard."];
    } else {
      statusLines = ["Select the recovered value above and copy it."];
      statusType = "warn";
    }
  } catch {
    statusLines = ["Select the recovered value above and copy it."];
    statusType = "warn";
  }
  if (getState().recoveredShardSecret !== text) return;
  dispatchPatch(dispatch, getState, { shardStatus: { lines: statusLines, type: statusType } });
}
