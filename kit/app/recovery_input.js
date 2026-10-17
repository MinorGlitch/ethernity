/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */
import { RecoveryError } from "../lib/errors.js";
import { documentCounts, primaryDocumentRecord } from "./documents/store.js";
import { inspectExtensionTarget } from "./extensions/target.js";
import { inspectCollectedDocuments } from "./frames_cipher.js";

// Both the button state and the action use this assessment. The recovery engine
// independently verifies the selected documents and their signatures.
export function inspectRecoveryInput(state, targetValue = state.extensionTargetText) {
  const target = inspectExtensionTarget(
    targetValue,
    state.expectedHeadDocHashText,
    state.freshnessUnknownAcknowledged,
  );
  const allowPartial = target.target !== null && target.target.kind !== "latest";
  const collectionOptions = { allowIncomplete: allowPartial, allowAuthOnly: allowPartial };
  const collection = inspectCollectedDocuments(state, collectionOptions);
  const error = !state.agePassphrase
    ? new RecoveryError("PASSPHRASE_REQUIRED", "Enter your passphrase.")
    : target.target === null
      ? target.error
      : (collection.error ?? target.error);
  return { target: target.target, collection, collectionOptions, error, decision: target.decision };
}

export function inspectEncryptedDownload(state) {
  const record = primaryDocumentRecord(state);
  const error = documentCounts(state).conflicts
    ? "Two copies contain different data. Start over with one matching page set."
    : state.documents.size > 1
      ? "Encrypted file download is only available for one backup document."
      : !record || record.total === null || record.mainFrames.size !== record.total
        ? "Add all backup data first."
        : null;
  return { record, error };
}
