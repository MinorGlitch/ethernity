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

import { RecoveryError, isPassphraseAuthenticationFailure } from "../lib/errors.js";
import { decryptAgePassphrase } from "../lib/age_scrypt.js";
import { recoverDocuments } from "./recovery_worker.js";
import { isLatestExtensionTarget, normalizeExtensionTarget } from "./extensions/target.js";
import { collectedRecoveryDocuments } from "./frames_cipher.js";
import {
  authOnlyDocumentRecords,
  incompleteDocumentRecords,
  documentCounts,
} from "./documents/store.js";
import { cloneState } from "./state/initial.js";
import {
  applyExtractResult,
  clearRecoveryResult,
  dispatchPatch,
  dispatchState,
  setErrorStatus,
  setLineStatus,
} from "./state_actions.js";

let activeDecryptController = null;

const MNEMONIC_WORD_COUNTS = new Set([12, 15, 18, 21, 24]);
const MNEMONIC_WORD_SHAPE = /^[a-z]{3,8}$/u;

export function cancelActiveDecryptWork() {
  activeDecryptController?.abort();
  activeDecryptController = null;
}

export async function decryptCiphertext(dispatch, getState, options = {}) {
  const { decrypt = decryptAgePassphrase, verifySignature } = options;
  const base = cloneState(getState());
  if (base.agePassphrase.length === 0) {
    setLineStatus(base, "decryptStatus", "Passphrase required.", "warn");
    dispatchState(dispatch, base);
    return;
  }
  const prep = cloneState(base);
  clearRecoveryResult(prep);
  let didStartDecrypt = false;
  let finalState = null;
  let decryptController = null;
  try {
    const extensionTarget = resolveExtensionTarget(prep, options);
    const counts = documentCounts(prep);
    if (counts.conflicts > 0) {
      throw new RecoveryError("DOCUMENT_INVALID", "conflicting duplicate frames detected");
    }
    if (counts.authConflicts > 0) {
      throw new RecoveryError("AUTH_CONFLICT", "conflicting AUTH frames detected");
    }
    if (counts.authErrors > 0) {
      throw new RecoveryError("AUTH_PAYLOAD_INVALID", "invalid AUTH frames detected");
    }
    const allowPartialDocuments = !isLatestExtensionTarget(extensionTarget);
    const ignoredDocumentLines = allowPartialDocuments ? ignoredPartialDocumentLines(prep) : [];
    const documents = collectedRecoveryDocuments(prep, {
      allowIncomplete: allowPartialDocuments,
      allowAuthOnly: allowPartialDocuments,
    });
    if (!documents.length) {
      throw new RecoveryError("INPUT_REQUIRED", "Collected ciphertext not available yet.");
    }
    prep.decryptRequestId = base.decryptRequestId + 1;
    prep.isDecrypting = true;
    setLineStatus(prep, "decryptStatus", "Unlocking backup...");
    const requestId = prep.decryptRequestId;
    dispatchState(dispatch, prep);
    didStartDecrypt = true;
    cancelActiveDecryptWork();
    decryptController = new AbortController();
    activeDecryptController = decryptController;

    const result = await recoverWithMnemonicWhitespaceFallback(
      documents,
      prep.agePassphrase,
      decrypt,
      {
        verifySignature,
        extensionTarget,
        signal: decryptController.signal,
        freshnessUnknownAcknowledged: prep.freshnessUnknownAcknowledged === true,
      },
    );
    const next = cloneState(getState());
    if (!isCurrentDecryptRequest(next, requestId)) {
      return;
    }
    next.decryptedBackup = result.selectedExtensionIndex === null ? result.decryptedBackup : null;
    applyExtractResult(next, result);
    next.isDecrypting = false;
    next.decryptStatus = {
      lines: [...extensionRecoveryLines(result), ...ignoredDocumentLines],
      type: "ok",
    };
    if (next.agePassphrase === base.agePassphrase) {
      next.agePassphrase = "";
    }
    finalState = next;
  } catch (err) {
    const next = didStartDecrypt ? cloneState(getState()) : prep;
    if (didStartDecrypt && !isCurrentDecryptRequest(next, prep.decryptRequestId)) {
      return;
    }
    next.isDecrypting = false;
    setErrorStatus(next, "decryptStatus", err, recoveryFriendlyError(err));
    finalState = next;
  } finally {
    if (activeDecryptController === decryptController) {
      activeDecryptController = null;
    }
  }
  dispatchState(dispatch, finalState);
}

