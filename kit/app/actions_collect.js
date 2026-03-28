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
  copyAuthAndCipherFields,
  copyShardAsyncFields,
  dispatchPatch,
  dispatchReset,
  dispatchState,
  parseTextWithErrors,
} from "./actions_common.js";
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

function parsedMainAccepted(base, before, added) {
  return (
    added > 0 &&
    base.errors === before.errors &&
    base.conflicts === before.conflicts &&
    base.ignored === before.ignored &&
    base.authErrors === before.authErrors &&
    base.authConflicts === before.authConflicts
  );
}

async function runMainAsyncFollowups(dispatch, base) {
  const work = cloneState(base);
  const targetRevision = base.revision + 1;
  await updateAuthStatus(work);
  syncCollectedCiphertext(work);
  if (!work.recoveredShardSecret) {
    autoRecoverShardSecret(work);
  }
  dispatch({
    type: "MUTATE_STATE",
    baseRevision: targetRevision,
    mutate(next) {
      copyAuthAndCipherFields(next, work);
      copyShardAsyncFields(next, work);
    },
  });
}

function parsedShardAccepted(parsed, before, added) {
  return (
    added > 0 &&
    parsed.shardErrors === before.shardErrors &&
    parsed.shardConflicts === before.shardConflicts
  );
}

function mainScanStatus(base, before, added) {
  if (added > 0) {
    return {
      lines: [
        `Added ${added} frame(s).`,
        base.total ? "Collect all frames to download." : "Waiting for more frames.",
      ],
      type: "",
    };
  }
  if (base.errors > before.errors || base.authErrors > before.authErrors) {
    return {
      lines: [
        "Scanned QR could not be decoded.",
        "Try another scan or paste the payload text instead.",
      ],
      type: "error",
    };
  }
  if (
    base.conflicts > before.conflicts ||
    base.ignored > before.ignored ||
    base.authConflicts > before.authConflicts
  ) {
    return {
      lines: [
        "Scanned QR was ignored.",
        "Check for duplicates or conflicting frames, then continue scanning.",
      ],
      type: "warn",
    };
  }
  return {
    lines: [
      `Added ${added} frame(s).`,
      base.total ? "Collect all frames to download." : "Waiting for more frames.",
    ],
    type: "",
  };
}

function mainTextStatus(base, added, failed) {
  if (failed) {
    return {
      lines: [
        "Pasted text could not be decoded.",
        "Check the payload text or recovery text, then try again.",
      ],
      type: "error",
    };
  }
  return {
    lines: [
      `Added ${added} frame(s).`,
      base.total ? "Collect all frames to download." : "Waiting for more frames.",
    ],
    type: "",
  };
}

function shardScanStatus(parsed, before, added) {
  if (added > 0) {
    return {
      lines: [
        `Added ${added} shard frame(s).`,
        parsed.shardThreshold
          ? "Ready to recover when enough shards are collected."
          : "Waiting for shard metadata.",
      ],
      type: "",
    };
  }
  if (parsed.shardErrors > before.shardErrors) {
    return {
      lines: [
        "Scanned shard QR could not be decoded.",
        "Try another scan or paste the shard payload text instead.",
      ],
      type: "error",
    };
  }
  if (parsed.shardConflicts > before.shardConflicts) {
    return {
      lines: [
        "Scanned shard QR was ignored.",
        "Check for duplicates or conflicting shard frames, then continue scanning.",
      ],
      type: "warn",
    };
  }
  return {
    lines: [
      `Added ${added} shard frame(s).`,
      parsed.shardThreshold
        ? "Ready to recover when enough shards are collected."
        : "Waiting for shard metadata.",
    ],
    type: "",
  };
}

function shardTextStatus(parsed, added, failed) {
  if (failed) {
    return {
      lines: [
        "Pasted shard text could not be decoded.",
        "Check the shard payload text or shard recovery text, then try again.",
      ],
      type: "error",
    };
  }
  return {
    lines: [
      `Added ${added} shard frame(s).`,
      parsed.shardThreshold
        ? "Ready to recover when enough shards are collected."
        : "Waiting for shard metadata.",
    ],
    type: "",
  };
}

async function runShardAsyncFollowups(dispatch, parsed, baseStatusLines, baseStatusType = "") {
  const work = cloneState(parsed);
  const targetRevision = parsed.revision + 1;
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
    setStatus(work, "shardStatus", combinedLines, signatureType || baseStatusType);
  }
  dispatch({
    type: "MUTATE_STATE",
    baseRevision: targetRevision,
    mutate(next) {
      copyShardAsyncFields(next, work);
    },
  });
}

