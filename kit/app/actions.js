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

import { decryptAgePassphrase } from "../lib/age_scrypt.js";
import { makeZip } from "../lib/zip.js";
import { updateAuthStatus } from "./auth.js";
import { verifyCollectedShardSignatures } from "./shard_auth.js";
import { extractFiles } from "./envelope.js";
import {
  parseAutoPayload,
  parseAutoShard,
  reassembleCiphertext,
  syncCollectedCiphertext,
} from "./frames.js";
import { downloadBlob, downloadBytes } from "./io.js";
import { autoRecoverShardSecret } from "./shards.js";
import { bumpError, cloneState, createInitialState, setStatus } from "./state/initial.js";
import { formatBytes } from "./state/selectors.js";

function dispatchState(dispatch, state) {
  dispatch({ type: "REPLACE", state });
}

function setLineStatus(state, key, line, type = "") {
  setStatus(state, key, [line], type);
}

function setErrorStatus(state, key, err) {
  setLineStatus(state, key, String(err), "error");
}

function parseTextWithErrors(state, text, parseFn, errorKey) {
  let added = 0;
  try {
    added += parseFn(state, text);
  } catch (err) {
    bumpError(state, errorKey);
  }
  return added;
}

function clearRecoveredOutput(state) {
  state.extractedFiles = [];
  setStatus(state, "extractStatus", []);
}

function clearDecryptedEnvelope(state) {
  state.decryptedEnvelope = null;
  state.decryptedEnvelopeSource = "";
}

function applyExtractResult(state, result) {
  state.extractedFiles = result.files;
  setLineStatus(state, "extractStatus", `${result.files.length} file(s) ready.`, "ok");
}

export function updateField(dispatch, getState, key, value) {
  const next = cloneState(getState());
  next[key] = value;
  dispatchState(dispatch, next);
}

export function resetAll(dispatch) {
  dispatchState(dispatch, createInitialState());
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
    base.total
      ? "Collect all frames to download."
      : "Waiting for more frames.",
  ]);
  dispatchState(dispatch, base);

  const next = cloneState(base);
  await updateAuthStatus(next);
  syncCollectedCiphertext(next);
  dispatchState(dispatch, next);
}

export async function addShardPayloads(dispatch, getState) {
  let added = 0;
  const next = cloneState(getState());
  const before = {
    shardErrors: next.shardErrors,
    shardConflicts: next.shardConflicts,
  };
  added = parseTextWithErrors(next, next.shardPayloadText, parseAutoShard, "shardErrors");
  const fullyAccepted = added > 0
    && next.shardErrors === before.shardErrors
    && next.shardConflicts === before.shardConflicts;
  if (fullyAccepted) {
    next.shardPayloadText = "";
  }
  const statusLines = [
    `Added ${added} shard frame(s).`,
    next.shardThreshold
      ? "Ready to recover when enough shards are collected."
      : "Waiting for shard metadata.",
  ];

  const signatureLines = [];
  let signatureType = "";
  try {
    const result = await verifyCollectedShardSignatures(next);
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

  const combinedLines = [...statusLines, ...signatureLines];
  const previousShardStatus = next.shardStatus;
  const recovered = autoRecoverShardSecret(next, combinedLines);
  const shardStatusOverridden =
    next.shardStatus !== previousShardStatus &&
    (next.shardStatus.lines.length !== previousShardStatus.lines.length ||
      next.shardStatus.lines.some((line, index) => line !== previousShardStatus.lines[index]) ||
      next.shardStatus.type !== previousShardStatus.type);
  if (!recovered && !shardStatusOverridden) {
    setStatus(next, "shardStatus", combinedLines, signatureType);
  }
  dispatchState(dispatch, next);
}

export async function copyRecoveredSecret(dispatch, getState) {
  const current = getState();
  const text = current.recoveredShardSecret;
  if (!text) {
    return;
  }
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
  } catch (err) {
    statusLines = ["Copy manually."];
    statusType = "warn";
  }
  const next = cloneState(getState());
  setStatus(next, "shardStatus", statusLines, statusType);
  dispatchState(dispatch, next);
}

