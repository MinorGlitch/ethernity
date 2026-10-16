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
  incompleteDocumentRecords,
  documentCounts,
  primaryDocumentRecord,
} from "../documents/store.js";
import { activeShardSetRecord, shardCounts } from "../shard_store.js";
import { formatBytes } from "../format.js";
import { listMissing } from "../frame_list.js";
import { SHARD_KEY_PASSPHRASE, SHARD_KEY_SIGNING_SEED } from "../constants.js";
import { inspectEncryptedDownload, inspectRecoveryInput } from "../recovery_input.js";
import { recoveryErrorMessage } from "../recovery_messages.js";

const TONE_IDLE = "idle";
const TONE_OK = "ok";
const TONE_WARN = "warn";

function diagItem(label, value, tone, detail, prominent = false) {
  return { label, value, detail, tone, prominent };
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
      detail: mainRecords.length > 1 ? `${mainRecords.length} documents added.` : "",
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

  return {
    value: `${missingCount} missing`,
    detail: "Scan or paste the remaining QR codes or text from this backup.",
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

export function selectFrameDiagnostics(state) {
  const missingInfo = describeMissingFrames(state);
  const documentCount = state.documents.size;
  const counts = documentCounts(state);
  const primary = primaryDocumentRecord(state);
  return [
    diagItem(
      "Backup data",
      missingInfo.value,
      missingInfo.tone,
      missingInfo.detail,
      primary !== null,
    ),
    ...incompleteDocumentRecords(state).map((record) => {
      const indexes = listMissing(record.total, record.mainFrames).slice(0, 8);
      const extra = record.total - record.mainFrames.size - indexes.length;
      return diagItem(
        "Missing data indexes",
        `${indexes.join(", ")}${extra > 0 ? ` (+${extra} more)` : ""}`,
        TONE_IDLE,
        `Document ${record.docIdHex}; indexes start at 0, not printed segment numbers.`,
      );
    }),
    diagItem(
      "Documents",
      documentCount ? `${documentCount}` : "Waiting",
      documentCount ? TONE_OK : TONE_IDLE,
    ),
    diagItem("Repeated parts", `${counts.duplicates + counts.authDuplicates}`, TONE_IDLE),
    diagItem("Document ID", primary?.docIdHex ?? "(unknown)", primary ? TONE_OK : TONE_IDLE),
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
  const progress = Array.from(state.shardSets.values(), (record) => {
    const collected = record.shardFrames.size;
    const needed = Math.max(0, record.threshold - collected);
    const label =
      record.keyType === SHARD_KEY_SIGNING_SEED ? "Signing key sheets" : "Passphrase sheets";
    return diagItem(
      label,
      `${collected} of ${record.threshold} needed`,
      needed ? TONE_WARN : TONE_OK,
      state.shardSets.size > 1
        ? `Document ${record.docIdHex}; set ${record.shardSetIdHex || "legacy"}`
        : undefined,
      !state.recoveredShardSecret,
    );
  });
  return [
    ...progress,
    diagItem(
      "Key type",
      shardKeyLabel === "-" ? "Unknown" : shardKeyLabel,
      shardKeyLabel === "-" ? TONE_IDLE : TONE_OK,
    ),
    diagItem("Repeated sheets", `${counts.duplicates}`, TONE_IDLE),
  ];
}

export function selectOutputSummary(state) {
  const count = state.extractedFiles.length;
  const totalBytes = state.extractedFiles.reduce((sum, file) => sum + file.data.length, 0);
  const subtitle = count
    ? `${count} ${count === 1 ? "file" : "files"} | ${formatBytes(totalBytes)}`
    : "";
  return subtitle;
}

export function selectActionState(state) {
  const recovery = inspectRecoveryInput(state);
  const rootRecovery = inspectRecoveryInput(state, "root");
  const hasMultipleDocuments = state.documents.size > 1;
  const download = inspectEncryptedDownload(state);
  return {
    canDownloadCipher: download.error === null,
    downloadCipherDisabledReason: download.error ?? "",
    canDecryptCiphertext: recovery.error === null,
    canDecryptRootOnly: rootRecovery.error === null,
    decryptDisabledReason: recovery.error ? recoveryErrorMessage(recovery.error) : "",
    rootOnlyDisabledReason: rootRecovery.error ? recoveryErrorMessage(rootRecovery.error) : "",
    canDownloadDecryptedBackup: Boolean(state.decryptedBackup),
    canCopyResult: Boolean(state.recoveredShardSecret),
    hasMultipleDocuments,
    freshnessDecisionReady: recovery.decision !== null,
    hasOutput: state.extractedFiles.length > 0,
  };
}