export function updateField(dispatch, getState, key, value) {
  dispatchPatch(dispatch, getState, { [key]: value });
}

export function resetAll(dispatch) {
  dispatchReset(dispatch);
}

export async function addPayloads(dispatch, getState) {
  const base = cloneState(getState());
  if (base.isAddingFrames) return;
  const before = {
    errors: base.errors,
    conflicts: base.conflicts,
    ignored: base.ignored,
    authErrors: base.authErrors,
    authConflicts: base.authConflicts,
  };
  const { added, failed } = parseTextWithErrors(base, base.payloadText, parseAutoPayload, "errors");
  const fullyAccepted = parsedMainAccepted(base, before, added);
  if (fullyAccepted) {
    base.payloadText = "";
  }
  base.isAddingFrames = true;
  const frameStatus = mainTextStatus(base, added, failed);
  setStatus(base, "frameStatus", frameStatus.lines, frameStatus.type);
  dispatchState(dispatch, base);
  try {
    await runMainAsyncFollowups(dispatch, base);
  } finally {
    const latest = cloneState(getState());
    latest.isAddingFrames = false;
    dispatchState(dispatch, latest);
  }
}

export async function addScannedPayload(dispatch, getState, scanned) {
  const base = cloneState(getState());
  if (base.isAddingFrames) return;
  const before = {
    errors: base.errors,
    conflicts: base.conflicts,
    ignored: base.ignored,
    authErrors: base.authErrors,
    authConflicts: base.authConflicts,
  };
  const added = parseScannedPayload(base, scanned);
  const fullyAccepted = parsedMainAccepted(base, before, added);
  if (fullyAccepted) {
    base.payloadText = "";
  }
  base.isAddingFrames = true;
  const frameStatus = mainScanStatus(base, before, added);
  setStatus(base, "frameStatus", frameStatus.lines, frameStatus.type);
  dispatchState(dispatch, base);
  try {
    await runMainAsyncFollowups(dispatch, base);
  } finally {
    const latest = cloneState(getState());
    latest.isAddingFrames = false;
    dispatchState(dispatch, latest);
  }
}

export async function addShardPayloads(dispatch, getState) {
  const parsed = cloneState(getState());
  if (parsed.isAddingShards) return;
  const before = {
    shardErrors: parsed.shardErrors,
    shardConflicts: parsed.shardConflicts,
  };
  const { added, failed } = parseTextWithErrors(
    parsed,
    parsed.shardPayloadText,
    parseAutoShard,
    "shardErrors",
  );
  const fullyAccepted = parsedShardAccepted(parsed, before, added);
  if (fullyAccepted) {
    parsed.shardPayloadText = "";
  }
  parsed.isAddingShards = true;
  const shardStatus = shardTextStatus(parsed, added, failed);
  const baseStatusLines = shardStatus.lines;
  setStatus(parsed, "shardStatus", baseStatusLines, shardStatus.type);
  dispatchState(dispatch, parsed);
  try {
    await runShardAsyncFollowups(dispatch, parsed, baseStatusLines, shardStatus.type);
  } finally {
    const latest = cloneState(getState());
    latest.isAddingShards = false;
    dispatchState(dispatch, latest);
  }
}

export async function addScannedShardPayload(dispatch, getState, scanned) {
  const parsed = cloneState(getState());
  if (parsed.isAddingShards) return;
  const before = {
    shardErrors: parsed.shardErrors,
    shardConflicts: parsed.shardConflicts,
  };
  const added = parseScannedShard(parsed, scanned);
  const fullyAccepted = parsedShardAccepted(parsed, before, added);
  if (fullyAccepted) {
    parsed.shardPayloadText = "";
  }
  parsed.isAddingShards = true;
  const shardStatus = shardScanStatus(parsed, before, added);
  const baseStatusLines = shardStatus.lines;
  setStatus(parsed, "shardStatus", baseStatusLines, shardStatus.type);
  dispatchState(dispatch, parsed);
  try {
    await runShardAsyncFollowups(dispatch, parsed, baseStatusLines, shardStatus.type);
  } finally {
    const latest = cloneState(getState());
    latest.isAddingShards = false;
    dispatchState(dispatch, latest);
  }
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
