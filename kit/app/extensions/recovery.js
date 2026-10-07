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
  RecoveryError,
  asRecoveryError,
  isPassphraseAuthenticationFailure,
} from "../../lib/errors.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesEqual, bytesToHex } from "../../lib/bytes.js";
import { EXTENSION_DOCUMENT_VERSION, BACKUP_DOCUMENT_VERSIONS } from "../constants.js";
import { documentIdentityFromCiphertext } from "../documents/identity.js";
import { extractFiles, readDocumentVersion } from "../backup_document.js";
import { decodeExtensionDocumentHeader, reconstructLatestFilesFromDocuments } from "./document.js";
import {
  deriveSigningPublicKey,
  requireVerifiedAuthPayload,
  verifyAuthSignature,
} from "../auth.js";
import { enforceRecoveryDocumentBudget } from "../frames_cipher.js";
import { normalizeExtensionTarget, requireFreshnessDecision } from "./target.js";

export async function recoverLatestFromPlaintextDocuments(
  documents,
  {
    verifySignature = verifyAuthSignature,
    extensionTarget = "latest",
    freshnessUnknownAcknowledged = false,
  } = {},
) {
  if (!documents.length) {
    throw new RecoveryError("INPUT_REQUIRED", "Collected ciphertext not available yet.");
  }
  enforceRecoveryDocumentBudget(documents, { byteField: "plaintext", byteLabel: "plaintext" });
  const target = normalizeExtensionTarget(extensionTarget);
  const freshnessDecision = requireFreshnessDecision(target, freshnessUnknownAcknowledged);
  const rootOnly = target.kind === "root";
  const decoded = [];
  const decodeErrors = [];
  for (const document of documents) {
    try {
      const version = readDocumentVersion(document.plaintext);
      if (BACKUP_DOCUMENT_VERSIONS.has(version)) {
        decoded.push({
          kind: "root",
          document,
          extracted: await extractFiles(document.plaintext),
        });
      } else if (version === EXTENSION_DOCUMENT_VERSION) {
        decoded.push({
          kind: "extension",
          document,
        });
      } else {
        decodeErrors.push({
          document,
          error: new RecoveryError("DOCUMENT_INVALID", `unsupported document version: ${version}`),
        });
      }
    } catch (err) {
      decodeErrors.push({ document, error: asRecoveryError(err) });
    }
  }

  const roots = decoded.filter((item) => item.kind === "root");
  if (roots.length !== 1) {
    if (!roots.length && decodeErrors.length) {
      throw new RecoveryError(
        "DOCUMENT_INVALID",
        `content import did not contain a decryptable root backup: ${decodeErrors[0].error.message}`,
        { cause: decodeErrors[0].error },
      );
    }
    throw new RecoveryError(
      "DOCUMENT_INVALID",
      `content import must contain exactly one root backup (${roots.length} found)`,
    );
  }
  const root = roots[0];
  const rawExtensions = decoded.filter((item) => item.kind === "extension");
  for (const failure of decodeErrors) {
    throwIfSelectedDocHashFailure(target, failure.document, "decoded", failure.error);
  }
  if (decodeErrors.length && documents.length > 1 && target.kind === "latest") {
    throw new RecoveryError(
      "SUPPLIED_DOCUMENT_FAILED",
      "one or more supplied backup documents could not be decoded",
      { cause: decodeErrors[0].error },
    );
  }
  const suppliedRootAuthPayload = await verifySuppliedRootAuth(root, verifySignature);
  if (rootOnly || !rawExtensions.length) {
    if (!rootOnly && target.kind !== "latest") {
      throw new RecoveryError(
        "RECOVERY_TARGET_INVALID",
        "requested extension target was not supplied",
      );
    }
    ensureExpectedHeadSatisfied(target, root.document.docHashHex);
    return {
      files: root.extracted.files,
      manifest: root.extracted.manifest,
      selectedExtensionIndex: null,
      selectedExtensionDocHash: null,
      freshnessScope: null,
      freshnessDecision,
      ...recoveryTrustDetails(target, root.extracted.manifest),
      decryptedBackup: root.document.plaintext,
      replayTarget: rootOnly ? "root" : "latest",
      suppliedDocumentCount: documents.length,
    };
  }

  const rootSigningPublicKey = deriveRootSigningPublicKey(root.extracted.manifest);
  if (!suppliedRootAuthPayload) {
    await requireVerifiedAuthPayload(root.document, rootSigningPublicKey, verifySignature);
  }
  const authenticatedExtensions = [];
  const extensionFailures = [];
  for (const item of rawExtensions) {
    let authPayload;
    try {
      authPayload = await requireVerifiedAuthPayload(
        item.document,
        rootSigningPublicKey,
        verifySignature,
      );
    } catch (err) {
      throwIfSelectedDocHashFailure(target, item.document, "trusted", err);
      extensionFailures.push(asRecoveryError(err, "AUTH_VERIFICATION_FAILED"));
      continue;
    }
    let header;
    try {
      header = decodeExtensionDocumentHeader(item.document.plaintext);
    } catch (err) {
      const error = extensionDecodeFailure(err);
      throwIfSelectedDocHashFailure(target, item.document, "decoded", error);
      extensionFailures.push(error);
      continue;
    }
    if (!bytesEqual(header.rootDocHash, root.document.docHash)) {
      const error = new RecoveryError(
        "DOCUMENT_INTEGRITY_FAILED",
        "extension root_doc_hash does not match root backup",
      );
      throwIfSelectedDocHashFailure(target, item.document, "trusted", error);
      extensionFailures.push(error);
      continue;
    }
    authenticatedExtensions.push({
      header,
      document: item.document,
      docHash: item.document.docHash,
      docHashHex: item.document.docHashHex,
      authPayload,
    });
  }
  for (const failure of decodeErrors) {
    if (
      await documentHasVerifiedRootSignature(
        failure.document,
        rootSigningPublicKey,
        verifySignature,
      )
    ) {
      extensionFailures.push(extensionDecodeFailure(failure.error));
    }
  }
  if (target.kind === "latest" && extensionFailures.length) {
    throw extensionFailures[0];
  }

  const selectedHeaders = selectSuppliedChainForTarget(authenticatedExtensions, target);
  let files;
  try {
    files = await reconstructLatestFilesFromDocuments(
      root.extracted.files,
      root.document.docHash,
      selectedHeaders.map((item) => ({
        header: item.header,
        plaintext: item.document.plaintext,
        docHash: item.document.docHash,
      })),
    );
  } catch (err) {
    const error = extensionDecodeFailure(err);
    const selectedDocument = selectedHeaders.at(-1)?.document;
    if (selectedDocument) {
      throwIfSelectedDocHashFailure(target, selectedDocument, "decoded", error);
    }
    throw error;
  }
  const latest = selectedHeaders.at(-1);
  ensureExpectedHeadSatisfied(target, latest?.docHashHex ?? root.document.docHashHex);
  return {
    files,
    manifest: selectedHeaders.length
      ? manifestForRecoveredFiles(root.extracted.manifest, files)
      : root.extracted.manifest,
    selectedExtensionIndex: latest?.header.index ?? null,
    updateMode: latest?.header.updateMode ?? null,
    selectedExtensionDocHash: latest?.docHashHex ?? null,
    freshnessScope: selectedHeaders.length ? "supplied_carriers_only" : null,
    freshnessDecision,
    ...recoveryTrustDetails(target, root.extracted.manifest),
    decryptedBackup: root.document.plaintext,
    replayTarget: target.kind === "latest" ? "latest" : "extension",
    suppliedDocumentCount: documents.length,
  };
}

