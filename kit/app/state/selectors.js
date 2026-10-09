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
  authOnlyDocumentRecords,
  completeDocumentRecords,
  incompleteDocumentRecords,
  documentCounts,
  primaryDocumentRecord,
} from "../documents/store.js";
import { activeShardSetRecord, shardCounts } from "../shard_store.js";
import { formatBytes } from "../format.js";
import { listMissing } from "../frame_list.js";
import { SHARD_KEY_PASSPHRASE, SHARD_KEY_SIGNING_SEED } from "../constants.js";
import { inspectExtensionTarget } from "../extensions/target.js";

const TONE_IDLE = "idle";
const TONE_OK = "ok";
const TONE_WARN = "warn";
const TONE_ERR = "error";

function diagItem(label, value, tone, detail) {
  return { label, value, detail, tone };
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
  const missingList = listMissing(mainRecords[0].total, mainRecords[0].mainFrames);
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
  return Array.from(state.documents.values()).filter((record) => record.total !== null);
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
  const documentCount = state.documents.size;
  const counts = documentCounts(state);
  const primary = primaryDocumentRecord(state);
  return [
    diagItem("Missing", missingInfo.value, missingInfo.tone, missingInfo.detail),
    diagItem(
      "Documents",
      documentCount ? `${documentCount}` : "Waiting",
      documentCount ? TONE_OK : TONE_IDLE,
    ),
    diagItem("Conflicts", `${counts.conflicts}`, countTone(counts.conflicts, TONE_ERR)),
    diagItem("Errors", `${state.errors}`, countTone(state.errors, TONE_ERR)),
    diagItem(
      "AUTH conflicts",
      `${counts.authConflicts}`,
      countTone(counts.authConflicts, TONE_ERR),
    ),
    diagItem("AUTH errors", `${counts.authErrors}`, countTone(counts.authErrors, TONE_ERR)),
    diagItem("Duplicates", `${counts.duplicates}`, countTone(counts.duplicates)),
    diagItem("Ignored", `${state.ignored}`, countTone(state.ignored)),
    diagItem("Doc ID", primary?.docIdHex ?? "(unknown)", primary ? TONE_OK : TONE_IDLE),
  ];
}

export function selectShardKeyLabel(state) {
  const keyType = activeShardSetRecord(state)?.keyType;
  if (keyType === SHARD_KEY_PASSPHRASE) return "passphrase";
  if (keyType === SHARD_KEY_SIGNING_SEED) return "signing key";
  return "-";
}

export function selectRecoveredLabel(state) {
  const keyType = activeShardSetRecord(state)?.keyType;
  if (keyType === SHARD_KEY_SIGNING_SEED) {
    return "Recovered signing key (hex)";
  }
  if (keyType === SHARD_KEY_PASSPHRASE) {
    return "Recovered passphrase";
  }
  return "Recovered secret";
}

export function selectShardInputs(state) {
  const primary = primaryDocumentRecord(state);
  const shard = activeShardSetRecord(state);
  return {
    docIdHex: shard?.docIdHex || primary?.docIdHex || "",
    docHashHex: shard?.docHashHex || primary?.authDocHashHex || primary?.cipherDocHashHex || "",
    signPubHex: shard?.signPubHex || primary?.authSignPubHex || "",
  };
}

export function selectShardDiagnostics(state) {
  const shardKeyLabel = selectShardKeyLabel(state);
  const counts = shardCounts(state);
  return [
    diagItem(
      "Key type",
      shardKeyLabel === "-" ? "Unknown" : shardKeyLabel,
      shardKeyLabel === "-" ? TONE_IDLE : TONE_OK,
    ),
    diagItem("Conflicts", `${counts.conflicts}`, countTone(counts.conflicts, TONE_ERR)),
    diagItem("Errors", `${counts.errors}`, countTone(counts.errors, TONE_ERR)),
    diagItem("Duplicates", `${counts.duplicates}`, countTone(counts.duplicates)),
  ];
}

