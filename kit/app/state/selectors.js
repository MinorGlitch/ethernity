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
  const mainRecords = mainDocumentRecords(state);
  if (!mainRecords.length) {
    return {
      value: "Waiting",
      detail: "Paste backup data.",
      tone: TONE_IDLE,
    };
  }
  const missingCount = mainRecords.reduce(
    (sum, record) => sum + Math.max(0, record.total - record.mainFrames.size),
    0,
  );
  if (missingCount === 0) {
    return {
      value: "Complete",
      detail:
        mainRecords.length > 1
          ? `${mainRecords.length} documents collected.`
          : "All frames collected.",
      tone: TONE_OK,
    };
  }
  if (mainRecords.length > 1) {
    const completeCount = mainRecords.filter(
      (record) => record.mainFrames.size === record.total,
    ).length;
    return {
      value: `${missingCount} missing`,
      detail: `${completeCount}/${mainRecords.length} documents complete.`,
      tone: TONE_WARN,
    };
  }
  const missingList = listMissing(state.total, state.mainFrames);
  const preview = missingList.slice(0, 8);
  const extra = missingList.length - preview.length;
  const detail = preview.length ? `${preview.join(", ")}${extra > 0 ? ` +${extra}` : ""}` : "";
  return {
    value: `${missingCount} missing`,
    detail,
    tone: TONE_WARN,
  };
}

function mainDocumentRecords(state) {
  return Array.from(state.documents?.values?.() ?? []).filter((record) => record.total !== null);
}

function completeMainDocumentRecords(state) {
  return mainDocumentRecords(state).filter((record) => record.mainFrames.size === record.total);
}

function incompleteMainDocumentRecords(state) {
  return mainDocumentRecords(state).filter((record) => record.mainFrames.size !== record.total);
}

function rootOnlyTargetText(value) {
  const target = String(value ?? "")
    .trim()
    .toLowerCase();
  return target === "root" || target === "0";
}

function nonLatestTargetText(value) {
  const target = String(value ?? "")
    .trim()
    .toLowerCase();
  return rootOnlyTargetText(target) || /^[1-9]\d*$/.test(target) || /^[0-9a-f]{64}$/.test(target);
}

export function selectFrameCollectionComplete(state) {
  const records = mainDocumentRecords(state);
  return records.length > 0 && records.every((record) => record.mainFrames.size === record.total);
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
  const documentCount = state.documents?.size ?? 0;
  return [
    diagItem("Missing", missingInfo.value, missingInfo.tone, missingInfo.detail),
    diagItem(
      "Documents",
      documentCount ? `${documentCount}` : "Waiting",
      documentCount ? TONE_OK : TONE_IDLE,
    ),
    diagItem("Conflicts", `${state.conflicts}`, countTone(state.conflicts, TONE_ERR)),
    diagItem("Errors", `${state.errors}`, countTone(state.errors, TONE_ERR)),
    diagItem("AUTH conflicts", `${state.authConflicts}`, countTone(state.authConflicts, TONE_ERR)),
    diagItem("AUTH errors", `${state.authErrors}`, countTone(state.authErrors, TONE_ERR)),
    diagItem("Duplicates", `${state.duplicates}`, countTone(state.duplicates)),
    diagItem("Ignored", `${state.ignored}`, countTone(state.ignored)),
    diagItem(
      "Doc ID",
      state.docIdHex ?? "(unknown)",
      state.docIdHex ? TONE_OK : TONE_IDLE,
      undefined,
      true,
    ),
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
    diagItem(
      "Key type",
      shardKeyLabel === "-" ? "Unknown" : shardKeyLabel,
      shardKeyLabel === "-" ? TONE_IDLE : TONE_OK,
    ),
    diagItem("Conflicts", `${state.shardConflicts}`, countTone(state.shardConflicts, TONE_ERR)),
    diagItem("Errors", `${state.shardErrors}`, countTone(state.shardErrors, TONE_ERR)),
    diagItem("Duplicates", `${state.shardDuplicates}`, countTone(state.shardDuplicates)),
  ];
}