export async function recoverLatestFromEncryptedDocuments(
  documents,
  passphrase,
  decrypt,
  {
    verifySignature = verifyAuthSignature,
    extensionTarget = "latest",
    signal,
    freshnessUnknownAcknowledged = false,
  } = {},
) {
  const target = normalizeExtensionTarget(extensionTarget);
  requireFreshnessDecision(target, freshnessUnknownAcknowledged);
  enforceRecoveryDocumentBudget(documents);
  const authPreflight = await preflightEncryptedDocumentAuth(documents, verifySignature);
  const decryptPreflight =
    typeof decrypt.preflightBatch === "function"
      ? decrypt.preflightBatch(documents.map((document) => document.ciphertext))
      : null;
  if (target.kind === "latest") {
    const firstAuthError = authPreflight.errors.find(Boolean);
    if (firstAuthError) {
      throw firstAuthError;
    }
    if (authPreflight.hasMultipleSigningKeys) {
      throw new RecoveryError(
        "ROOT_SIGNING_KEY_MISMATCH",
        "supplied AUTH payloads contain multiple signing keys",
      );
    }
    const firstPreflightError = decryptPreflight?.errors?.find(Boolean);
    if (firstPreflightError) {
      throw firstPreflightError;
    }
  }
  const plaintextDocuments = [];
  const decryptErrors = [];
  for (const [documentIndex, document] of authPreflight.documents.entries()) {
    if (signal?.aborted) {
      throw new RecoveryError("CANCELLED", "recovery decryption was cancelled");
    }
    const identifiedDocument = document;
    try {
      const authError = authPreflight.errors[documentIndex];
      if (authError) {
        throw authError;
      }
      const preflightError = decryptPreflight?.errors?.[documentIndex];
      if (preflightError) {
        throw preflightError;
      }
      const plaintext = await decrypt(document.ciphertext, passphrase, { signal });
      plaintextDocuments.push({
        ...identifiedDocument,
        plaintext,
      });
    } catch (err) {
      const error = asRecoveryError(err);
      if (error.code === "CANCELLED") throw error;
      decryptErrors.push({ document: identifiedDocument, error });
    }
  }
  const failures = decryptErrors.map((failure) => failure.error);
  // Retry a mnemonic only when every document rejected the exact passphrase.
  if (
    !plaintextDocuments.length &&
    failures.length &&
    failures.every(isPassphraseAuthenticationFailure)
  ) {
    throw failures[0];
  }
  for (const failure of decryptErrors) {
    throwIfSelectedDocHashFailure(target, failure.document, "decrypted", failure.error);
  }
  if (!plaintextDocuments.length) {
    throw (
      failures.find((error) => !isPassphraseAuthenticationFailure(error)) ??
      new RecoveryError("INPUT_REQUIRED", "Collected ciphertext not available yet.")
    );
  }
  if (decryptErrors.length && documents.length > 1 && target.kind === "latest") {
    throw new RecoveryError(
      "SUPPLIED_DOCUMENT_FAILED",
      "one or more supplied backup documents could not be decrypted",
      {
        cause: decryptErrors[0].error,
      },
    );
  }
  const result = await recoverLatestFromPlaintextDocuments(plaintextDocuments, {
    verifySignature,
    extensionTarget: target,
    freshnessUnknownAcknowledged,
  });
  return result;
}

