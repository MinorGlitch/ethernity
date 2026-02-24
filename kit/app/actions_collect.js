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

import { updateAuthStatus } from "./auth.js";
import { parseAutoPayload, parseAutoShard } from "./frames_parse.js";
import { syncCollectedCiphertext } from "./frames_cipher.js";
import { verifyCollectedShardSignatures } from "./shard_auth.js";
import { autoRecoverShardSecret } from "./shards.js";
import { cloneState, setStatus } from "./state/initial.js";
import {
  cloneLatest,
  copyAuthAndCipherFields,
  copyShardAsyncFields,
  dispatchPatch,
  dispatchReset,
  dispatchState,
  parseTextWithErrors,
} from "./actions_common.js";

export function updateField(dispatch, getState, key, value) {
  dispatchPatch(dispatch, getState, { [key]: value });
}

export function resetAll(dispatch) {
  dispatchReset(dispatch);
}

export async function addPayloads(dispatch, getState) {
  const base = cloneState(getState());
  const before = {
    errors: base.errors,
    conflicts: base.conflicts,
    ignored: base.ignored,
    authErrors: base.authErrors,
    authConflicts: base.authConflicts,
  };
  const added = parseTextWithErrors(base, base.payloadText, parseAutoPayload, "errors");
  const fullyAccepted = added > 0
    && base.errors === before.errors
    && base.conflicts === before.conflicts
    && base.ignored === before.ignored
    && base.authErrors === before.authErrors
    && base.authConflicts === before.authConflicts;
  if (fullyAccepted) {
    base.payloadText = "";
  }
  setStatus(base, "frameStatus", [
    `Added ${added} frame(s).`,
    base.total ? "Collect all frames to download." : "Waiting for more frames.",
  ]);
  dispatchState(dispatch, base);

  const work = cloneState(base);
  await updateAuthStatus(work);
  syncCollectedCiphertext(work);
  if (!work.recoveredShardSecret) {
    autoRecoverShardSecret(work);
  }
  const next = cloneLatest(getState);
  copyAuthAndCipherFields(next, work);
  copyShardAsyncFields(next, work);
  dispatchState(dispatch, next);
}

export async function addShardPayloads(dispatch, getState) {
  let added = 0;
  const parsed = cloneState(getState());
  const before = {
    shardErrors: parsed.shardErrors,
    shardConflicts: parsed.shardConflicts,
  };
  added = parseTextWithErrors(parsed, parsed.shardPayloadText, parseAutoShard, "shardErrors");
  const fullyAccepted = added > 0
    && parsed.shardErrors === before.shardErrors
    && parsed.shardConflicts === before.shardConflicts;
  if (fullyAccepted) {
    parsed.shardPayloadText = "";
  }
  const baseStatusLines = [
    `Added ${added} shard frame(s).`,
    parsed.shardThreshold
      ? "Ready to recover when enough shards are collected."
      : "Waiting for shard metadata.",
  ];
  setStatus(parsed, "shardStatus", baseStatusLines);
  dispatchState(dispatch, parsed);

  const work = cloneState(parsed);
  const signatureLines = [];
  let signatureType = "";
  try {
    const result = await verifyCollectedShardSignatures(work);
    if (result.unavailable) {
      signatureLines.push("Shard signatures not verified in this browser.");
      signatureType = "warn";
    } else {
      if (result.verified) {
        signatureLines.push(`Verified ${result.verified} shard signature(s).`);
      }
      if (result.invalid) {
        signatureLines.push(`Rejected ${result.invalid} shard(s) due to invalid signature.`);
        signatureType = "warn";
      }
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
  if (!recovered && !shardStatusOverridden) {
    setStatus(work, "shardStatus", combinedLines, signatureType);
  }
  const next = cloneLatest(getState);
  copyShardAsyncFields(next, work);
  dispatchState(dispatch, next);
}

export async function copyRecoveredSecret(dispatch, getState) {
  const current = getState();
  const text = current.recoveredShardSecret;
  if (!text) return;

  let statusLines = [];
  let statusType = "ok";
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
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
