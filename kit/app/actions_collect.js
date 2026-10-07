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

import {
  cancelDecryptRequest,
  clearRecoveryResult,
  dispatchPatch,
  dispatchReset,
  dispatchState,
  parseTextWithErrors,
} from "./state_actions.js";
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
import { cloneState, setStatus } from "./state/initial.js";
import { documentCounts, primaryDocumentRecord } from "./documents/store.js";
import { activeShardSetRecord, shardCounts } from "./shard_store.js";

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

function collectionStatus(state, collection, added, failed, ignored, scanned) {
  const shard = collection === SHARD_COLLECTION;
  const noun = shard ? "shard " : "";
  if (failed) {
    return {
      lines: [
        scanned
          ? `Scanned ${noun}QR could not be decoded.`
          : `Pasted ${noun}text could not be decoded.`,
      ],
      type: "error",
    };
  }
  if (!added && ignored && scanned) {
    return {
      lines: [`Scanned ${noun}QR was ignored. Check for duplicates or conflicting frames.`],
      type: "warn",
    };
  }
  const ready = shard
    ? activeShardSetRecord(state)?.threshold
    : primaryDocumentRecord(state)?.total;
  const hint = shard
    ? ready
      ? "Ready to recover when enough shards are collected."
      : "Waiting for shard metadata."
    : ready
      ? "Collect all frames to download."
      : "Waiting for more frames.";
  return { lines: [`Added ${added} ${noun}frame(s).`, hint], type: "" };
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
    parsed,
    collection,
    added,
    failed || counts.errors > before.errors,
    hasIssues,
    fromScan,
  );
  setStatus(parsed, collection.status, status.lines, status.type);
  dispatchState(dispatch, parsed);
  try {
    await finishCollection(dispatch, getState, parsed, collection, status);
  } finally {
    if (getState()[collection.request] === requestId) {
      dispatchPatch(dispatch, getState, { [collection.busy]: false });
    }
  }
}

async function finishCollection(dispatch, getState, parsed, collection, status) {
  const work = cloneState(parsed);
  await updateAuthStatus(work);
  syncCollectedCiphertext(work);
  const shard = collection === SHARD_COLLECTION;
  await verifyAndRecoverShardSecret(work, shard ? status.lines : [], shard ? status.type : "");
  const latest = getState();
  if (latest[collection.request] !== parsed[collection.request]) return;
  if (!shard) {
    dispatchState(dispatch, { ...work, revision: parsed.revision + 1 });
    return;
  }
  // Shard verification may finish after the main collector. Preserve unrelated edits.
  if (
    latest.frameRequestId !== parsed.frameRequestId ||
    !latest.isAddingShards ||
    latest.shardPayloadText !== parsed.shardPayloadText ||
    latest.agePassphrase !== parsed.agePassphrase
  )
    return;
  dispatchState(dispatch, {
    ...latest,
    documents: work.documents,
    shardSets: work.shardSets,
    activeShardSetKey: work.activeShardSetKey,
    recoveredShardSecret: work.recoveredShardSecret,
    agePassphrase: work.agePassphrase,
    shardStatus: work.shardStatus,
  });
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
    if (result.verified) {
      signatureLines.push(`Verified ${result.verified} shard signature(s).`);
    }
    if (result.invalid) {
      signatureLines.push(`Rejected ${result.invalid} shard(s) due to invalid signature.`);
      signatureType = "warn";
    }
  } catch {
    signatureLines.push("Shard signature verification failed.");
    signatureType = "warn";
  }

  const combinedLines = [...baseStatusLines, ...signatureLines];
  const previousShardStatus = work.shardStatus;
  const recovered = autoRecoverShardSecret(work, combinedLines);
  const shardStatusOverridden =
    work.shardStatus !== previousShardStatus &&
    (work.shardStatus.lines.length !== previousShardStatus.lines.length ||
      work.shardStatus.lines.some((line, index) => line !== previousShardStatus.lines[index]) ||
      work.shardStatus.type !== previousShardStatus.type);
  if (!recovered && !shardStatusOverridden && combinedLines.length) {
    setStatus(work, "shardStatus", combinedLines, signatureType || baseStatusType);
  }
  return recovered;
}

export function updateField(dispatch, getState, key, value) {
  const current = getState();
  const patch = { [key]: value };
  if (RECOVERY_INPUT_FIELDS.has(key) && current[key] !== value) {
    patch.extractedFiles = [];
    patch.decryptedBackup = null;
    patch.extractStatus = { lines: [], type: "" };
    patch.decryptStatus = { lines: [], type: "" };
  }
  if (current.isDecrypting && RECOVERY_INPUT_FIELDS.has(key)) {
    cancelActiveDecryptWork();
    patch.isDecrypting = false;
    patch.decryptRequestId = current.decryptRequestId + 1;
  }
  dispatchPatch(dispatch, getState, patch);
}

export function resetAll(dispatch) {
  cancelActiveDecryptWork();
  dispatchReset(dispatch);
}

function cancelRecoveryDecrypt(state) {
  if (state.isDecrypting) {
    cancelActiveDecryptWork();
  }
  cancelDecryptRequest(state);
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
      statusLines = ["Copy manually."];
      statusType = "warn";
    }
  } catch {
    statusLines = ["Copy manually."];
    statusType = "warn";
  }
  dispatchPatch(dispatch, getState, { shardStatus: { lines: statusLines, type: statusType } });
}