export function downloadCipher(dispatch, getState) {
  const next = cloneState(getState());
  try {
    if (next.conflicts > 0) {
      throw new Error("conflicting duplicate frames detected");
    }
    const ciphertext = reassembleCiphertext(next);
    next.ciphertext = ciphertext;
    downloadBytes(ciphertext, "ciphertext.age");
    setLineStatus(next, "frameStatus", "Downloaded ciphertext.age", "ok");
  } catch (err) {
    setErrorStatus(next, "frameStatus", err);
  }
  dispatchState(dispatch, next);
}

export async function decryptCiphertext(dispatch, getState) {
  const base = cloneState(getState());
  if (!base.agePassphrase.trim()) {
    setLineStatus(base, "decryptStatus", "Passphrase required.", "warn");
    dispatchState(dispatch, base);
    return;
  }
  clearRecoveredOutput(base);
  clearDecryptedEnvelope(base);
  base.isDecrypting = true;
  setLineStatus(base, "decryptStatus", "Unlocking backup...");
  dispatchState(dispatch, base);

  const next = cloneState(base);
  try {
    if (next.conflicts > 0) {
      throw new Error("conflicting duplicate frames detected");
    }
    if (!next.ciphertext && next.total && next.mainFrames.size === next.total) {
      next.ciphertext = reassembleCiphertext(next);
    }
    const bytes = next.ciphertext;
    if (!bytes) {
      throw new Error("Collected ciphertext not available yet.");
    }
    const plaintext = await decryptAgePassphrase(bytes, next.agePassphrase);
    next.decryptedEnvelope = plaintext;
    next.decryptedEnvelopeSource = "Collected ciphertext";
    const result = extractFiles(plaintext);
    applyExtractResult(next, result);
    next.isDecrypting = false;
    next.recoveryComplete = true;
    setStatus(next, "decryptStatus", [
      "Recovery complete.",
      `${result.files.length} file(s) recovered (${formatBytes(plaintext.length)}).`,
    ], "ok");
    next.agePassphrase = "";
  } catch (err) {
    next.isDecrypting = false;
    const errorMsg = String(err);
    const friendlyError = errorMsg.includes("password")
      ? "Incorrect passphrase."
      : errorMsg.includes("decrypt")
        ? "Could not unlock backup. Check passphrase."
        : errorMsg;
    setLineStatus(next, "decryptStatus", friendlyError, "error");
  }
  dispatchState(dispatch, next);
}

export function downloadEnvelope(dispatch, getState) {
  const current = getState();
  if (!current.decryptedEnvelope) return;
  downloadBytes(current.decryptedEnvelope, "decrypted_envelope.bin");
}

export function extractEnvelope(dispatch, getState) {
  const base = cloneState(getState());
  try {
    clearRecoveredOutput(base);
    if (!base.decryptedEnvelope) {
      throw new Error("No decrypted envelope available yet.");
    }
    setLineStatus(base, "extractStatus", "Extracting files...");
    dispatchState(dispatch, base);
    const next = cloneState(base);
    const result = extractFiles(next.decryptedEnvelope);
    applyExtractResult(next, result);
    dispatchState(dispatch, next);
  } catch (err) {
    setErrorStatus(base, "extractStatus", err);
    dispatchState(dispatch, base);
  }
}

export function clearOutput(dispatch, getState) {
  const next = cloneState(getState());
  clearRecoveredOutput(next);
  dispatchState(dispatch, next);
}

export function downloadExtract(dispatch, getState, index) {
  const current = getState();
  const file = current.extractedFiles[index];
  if (file) {
    downloadBytes(file.data, file.path);
  }
}

export function downloadZip(dispatch, getState) {
  const next = cloneState(getState());
  if (!next.extractedFiles.length) return;
  try {
    const zipBlob = makeZip(next.extractedFiles);
    downloadBlob(zipBlob, "recovered_files.zip");
    setLineStatus(next, "extractStatus", `Downloaded ${next.extractedFiles.length} file(s) as ZIP.`, "ok");
  } catch (err) {
    setErrorStatus(next, "extractStatus", err);
  }
  dispatchState(dispatch, next);
}