export function selectCiphertextSource(
  state,
  { allowIncompleteDocuments = false, allowAuthOnlyDocuments = false } = {},
) {
  const counts = documentCounts(state);
  const primary = primaryDocumentRecord(state);
  const hasConflicts = counts.conflicts > 0;
  const hasAuthConflicts = counts.authConflicts > 0;
  const hasAuthErrors = counts.authErrors > 0;
  const documentCount = state.documents.size;
  const completeRecords = completeDocumentRecords(state);
  const incompleteRecords = incompleteDocumentRecords(state);
  const authOnlyRecords = authOnlyDocumentRecords(state);
  const blockedByIncompleteDocuments = incompleteRecords.length > 0 && !allowIncompleteDocuments;
  const blockedByAuthOnlyDocuments = authOnlyRecords.length > 0 && !allowAuthOnlyDocuments;
  const available =
    !hasConflicts &&
    !hasAuthConflicts &&
    !hasAuthErrors &&
    !blockedByIncompleteDocuments &&
    !blockedByAuthOnlyDocuments &&
    completeRecords.length > 0;
  const size = available
    ? completeRecords.reduce((sum, record) => sum + sumFrameBytes(record.mainFrames), 0)
    : 0;
  const frameDetail = `${primary?.mainFrames.size ?? 0}/${primary?.total ?? "?"} frames`;
  let detail = `Frames ${primary?.mainFrames.size ?? 0}/${primary?.total ?? "?"}`;
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
    detail = `${formatBytes(size)} | ${frameDetail}${docs}`;
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
  const targetInspection = inspectExtensionTarget(
    state.extensionTargetText,
    state.expectedHeadDocHashText,
    state.freshnessUnknownAcknowledged,
  );
  const target = targetInspection.target;
  const allowPartialDocuments = target !== null && target.kind !== "latest";
  const ciphertextSource = selectCiphertextSource(state, {
    allowIncompleteDocuments: allowPartialDocuments,
    allowAuthOnlyDocuments: allowPartialDocuments,
  });
  const rootOnlyCiphertextSource = selectCiphertextSource(state, {
    allowIncompleteDocuments: true,
    allowAuthOnlyDocuments: true,
  });
  const hasDecryptedBackup = Boolean(state.decryptedBackup);
  const documentCount = state.documents.size;
  const hasMultipleDocuments = documentCount > 1;
  const hasExpectedHead = Boolean(target?.expectedHeadDocHashHex);
  const freshnessDecisionReady = targetInspection.decision !== null;
  const freshnessDisabledReason = targetInspection.error?.message ?? "";
  const primary = primaryDocumentRecord(state);
  const canDownloadCipher =
    !hasMultipleDocuments &&
    primary !== null &&
    primary.total !== null &&
    primary.mainFrames.size === primary.total &&
    primary.conflicts === 0;
  return {
    canDownloadCipher,
    downloadCipherDisabledReason: hasMultipleDocuments
      ? "Encrypted file download is only available for one backup document."
      : "Add all backup data first.",
    canDecryptCiphertext:
      state.agePassphrase.length > 0 && ciphertextSource.available && freshnessDecisionReady,
    canDecryptRootOnly:
      state.agePassphrase.length > 0 && rootOnlyCiphertextSource.available && hasExpectedHead,
    decryptDisabledReason:
      state.agePassphrase.length === 0
        ? "Enter your passphrase to unlock."
        : !ciphertextSource.available
          ? "Add backup data first (Step 1)."
          : freshnessDisabledReason,
    rootOnlyDisabledReason:
      state.agePassphrase.length === 0
        ? "Enter your passphrase to unlock."
        : !rootOnlyCiphertextSource.available
          ? "Add backup data first (Step 1)."
          : "Enter the expected root head hash.",
    canDownloadDecryptedBackup: hasDecryptedBackup,
    canCopyResult: Boolean(state.recoveredShardSecret),
    hasMultipleDocuments,
    freshnessDecisionReady,
    hasOutput: state.extractedFiles.length > 0,
  };
}
