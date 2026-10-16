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

import { isPassphraseAuthenticationFailure } from "../lib/errors.js";
import { decryptAgePassphrase } from "../lib/age_scrypt.js";
import { recoverDocuments } from "./recovery_worker.js";
import { inspectRecoveryInput } from "./recovery_input.js";
import { collectedRecoveryDocuments } from "./frames_cipher.js";
import { recoveryErrorMessage, recoveryResultStatus } from "./recovery_messages.js";
import { cloneState } from "./state/initial.js";
import {
  clearRecoveryResult,
  dispatchPatch,
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
  const base = getState();
  const input = inspectRecoveryInput(base, options.extensionTarget ?? base.extensionTargetText);
  if (input.error?.code === "PASSPHRASE_REQUIRED") {
    const patch = {};
    setLineStatus(patch, "decryptStatus", input.error.message, "warn");
    dispatchPatch(dispatch, getState, patch);
    return;
  }

  const patch = {};
  clearRecoveryResult(patch);
  let requestId = null;
  let controller = null;
  try {
    if (input.error) throw input.error;
    const documents = collectedRecoveryDocuments(cloneState(base), input.collectionOptions);
    // Revisions survive reset. An older request can never reuse a newer request's id.
    requestId = base.revision + 1;
    dispatchPatch(dispatch, getState, {
      ...patch,
      decryptRequestId: requestId,
      isDecrypting: true,
      decryptStatus: { lines: ["Unlocking backup..."], type: "" },
    });
    cancelActiveDecryptWork();
    controller = new AbortController();
    activeDecryptController = controller;
    const result = await recoverWithMnemonicWhitespaceFallback(
      documents,
      base.agePassphrase,
      decrypt,
      {
        verifySignature,
        extensionTarget: input.target,
        signal: controller.signal,
        freshnessUnknownAcknowledged: base.freshnessUnknownAcknowledged === true,
      },
    );
    const current = getState();
    if (!isCurrentDecryptRequest(current, requestId)) return;
    patch.decryptedBackup = result.selectedExtensionIndex === null ? result.decryptedBackup : null;
    patch.extractedFiles = result.files;
    patch.decryptStatus = recoveryResultStatus(result);
    patch.decryptStatus.lines.push(...ignoredPartialDocumentLines(input.collection));
    if (current.agePassphrase === base.agePassphrase) patch.agePassphrase = "";
  } catch (error) {
    if (requestId !== null && !isCurrentDecryptRequest(getState(), requestId)) return;
    setErrorStatus(patch, "decryptStatus", error, recoveryErrorMessage(error));
  } finally {
    if (activeDecryptController === controller) activeDecryptController = null;
  }
  patch.isDecrypting = false;
  dispatchPatch(dispatch, getState, patch);
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

function ignoredPartialDocumentLines({ incomplete, authOnly }) {
  const lines = [];
  if (incomplete.length) {
    lines.push(
      `Skipped incomplete documents: ${incomplete.map((record) => record.docIdHex).join(", ")}.`,
    );
  }
  if (authOnly.length) {
    lines.push(
      `Skipped documents with only an AUTH section: ${authOnly.map((record) => record.docIdHex).join(", ")}.`,
    );
  }
  return lines;
}

export function clearOutput(dispatch, getState) {
  dispatchPatch(dispatch, getState, { extractedFiles: [], extractStatus: { lines: [], type: "" } });
}