async function preflightEncryptedDocumentAuth(documents, verifySignature) {
  const identifiedDocuments = [];
  const errors = [];
  const signingKeys = new Set();
  for (const document of documents) {
    let identifiedDocument = document;
    let error = null;
    try {
      const identity = documentIdentityFromCiphertext(document.ciphertext);
      identifiedDocument = {
        ...document,
        ...identity,
      };
      assertSuppliedDocumentIdentityMatches(document, identity);
    } catch (err) {
      error = asRecoveryError(err);
    }
    if (identifiedDocument.authPayload) {
      try {
        const payload = await requireVerifiedAuthPayload(identifiedDocument, null, verifySignature);
        signingKeys.add(bytesToHex(payload.signPub));
      } catch (err) {
        error ??= asRecoveryError(err, "AUTH_VERIFICATION_FAILED");
      }
    }
    identifiedDocuments.push(identifiedDocument);
    errors.push(error);
  }
  return {
    documents: identifiedDocuments,
    errors,
    hasMultipleSigningKeys: signingKeys.size > 1,
  };
}

function assertSuppliedDocumentIdentityMatches(document, identity) {
  assertSuppliedBytesMatch(document.docHash, identity.docHash, "doc_hash");
  assertSuppliedHexMatch(document.docHashHex, identity.docHashHex, "doc_hash_hex");
  assertSuppliedBytesMatch(document.docId, identity.docId, "doc_id");
  assertSuppliedHexMatch(document.docIdHex, identity.docIdHex, "doc_id_hex");
}

function assertSuppliedBytesMatch(value, expected, label) {
  if (value === undefined || value === null) {
    return;
  }
  if (!(value instanceof Uint8Array)) {
    throw new RecoveryError("DOCUMENT_INTEGRITY_FAILED", `supplied ${label} must be bytes`);
  }
  if (!bytesEqual(value, expected)) {
    throw new RecoveryError(
      "DOCUMENT_INTEGRITY_FAILED",
      `supplied ${label} does not match derived ciphertext identity`,
    );
  }
}

function assertSuppliedHexMatch(value, expected, label) {
  if (value === undefined || value === null || value === "") {
    return;
  }
  if (String(value).toLowerCase() !== expected) {
    throw new RecoveryError(
      "DOCUMENT_INTEGRITY_FAILED",
      `supplied ${label} does not match derived ciphertext identity`,
    );
  }
}