export function selectCiphertextSource(
  state,
  { allowIncompleteDocuments = false, allowAuthOnlyDocuments = false } = {},
) {
  const hasConflicts = state.conflicts > 0;
  const hasAuthConflicts = state.authConflicts > 0;
  const hasAuthErrors = state.authErrors > 0;
  const documentCount = state.documents?.size ?? 0;
  const completeRecords = completeMainDocumentRecords(state);
  const incompleteRecords = incompleteMainDocumentRecords(state);
  const authOnlyRecords = Array.from(state.documents?.values?.() ?? []).filter(
    (record) => record.authPayload && record.total === null,
  );
  const blockedByIncompleteDocuments = incompleteRecords.length > 0 && !allowIncompleteDocuments;
  const blockedByAuthOnlyDocuments = authOnlyRecords.length > 0 && !allowAuthOnlyDocuments;
  const available =
    !hasConflicts &&
    !hasAuthConflicts &&
    !hasAuthErrors &&
    !blockedByIncompleteDocuments &&
    !blockedByAuthOnlyDocuments &&
    (Boolean(state.ciphertext) ||
      (state.total && state.mainFrames.size === state.total) ||
      completeRecords.length > 0);
  const size = available
    ? state.ciphertext
      ? state.ciphertext.length
      : completeRecords.length > 1
        ? completeRecords.reduce((sum, record) => sum + sumFrameBytes(record.mainFrames), 0)
        : sumFrameBytes(state.mainFrames)
    : 0;
  let detail = `Frames ${state.mainFrames.size}/${state.total ?? "?"}`;
  if (hasConflicts) {
    detail = "Conflicts found. Reset and re-add data.";
  } else if (hasAuthConflicts) {
    detail = "AUTH conflicts found. Reset and re-add data.";
  } else if (hasAuthErrors) {
    detail = "Invalid AUTH data found. Reset and re-add data.";
  } else if (blockedByIncompleteDocuments) {
    detail = "Complete remaining extension documents or choose a specific target.";
  } else if (blockedByAuthOnlyDocuments) {
    detail = "Complete matching MAIN document or choose a specific target.";
  } else if (available) {
    const docs = documentCount > 1 ? ` | ${documentCount} documents` : "";
    detail = `${formatBytes(size)} | ${state.mainFrames.size}/${state.total ?? "?"} frames${docs}`;
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
  const subtitle = count ? `${count} file(s) | ${formatBytes(totalBytes)}` : "No files extracted";
  return { count, totalBytes, subtitle };
}

export function selectActionState(state) {
  const allowPartialDocuments = nonLatestTargetText(state.extensionTargetText);
  const ciphertextSource = selectCiphertextSource(state, {
    allowIncompleteDocuments: allowPartialDocuments,
    allowAuthOnlyDocuments: allowPartialDocuments,
  });
  const rootOnlyCiphertextSource = selectCiphertextSource(state, {
    allowIncompleteDocuments: true,
    allowAuthOnlyDocuments: true,
  });
  const hasEnvelope = Boolean(state.decryptedEnvelope);
  const documentCount = state.documents?.size ?? 0;
  const hasMultipleDocuments = documentCount > 1;
  const canDownloadCipher =
    !hasMultipleDocuments &&
    state.total &&
    state.mainFrames.size === state.total &&
    state.conflicts === 0;
  return {
    canDownloadCipher,
    downloadCipherDisabledReason: hasMultipleDocuments
      ? "Encrypted file download is only available for one backup document."
      : "Add all backup data first.",
    canDecryptCiphertext: state.agePassphrase.trim().length > 0 && ciphertextSource.available,
    canDecryptRootOnly:
      state.agePassphrase.trim().length > 0 &&
      hasMultipleDocuments &&
      rootOnlyCiphertextSource.available,
    canExtractEnvelope: hasEnvelope,
    canDownloadEnvelope: hasEnvelope,
    canCopyResult: Boolean(state.recoveredShardSecret),
    hasMultipleDocuments,
    hasOutput: state.extractedFiles.length > 0,
  };
}
