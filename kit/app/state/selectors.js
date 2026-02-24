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

import { formatBytes } from "../format.js";
import { listMissing } from "../frame_list.js";
import { SHARD_KEY_PASSPHRASE, SHARD_KEY_SIGNING_SEED } from "../constants.js";

const TONE_IDLE = "idle";
const TONE_OK = "ok";
const TONE_WARN = "warn";
const TONE_ERR = "error";

function diagItem(label, value, tone, detail, code = false) {
  return { label, value, detail, tone, code };
}

function countTone(value, warnTone = TONE_WARN) {
  return value > 0 ? warnTone : TONE_OK;
}

function describeMissingFrames(state) {
  if (!state.total) {
    return {
      value: "Waiting",
      detail: "Paste backup data.",
      tone: TONE_IDLE,
    };
  }
  const missingCount = Math.max(0, state.total - state.mainFrames.size);
  if (missingCount === 0) {
    return {
      value: "Complete",
      detail: "All frames collected.",
      tone: TONE_OK,
    };
  }
  const missingList = listMissing(state.total, state.mainFrames);
  const preview = missingList.slice(0, 8);
  const extra = missingList.length - preview.length;
  const detail = preview.length
    ? `${preview.join(", ")}${extra > 0 ? ` +${extra}` : ""}`
    : "";
  return {
    value: `${missingCount} missing`,
    detail,
    tone: TONE_WARN,
  };
}

function sumFrameBytes(frames) {
  let total = 0;
  for (const frame of frames.values()) {
    total += frame.data.length;
  }
  return total;
}

export function selectFrameDiagnostics(state) {
  const missingInfo = describeMissingFrames(state);
  return [
    diagItem("Missing", missingInfo.value, missingInfo.tone, missingInfo.detail),
    diagItem("Conflicts", `${state.conflicts}`, countTone(state.conflicts, TONE_ERR)),
    diagItem("Errors", `${state.errors}`, countTone(state.errors, TONE_ERR)),
    diagItem("Duplicates", `${state.duplicates}`, countTone(state.duplicates)),
    diagItem("Ignored", `${state.ignored}`, countTone(state.ignored)),
    diagItem("Doc ID", state.docIdHex ?? "(unknown)", state.docIdHex ? TONE_OK : TONE_IDLE, undefined, true),
  ];
}

export function selectShardKeyLabel(state) {
  if (state.shardKeyType === SHARD_KEY_PASSPHRASE) return "passphrase";
  if (state.shardKeyType === SHARD_KEY_SIGNING_SEED) return "signing key";
  return "-";
}

export function selectRecoveredLabel(state) {
  if (state.shardKeyType === SHARD_KEY_SIGNING_SEED) {
    return "Recovered signing key (hex)";
  }
  if (state.shardKeyType === SHARD_KEY_PASSPHRASE) {
    return "Recovered passphrase";
  }
  return "Recovered secret";
}

export function selectShardMatch(state) {
  if (state.docIdHex && state.shardDocIdHex) {
    return state.docIdHex === state.shardDocIdHex ? "yes" : "no";
  }
  return "-";
}

export function selectShardInputs(state) {
  return {
    docIdHex: state.shardDocIdHex || state.docIdHex || state.authDocIdHex || "",
    docHashHex: state.shardDocHashHex || state.authDocHashHex || state.cipherDocHashHex || "",
    signPubHex: state.shardSignPubHex || state.authSignPubHex || "",
  };
}

export function selectShardDiagnostics(state) {
  const shardKeyLabel = selectShardKeyLabel(state);
  return [
    diagItem("Key type", shardKeyLabel === "-" ? "Unknown" : shardKeyLabel, shardKeyLabel === "-" ? TONE_IDLE : TONE_OK),
    diagItem("Conflicts", `${state.shardConflicts}`, countTone(state.shardConflicts, TONE_ERR)),
    diagItem("Errors", `${state.shardErrors}`, countTone(state.shardErrors, TONE_ERR)),
    diagItem("Duplicates", `${state.shardDuplicates}`, countTone(state.shardDuplicates)),
  ];
}

export function selectCiphertextSource(state) {
  const hasConflicts = state.conflicts > 0;
  const available = !hasConflicts
    && (Boolean(state.ciphertext) || (state.total && state.mainFrames.size === state.total));
  const size = available
    ? (state.ciphertext ? state.ciphertext.length : sumFrameBytes(state.mainFrames))
    : 0;
  let detail = `Frames ${state.mainFrames.size}/${state.total ?? "?"}`;
  if (hasConflicts) {
    detail = "Conflicts found. Reset and re-add data.";
  } else if (available) {
    detail = `${formatBytes(size)} | ${state.mainFrames.size}/${state.total ?? "?"} frames`;
  }
  return {
    label: "Ciphertext",
    detail,
    available,
  };
}

export function selectOutputSummary(state) {
  const count = state.extractedFiles.length;
  const totalBytes = state.extractedFiles.reduce((sum, file) => sum + file.data.length, 0);
  const subtitle = count
    ? `${count} file(s) | ${formatBytes(totalBytes)}`
    : "No files extracted";
  return { count, totalBytes, subtitle };
}

export function selectActionState(state) {
  const ciphertextSource = selectCiphertextSource(state);
  const hasEnvelope = Boolean(state.decryptedEnvelope);
  return {
    canDownloadCipher: state.total && state.mainFrames.size === state.total && state.conflicts === 0,
    canDecryptCiphertext: state.agePassphrase.trim().length > 0 && ciphertextSource.available,
    canExtractEnvelope: hasEnvelope,
    canDownloadEnvelope: hasEnvelope,
    canCopyResult: Boolean(state.recoveredShardSecret),
    hasOutput: state.extractedFiles.length > 0,
  };
}