function manifestForRecoveredFiles(rootManifest, files) {
  return {
    ...rootManifest,
    inputOrigin: "directory",
    inputRoots: ["reconstructed-state"],
    pathEncoding: "direct",
    payloadCodec: "raw",
    payloadRawLen: null,
    entries: files.map((file) => ({
      path: file.path,
      size: file.data.length,
      sha: sha256(file.data),
      mtime: file.mtime ?? null,
    })),
  };
}

function recoveryTrustDetails(target, manifest) {
  if (target.expectedHeadDocHashHex || target.kind === "doc_hash") {
    return {
      trustBasis: "matched_expected_head",
      signingKeyVerified: Boolean(manifest.signingSeed),
    };
  }
  return { trustBasis: "internally_consistent", signingKeyVerified: false };
}

function ensureExpectedHeadSatisfied(target, actualHeadDocHashHex) {
  if (!target.expectedHeadDocHashHex) {
    return;
  }
  if (actualHeadDocHashHex !== target.expectedHeadDocHashHex) {
    throw new RecoveryError(
      "RECOVERY_TARGET_INVALID",
      `validated extension head doc_hash does not match expected head ${target.expectedHeadDocHashHex}; latest supplied head is ${actualHeadDocHashHex}`,
    );
  }
}

function extensionDecodeFailure(error) {
  return new RecoveryError(
    "DOCUMENT_INVALID",
    `extension signed by the root key could not be decoded: ${String(error)}`,
    { cause: error },
  );
}

function throwIfSelectedDocHashFailure(target, document, verb, error) {
  if (target.kind !== "doc_hash" || document.docHashHex !== target.docHashHex) {
    return;
  }
  throw new RecoveryError(
    "SELECTED_DOCUMENT_FAILED",
    `selected extension doc_hash ${target.docHashHex} could not be ${verb}: ${error instanceof Error ? error.message : String(error)}`,
    { cause: error },
  );
}

function deriveRootSigningPublicKey(manifest) {
  if (!manifest?.signingSeed) {
    throw new RecoveryError(
      "AUTH_REQUIRED",
      "extension replay requires an unsealed root backup with its signing seed",
    );
  }
  return deriveSigningPublicKey(manifest.signingSeed);
}

async function verifySuppliedRootAuth(root, verifySignature) {
  if (!root.document.authPayload) {
    return null;
  }
  const expectedSignPub = root.extracted.manifest?.signingSeed
    ? deriveSigningPublicKey(root.extracted.manifest.signingSeed)
    : null;
  return requireVerifiedAuthPayload(root.document, expectedSignPub, verifySignature);
}

function selectLatestSuppliedChain(extensions) {
  const byIndex = new Map();
  for (const extension of extensions) {
    const index = extension.header.index;
    const existing = byIndex.get(index);
    if (existing && existing.docHashHex !== extension.docHashHex) {
      throw new RecoveryError(
        "RECOVERY_TARGET_INVALID",
        `content import contains multiple authenticated extensions for index ${index}`,
      );
    }
    byIndex.set(index, extension);
  }
  return Array.from(byIndex.keys())
    .sort((left, right) => left - right)
    .map((index) => byIndex.get(index));
}

function selectSuppliedChainForTarget(extensions, target) {
  if (target.kind === "latest") {
    return selectLatestSuppliedChain(extensions);
  }
  if (target.kind === "index") {
    const selected = selectLatestSuppliedChain(
      extensions.filter((extension) => extension.header.index <= target.index),
    );
    const latest = selected.at(-1);
    if (!latest || latest.header.index !== target.index) {
      throw new RecoveryError(
        "RECOVERY_TARGET_INVALID",
        `extension index target was not supplied: ${target.index}`,
      );
    }
    return selected;
  }
  if (target.kind === "doc_hash") {
    const targetExtension = extensions.find(
      (extension) => extension.docHashHex === target.docHashHex,
    );
    if (!targetExtension) {
      throw new RecoveryError(
        "RECOVERY_TARGET_INVALID",
        `extension doc_hash target was not supplied: ${target.docHashHex}`,
      );
    }
    return selectLatestSuppliedChain(
      extensions.filter((extension) => extension.header.index <= targetExtension.header.index),
    );
  }
  throw new RecoveryError("RECOVERY_TARGET_INVALID", "unknown extension recovery target");
}

async function documentHasVerifiedRootSignature(document, expectedSignPub, verifySignature) {
  try {
    await requireVerifiedAuthPayload(document, expectedSignPub, verifySignature);
    return true;
  } catch {
    return false;
  }
}