async function recoverWithMnemonicWhitespaceFallback(
  documents,
  passphrase,
  decrypt,
  recoveryOptions,
) {
  try {
    return await recoverDocuments(documents, passphrase, decrypt, recoveryOptions);
  } catch (error) {
    const fallback = mnemonicWhitespaceFallback(passphrase);
    if (fallback === null || !isPassphraseAuthenticationFailure(error)) {
      throw error;
    }
    return recoverDocuments(documents, fallback, decrypt, recoveryOptions);
  }
}

function mnemonicWhitespaceFallback(passphrase) {
  // Custom secrets stay exact. This mnemonic-shaped candidate is only tried after the exact
  // value fails authenticated decryption, so no checksum or word-list guess can rewrite a key.
  const words = passphrase.trim().split(/\s+/u);
  if (
    !MNEMONIC_WORD_COUNTS.has(words.length) ||
    words.some((word) => !MNEMONIC_WORD_SHAPE.test(word))
  ) {
    return null;
  }
  const normalized = words.join(" ");
  return normalized === passphrase ? null : normalized;
}

function isCurrentDecryptRequest(state, requestId) {
  return state.isDecrypting && state.decryptRequestId === requestId;
}

function recoveryFriendlyError(error) {
  if (isPassphraseAuthenticationFailure(error)) {
    return "Incorrect passphrase.";
  }
  return error instanceof Error ? error.message : String(error);
}

function resolveExtensionTarget(state, options) {
  return normalizeExtensionTarget(
    options.extensionTarget ?? state.extensionTargetText,
    state.expectedHeadDocHashText,
  );
}

function ignoredPartialDocumentLines(state) {
  const lines = [];
  const incomplete = incompleteDocumentRecords(state);
  const authOnly = authOnlyDocumentRecords(state);
  if (incomplete.length) {
    lines.push(`Ignored ${incomplete.length} incomplete non-root backup document(s).`);
  }
  if (authOnly.length) {
    lines.push(`Ignored ${authOnly.length} AUTH-only non-root backup document(s).`);
  }
  return lines;
}

function extensionRecoveryLines(result) {
  const trustLines = recoveryTrustLines(result);
  if (result.updateMode) {
    trustLines.unshift(
      result.updateMode === "cumulative"
        ? "Cumulative update: original backup plus the selected update."
        : "Incremental update: original backup and every update through the selected version.",
    );
  }
  if (result.replayTarget === "root") {
    return ["Replay target: root backup only.", ...trustLines];
  }
  if (result.selectedExtensionIndex === null) {
    return trustLines;
  }
  if (result.replayTarget === "extension") {
    return [
      `Replay target: supplied extension ${result.selectedExtensionIndex}.`,
      `Extension doc hash: ${result.selectedExtensionDocHash}.`,
      ...trustLines,
    ];
  }
  return [
    `Replay target: latest supplied extension ${result.selectedExtensionIndex}.`,
    ...trustLines,
  ];
}

function recoveryTrustLines(result) {
  if (result.trustBasis === "matched_expected_head") {
    return [
      result.signingKeyVerified
        ? "Trust: Matched expected fingerprint; root identity, signing key, and selected head are bound."
        : "Trust: Matched expected fingerprint; backup identity is bound. The sealed backup hash does not bind its signing key.",
      "Freshness: matched the manually entered expected head hash.",
    ];
  }
  const lines = ["Trust: Internally consistent; no independently trusted fingerprint matched."];
  if (result.freshnessDecision === "manual_expected_head") {
    lines.push("Freshness: matched the manually entered expected head hash.");
  } else if (result.freshnessDecision === "supplied_pages_freshness_unknown") {
    lines.push("Freshness: unknown beyond supplied pages; explicit acknowledgement used.");
  }
  return lines;
}

export function clearOutput(dispatch, getState) {
  dispatchPatch(dispatch, getState, { extractedFiles: [], extractStatus: { lines: [], type: "" } });
}
