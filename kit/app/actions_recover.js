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
import { extractFiles } from "./envelope.js";
import { collectedRecoveryDocuments, reassembleCiphertext } from "./frames_cipher.js";
import { formatBytes } from "./format.js";
import { authOnlyDocumentRecords, incompleteDocumentRecords } from "./documents/store.js";
import { cloneState } from "./state/initial.js";
import { readEmbeddedKitMetadata } from "./kit_anchor.js";
import {
  applyExtractResult,
  clearDecryptedEnvelope,
  clearRecoveredOutput,
  cloneLatest,
  dispatchPatch,
  dispatchState,
  setErrorStatus,
  setLineStatus,
} from "./actions_common.js";

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
  clearDecryptedEnvelope(prep);
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
    const allowPartialDocuments = !isLatestTarget(extensionTarget);
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
        recoveryAnchor: anchoredKitMetadata(),
        freshnessUnknownAcknowledged: prep.freshnessUnknownAcknowledged === true,
      },
    );
    const next = cloneLatest(getState);
    if (!isCurrentDecryptRequest(next, requestId)) {
      return;
    }
    next.decryptedEnvelope =
      result.selectedExtensionIndex === null ? result.decryptedEnvelope : null;
    next.decryptedEnvelopeSource = "Collected ciphertext";
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
  const canonical = words.join(" ");
  return canonical === passphrase ? null : canonical;
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
  const anchor = anchoredKitMetadata();
  if (anchor) {
    if (
      options.extensionTarget !== undefined &&
      !isLatestTarget(options.extensionTarget) &&
      !isRootTarget(options.extensionTarget)
    ) {
      throw new Error(
        "chain-bound recovery kits recover only their pinned head or the pinned root",
      );
    }
    return withExpectedHead(options.extensionTarget ?? "latest", anchor.expectedLatestHeadHashHex);
  }
  const expectedHeadDocHashHex = normalizeExpectedHeadDocHash(state.expectedHeadDocHashText);
  if (options.extensionTarget !== undefined) {
    return withExpectedHead(options.extensionTarget, expectedHeadDocHashHex);
  }
  return parseExtensionTarget(state.extensionTargetText, expectedHeadDocHashHex);
}

function anchoredKitMetadata() {
  const metadata = readEmbeddedKitMetadata();
  return metadata?.anchored ? metadata : null;
}

function parseExtensionTarget(value, expectedHeadDocHashHex) {
  const target = String(value ?? "").trim();
  if (!target || target.toLowerCase() === "latest") {
    return withExpectedHead("latest", expectedHeadDocHashHex);
  }
  const latestMatch = target.match(/^latest:([0-9a-fA-F]{64})$/);
  if (latestMatch) {
    const inlineExpectedHeadDocHashHex = latestMatch[1].toLowerCase();
    if (expectedHeadDocHashHex && expectedHeadDocHashHex !== inlineExpectedHeadDocHashHex) {
      throw new Error("expected head doc hash conflicts with latest:<doc hash> target");
    }
    return {
      kind: "latest",
      expectedHeadDocHashHex: inlineExpectedHeadDocHashHex,
    };
  }
  if (target.toLowerCase() === "root" || target === "0") {
    return withExpectedHead("root", expectedHeadDocHashHex);
  }
  if (/^[1-9]\d*$/.test(target)) {
    return withExpectedHead(
      { kind: "index", index: Number.parseInt(target, 10) },
      expectedHeadDocHashHex,
    );
  }
  const hash = target.toLowerCase();
  if (/^[0-9a-f]{64}$/.test(hash)) {
    return withExpectedHead({ kind: "doc_hash", docHashHex: hash }, expectedHeadDocHashHex);
  }
  throw new Error(
    "extension target must be latest, latest:<doc hash>, root, an extension index, or a doc hash",
  );
}

function normalizeExpectedHeadDocHash(value) {
  const text = String(value ?? "").trim();
  if (!text) {
    return null;
  }
  const hash = text.toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(hash)) {
    throw new Error("expected head doc hash must be 64 hex characters");
  }
  return hash;
}

function withExpectedHead(target, expectedHeadDocHashHex) {
  if (!expectedHeadDocHashHex) {
    return target;
  }
  if (target === "latest") {
    return { kind: "latest", expectedHeadDocHashHex };
  }
  if (target === "root") {
    return { kind: "root", expectedHeadDocHashHex };
  }
  if (target && typeof target === "object" && target.expectedHeadDocHashHex) {
    if (target.expectedHeadDocHashHex.toLowerCase() !== expectedHeadDocHashHex) {
      throw new Error("expected head doc hash conflicts with extension recovery target");
    }
    return target;
  }
  if (target && typeof target === "object") {
    return { ...target, expectedHeadDocHashHex };
  }
  return target;
}

function isLatestTarget(extensionTarget) {
  return !extensionTarget || extensionTarget === "latest" || extensionTarget?.kind === "latest";
}

function isRootTarget(extensionTarget) {
  return extensionTarget === "root" || extensionTarget === 0 || extensionTarget?.kind === "root";
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
  if (result.trustBasis === "matched_trusted_kit") {
    return [
      "Trust: Matched trusted kit — root identity, signing key, and expected head match the separately stored anchor.",
    ];
  }
  const lines = [
    "Trust: Internally consistent — signatures agree with keys carried by the supplied set.",
  ];
  if (result.freshnessDecision === "manual_expected_head") {
    lines.push("Freshness: matched the manually entered expected head hash.");
  } else if (result.freshnessDecision === "supplied_pages_freshness_unknown") {
    lines.push("Freshness: unknown beyond supplied pages; explicit acknowledgement used.");
  }
  return lines;
}

export async function extractEnvelope(dispatch, getState) {
  const base = cloneState(getState());
  try {
    clearRecoveredOutput(base);
    if (!base.decryptedEnvelope) {
      throw new Error("No decrypted envelope available yet.");
    }
    const result = await extractFiles(base.decryptedEnvelope);
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
