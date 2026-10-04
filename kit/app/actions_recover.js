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

import { decryptAgePassphrase, INTENSIVE_SCRYPT_APPROVAL_PREFIX } from "../lib/age_scrypt.js";
import { recoverLatestFromEncryptedDocuments } from "./extensions/recovery.js";
import {
  isLatestExtensionTarget,
  normalizeExpectedHeadDocHash,
  normalizeExtensionTarget,
} from "./extensions/target.js";
import { extractFiles } from "./backup_document.js";
import { collectedRecoveryDocuments, reassembleCiphertext } from "./frames_cipher.js";
import { formatBytes } from "./format.js";
import { authOnlyDocumentRecords, incompleteDocumentRecords } from "./documents/store.js";
import { cloneState } from "./state/initial.js";
import {
  applyExtractResult,
  clearDecryptedBackup,
  clearRecoveredOutput,
  cloneLatest,
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
  clearRecoveredOutput(prep);
  clearDecryptedBackup(prep);
  let didStartDecrypt = false;
  let finalState = null;
  let decryptController = null;
  let extensionTarget = null;
  try {
    extensionTarget =
      options.allowResourceIntensiveScrypt && base.intensiveRecoveryTarget
        ? base.intensiveRecoveryTarget
        : resolveExtensionTarget(prep, options);
    if (prep.conflicts > 0) {
      throw new Error("conflicting duplicate frames detected");
    }
    if (prep.authConflicts > 0) {
      throw new Error("conflicting AUTH frames detected");
    }
    if (prep.authErrors > 0) {
      throw new Error("invalid AUTH frames detected");
    }
    if (!prep.ciphertext && prep.total && prep.mainFrames.size === prep.total) {
      prep.ciphertext = reassembleCiphertext(prep);
    }
    const allowPartialDocuments = !isLatestExtensionTarget(extensionTarget);
    const ignoredDocumentLines = allowPartialDocuments ? ignoredPartialDocumentLines(prep) : [];
    const documents = collectedRecoveryDocuments(prep, {
      allowIncomplete: allowPartialDocuments,
      allowAuthOnly: allowPartialDocuments,
    });
    if (!documents.length) {
      throw new Error("Collected ciphertext not available yet.");
    }
    prep.decryptRequestId = base.decryptRequestId + 1;
    prep.isDecrypting = true;
    prep.intensiveRecoveryTarget = null;
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
        allowResourceIntensiveScrypt: options.allowResourceIntensiveScrypt === true,
        freshnessUnknownAcknowledged: prep.freshnessUnknownAcknowledged === true,
      },
    );
    const next = cloneLatest(getState);
    if (!isCurrentDecryptRequest(next, requestId)) {
      return;
    }
    next.decryptedBackup = result.selectedExtensionIndex === null ? result.decryptedBackup : null;
    next.decryptedBackupSource = "Collected ciphertext";
    applyExtractResult(next, result);
    next.isDecrypting = false;
    next.intensiveRecoveryTarget = null;
    next.recoveryComplete = true;
    next.decryptStatus = {
      lines: [
        "Recovery complete.",
        `${result.files.length} file(s) recovered (${formatBytes(totalRecoveredBytes(result.files))}).`,
        ...extensionRecoveryLines(result),
        ...ignoredDocumentLines,
      ],
      type: "ok",
    };
    if (next.agePassphrase === base.agePassphrase) {
      next.agePassphrase = "";
    }
    finalState = next;
  } catch (err) {
    const next = didStartDecrypt ? cloneLatest(getState) : prep;
    if (didStartDecrypt && !isCurrentDecryptRequest(next, prep.decryptRequestId)) {
      return;
    }
    next.isDecrypting = false;
    const errorMsg = String(err);
    const friendlyError = recoveryFriendlyError(errorMsg);
    const intensiveApprovalRequired = errorMsg.includes(INTENSIVE_SCRYPT_APPROVAL_PREFIX);
    next.intensiveRecoveryTarget = intensiveApprovalRequired ? extensionTarget : null;
    setLineStatus(
      next,
      "decryptStatus",
      friendlyError,
      intensiveApprovalRequired ? "warn" : "error",
    );
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
    return await recoverLatestFromEncryptedDocuments(
      documents,
      passphrase,
      decrypt,
      recoveryOptions,
    );
  } catch (error) {
    const fallback = mnemonicWhitespaceFallback(passphrase);
    if (fallback === null || !isPassphraseAuthenticationFailure(error)) {
      throw error;
    }
    return recoverLatestFromEncryptedDocuments(documents, fallback, decrypt, recoveryOptions);
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

function isPassphraseAuthenticationFailure(error) {
  return String(error).toLowerCase().includes("invalid passphrase");
}

function isCurrentDecryptRequest(state, requestId) {
  return state.isDecrypting && state.decryptRequestId === requestId;
}

function recoveryFriendlyError(errorMsg) {
  if (errorMsg.includes(INTENSIVE_SCRYPT_APPROVAL_PREFIX)) {
    return errorMsg.split(INTENSIVE_SCRYPT_APPROVAL_PREFIX, 2)[1].trim();
  }
  if (
    errorMsg.includes("selected extension doc_hash") ||
    errorMsg.includes("supplied backup documents")
  ) {
    return errorMsg;
  }
  if (errorMsg.includes("password")) {
    return "Incorrect passphrase.";
  }
  if (errorMsg.includes("decrypt")) {
    return "Could not unlock backup. Check passphrase.";
  }
  return errorMsg;
}

function resolveExtensionTarget(state, options) {
  const expectedHeadDocHashHex = normalizeExpectedHeadDocHash(state.expectedHeadDocHashText);
  if (options.extensionTarget !== undefined) {
    return normalizeExtensionTarget(options.extensionTarget, expectedHeadDocHashHex);
  }
  return normalizeExtensionTarget(state.extensionTargetText, expectedHeadDocHashHex);
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

function totalRecoveredBytes(files) {
  return files.reduce((sum, file) => sum + file.data.length, 0);
}

function extensionRecoveryLines(result) {
  const trustLines = recoveryTrustLines(result);
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

export async function extractBackupFiles(dispatch, getState) {
  const base = cloneState(getState());
  try {
    clearRecoveredOutput(base);
    if (!base.decryptedBackup) {
      throw new Error("No decrypted document available yet.");
    }
    const result = await extractFiles(base.decryptedBackup);
    applyExtractResult(base, result);
    dispatchState(dispatch, base);
  } catch (err) {
    setErrorStatus(base, "extractStatus", err);
    dispatchState(dispatch, base);
  }
}

export function clearOutput(dispatch, getState) {
  dispatchPatch(dispatch, getState, { extractedFiles: [], extractStatus: { lines: [], type: "" } });
}
