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

import { sha256 } from "@noble/hashes/sha2.js";
import { bytesEqual, bytesToHex } from "../../lib/bytes.js";
import { EXTENSION_ENVELOPE_VERSION, ENVELOPE_VERSION } from "../constants.js";
import { documentIdentityFromCiphertext } from "../documents/identity.js";
import { extractFiles, readEnvelopeVersion } from "../envelope.js";
import { decodeExtensionEnvelopeHeader, reconstructLatestFilesFromEnvelopes } from "./envelope.js";
import { deriveSigningPublicKey, verifyAuthSignature } from "../auth.js";
import { enforceRecoveryDocumentBudget } from "../frames_cipher.js";

export async function recoverLatestFromPlaintextDocuments(
  documents,
  {
    verifySignature = verifyAuthSignature,
    extensionTarget = "latest",
    recoveryAnchor = null,
    freshnessUnknownAcknowledged = false,
  } = {},
) {
  if (!documents.length) {
    throw new Error("Collected ciphertext not available yet.");
  }
  enforceRecoveryDocumentBudget(documents, { byteField: "plaintext", byteLabel: "plaintext" });
  const target = applyRecoveryAnchor(normalizeExtensionTarget(extensionTarget), recoveryAnchor);
  const freshnessDecision = requireFreshnessDecision(
    target,
    recoveryAnchor,
    freshnessUnknownAcknowledged,
  );
  const rootOnly = target.kind === "root";
  const decoded = [];
  const decodeErrors = [];
  for (const document of documents) {
    try {
      const version = readEnvelopeVersion(document.plaintext);
      if (version === ENVELOPE_VERSION) {
        decoded.push({
          kind: "root",
          document,
          extracted: await extractFiles(document.plaintext),
        });
      } else if (version === EXTENSION_ENVELOPE_VERSION) {
        decoded.push({
          kind: "extension",
          document,
        });
      } else {
        decodeErrors.push({ document, message: `unsupported envelope version: ${version}` });
      }
    } catch (err) {
      decodeErrors.push({ document, message: String(err) });
    }
  }

  const roots = decoded.filter((item) => item.kind === "root");
  if (roots.length !== 1) {
    if (!roots.length && decodeErrors.length) {
      throw new Error(
        `content import did not contain a decryptable root backup: ${decodeErrors[0].message}`,
      );
    }
    throw new Error(`content import must contain exactly one root backup (${roots.length} found)`);
  }
  const root = roots[0];
  validateAnchoredRootDocument(recoveryAnchor, root.document);
  const rawExtensions = decoded.filter((item) => item.kind === "extension");
  for (const failure of decodeErrors) {
    throwIfSelectedDocHashFailure(target, failure.document, "decoded", failure.message);
  }
  if (decodeErrors.length && documents.length > 1 && target.kind === "latest") {
    throw new Error("one or more supplied backup documents could not be decoded");
  }
  const suppliedRootAuthPayload = await verifySuppliedRootAuth(root, verifySignature);
  if (recoveryAnchor) {
    const anchoredSignPub =
      suppliedRootAuthPayload?.signPub ?? deriveRootSigningAuthority(root.extracted.manifest);
    validateAnchoredSigningAuthority(recoveryAnchor, anchoredSignPub);
  }
  if (rootOnly) {
    ensureRootOnlyMatchesAnchor(target, recoveryAnchor, root.document.docHashHex);
    ensureExpectedHeadSatisfied(target, root.document.docHashHex);
    return {
      files: root.extracted.files,
      manifest: root.extracted.manifest,
      selectedExtensionIndex: null,
      selectedExtensionDocHash: null,
      freshnessScope: null,
      freshnessDecision,
      trustBasis: recoveryTrustBasis(recoveryAnchor),
      decryptedEnvelope: root.document.plaintext,
      replayTarget: rootOnly ? "root" : "latest",
      suppliedDocumentCount: documents.length,
    };
  }
  if (!rawExtensions.length) {
    if (target.kind !== "latest") {
      throw new Error("requested extension target was not supplied");
    }
    ensureExpectedHeadSatisfied(target, root.document.docHashHex);
    return {
      files: root.extracted.files,
      manifest: root.extracted.manifest,
      selectedExtensionIndex: null,
      selectedExtensionDocHash: null,
      freshnessScope: null,
      freshnessDecision,
      trustBasis: recoveryTrustBasis(recoveryAnchor),
      decryptedEnvelope: root.document.plaintext,
      replayTarget: "latest",
      suppliedDocumentCount: documents.length,
    };
  }

  const rootAuthoritySignPub = deriveRootSigningAuthority(root.extracted.manifest);
  if (!suppliedRootAuthPayload) {
    await requireVerifiedDocumentAuth(root.document, rootAuthoritySignPub, verifySignature);
  }
  const authenticatedExtensions = [];
  const extensionFailures = [];
  for (const item of rawExtensions) {
    let authPayload;
    try {
      authPayload = await requireVerifiedDocumentAuth(
        item.document,
        rootAuthoritySignPub,
        verifySignature,
      );
    } catch (err) {
      throwIfSelectedDocHashFailure(target, item.document, "trusted", String(err));
      extensionFailures.push({
        authenticated: false,
        message: String(err),
      });
      continue;
    }
    let header;
    try {
      header = decodeExtensionEnvelopeHeader(item.document.plaintext);
    } catch (err) {
      throwIfSelectedDocHashFailure(
        target,
        item.document,
        "decoded",
        `root-authority extension could not be decoded: ${String(err)}`,
      );
      extensionFailures.push({
        authenticated: true,
        message: `root-authority extension could not be decoded: ${String(err)}`,
      });
      continue;
    }
    if (!bytesEqual(header.rootDocHash, root.document.docHash)) {
      throwIfSelectedDocHashFailure(
        target,
        item.document,
        "trusted",
        "extension root_doc_hash does not match root backup",
      );
      extensionFailures.push({
        authenticated: true,
        message: "extension root_doc_hash does not match root backup",
      });
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
      await documentHasVerifiedRootAuthority(
        failure.document,
        rootAuthoritySignPub,
        verifySignature,
      )
    ) {
      extensionFailures.push({
        authenticated: true,
        message: `root-authority extension could not be decoded: ${failure.message}`,
      });
    }
  }
  if (target.kind === "latest" && extensionFailures.length) {
    throw new Error(extensionFailures[0].message);
  }

  const selectedHeaders = selectSuppliedChainForTarget(authenticatedExtensions, target);
  let files;
  try {
    files = await reconstructLatestFilesFromEnvelopes(
      root.extracted.files,
      root.document.docHash,
      selectedHeaders.map((item) => ({
        header: item.header,
        plaintext: item.document.plaintext,
        docHash: item.document.docHash,
      })),
    );
  } catch (err) {
    const selectedDocument = selectedHeaders.at(-1)?.document;
    if (selectedDocument) {
      throwIfSelectedDocHashFailure(
        target,
        selectedDocument,
        "decoded",
        `root-authority extension could not be decoded: ${String(err)}`,
      );
    }
    throw new Error(`root-authority extension could not be decoded: ${String(err)}`);
  }
  const latest = selectedHeaders.at(-1);
  ensureExpectedHeadSatisfied(target, latest?.docHashHex ?? root.document.docHashHex);
  return {
    files,
    manifest: selectedHeaders.length
      ? syntheticManifestFromFiles(root.extracted.manifest, files)
      : root.extracted.manifest,
    selectedExtensionIndex: latest?.header.index ?? null,
    selectedExtensionDocHash: latest?.docHashHex ?? null,
    freshnessScope: selectedHeaders.length ? "supplied_carriers_only" : null,
    freshnessDecision,
    trustBasis: recoveryTrustBasis(recoveryAnchor),
    decryptedEnvelope: root.document.plaintext,
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
    allowResourceIntensiveScrypt = false,
    recoveryAnchor = null,
    freshnessUnknownAcknowledged = false,
  } = {},
) {
  const target = applyRecoveryAnchor(normalizeExtensionTarget(extensionTarget), recoveryAnchor);
  requireFreshnessDecision(target, recoveryAnchor, freshnessUnknownAcknowledged);
  enforceRecoveryDocumentBudget(documents);
  const authPreflight = await preflightEncryptedDocumentAuth(documents, verifySignature);
  const decryptPreflight =
    typeof decrypt.preflightBatch === "function"
      ? decrypt.preflightBatch(
          documents.map((document) => document.ciphertext),
          {
            allowResourceIntensive: allowResourceIntensiveScrypt,
          },
        )
      : null;
  if (target.kind === "latest") {
    const firstAuthError = authPreflight.errors.find(Boolean);
    if (firstAuthError) {
      throw new Error(firstAuthError);
    }
    if (authPreflight.hasMultipleSigningAuthorities) {
      throw new Error("supplied AUTH payloads advertise multiple signing authorities");
    }
    const firstPreflightError = decryptPreflight?.errors?.find(Boolean);
    if (firstPreflightError) {
      throw new Error(firstPreflightError);
    }
  }
  const plaintextDocuments = [];
  const decryptErrors = [];
  for (const [documentIndex, document] of authPreflight.documents.entries()) {
    if (signal?.aborted) {
      throw new Error("recovery decryption was cancelled");
    }
    const identifiedDocument = document;
    try {
      const authError = authPreflight.errors[documentIndex];
      if (authError) {
        throw new Error(authError);
      }
      const preflightError = decryptPreflight?.errors?.[documentIndex];
      if (preflightError) {
        throw new Error(preflightError);
      }
      const plaintext = await decrypt(document.ciphertext, passphrase, { signal });
      plaintextDocuments.push({
        ...identifiedDocument,
        plaintext,
      });
    } catch (err) {
      decryptErrors.push({ document: identifiedDocument, message: String(err) });
    }
  }
  for (const failure of decryptErrors) {
    throwIfSelectedDocHashFailure(target, failure.document, "decrypted", failure.message);
  }
  if (!plaintextDocuments.length) {
    throw new Error(decryptErrors[0]?.message ?? "Could not unlock backup. Check passphrase.");
  }
  if (decryptErrors.length && documents.length > 1 && target.kind === "latest") {
    throw new Error("one or more supplied backup documents could not be decrypted");
  }
  const result = await recoverLatestFromPlaintextDocuments(plaintextDocuments, {
    verifySignature,
    extensionTarget: target,
    recoveryAnchor,
    freshnessUnknownAcknowledged,
  });
  return result;
}

function validateAnchoredRootDocument(anchor, document) {
  if (!anchor) return;
  if (document.docHashHex !== anchor.rootDocumentHashHex) {
    throw new Error("root backup does not match the recovery kit anchor");
  }
}

function validateAnchoredSigningAuthority(anchor, signPub) {
  if (!anchor) return;
  const fingerprint = bytesToHex(sha256(signPub));
  if (fingerprint !== anchor.rootSigningPublicKeyFingerprintHex) {
    throw new Error("root signing authority does not match the recovery kit anchor");
  }
}

async function preflightEncryptedDocumentAuth(documents, verifySignature) {
  const identifiedDocuments = [];
  const errors = [];
  const signingAuthorities = new Set();
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
      error = err instanceof Error ? err.message : String(err);
    }
    if (identifiedDocument.authPayload) {
      try {
        const payload = await requireVerifiedDocumentAuth(
          identifiedDocument,
          null,
          verifySignature,
        );
        signingAuthorities.add(bytesToHex(payload.signPub));
      } catch (err) {
        error ??= err instanceof Error ? err.message : String(err);
      }
    }
    identifiedDocuments.push(identifiedDocument);
    errors.push(error);
  }
  return {
    documents: identifiedDocuments,
    errors,
    hasMultipleSigningAuthorities: signingAuthorities.size > 1,
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
    throw new Error(`supplied ${label} must be bytes`);
  }
  if (!bytesEqual(value, expected)) {
    throw new Error(`supplied ${label} does not match derived ciphertext identity`);
  }
}

function assertSuppliedHexMatch(value, expected, label) {
  if (value === undefined || value === null || value === "") {
    return;
  }
  if (String(value).toLowerCase() !== expected) {
    throw new Error(`supplied ${label} does not match derived ciphertext identity`);
  }
}

function syntheticManifestFromFiles(rootManifest, files) {
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

function normalizeExtensionTarget(extensionTarget) {
  if (!extensionTarget || extensionTarget === "latest") {
    return { kind: "latest" };
  }
  if (typeof extensionTarget === "string") {
    const latestMatch = extensionTarget.trim().match(/^latest:([0-9a-fA-F]{64})$/);
    if (latestMatch) {
      return {
        kind: "latest",
        expectedHeadDocHashHex: latestMatch[1].toLowerCase(),
      };
    }
  }
  if (extensionTarget === "root") {
    return { kind: "root" };
  }
  if (typeof extensionTarget === "object" && extensionTarget.kind === "latest") {
    return withExpectedHeadDocHash({ kind: "latest" }, extensionTarget.expectedHeadDocHashHex);
  }
  if (typeof extensionTarget === "object" && extensionTarget.kind === "root") {
    return withExpectedHeadDocHash({ kind: "root" }, extensionTarget.expectedHeadDocHashHex);
  }
  if (typeof extensionTarget === "object" && extensionTarget.kind === "index") {
    if (!Number.isInteger(extensionTarget.index) || extensionTarget.index < 0) {
      throw new Error("extension index target must be a non-negative integer");
    }
    if (extensionTarget.index === 0) {
      return withExpectedHeadDocHash({ kind: "root" }, extensionTarget.expectedHeadDocHashHex);
    }
    return withExpectedHeadDocHash(
      { kind: "index", index: extensionTarget.index },
      extensionTarget.expectedHeadDocHashHex,
    );
  }
  if (typeof extensionTarget === "object" && extensionTarget.kind === "doc_hash") {
    const docHashHex = String(extensionTarget.docHashHex ?? "").toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(docHashHex)) {
      throw new Error("extension doc_hash target must be 64 lowercase hex characters");
    }
    return withExpectedHeadDocHash(
      { kind: "doc_hash", docHashHex },
      extensionTarget.expectedHeadDocHashHex,
    );
  }
  throw new Error("unknown extension recovery target");
}

function applyRecoveryAnchor(target, anchor) {
  if (!anchor) return target;
  if (target.kind !== "latest" && target.kind !== "root") {
    throw new Error("chain-bound recovery kits recover only their pinned head or the pinned root");
  }
  if (
    target.expectedHeadDocHashHex &&
    target.expectedHeadDocHashHex !== anchor.expectedLatestHeadHashHex
  ) {
    throw new Error("recovery target conflicts with the chain-bound kit head anchor");
  }
  return { ...target, expectedHeadDocHashHex: anchor.expectedLatestHeadHashHex };
}

function requireFreshnessDecision(target, anchor, freshnessUnknownAcknowledged) {
  if (anchor) {
    if (target.kind === "root" && anchor.expectedLatestHeadHashHex !== anchor.rootDocumentHashHex) {
      throw new Error("root-only recovery refused because the trusted kit pins a non-root head");
    }
    return "trusted_kit";
  }
  if (target.expectedHeadDocHashHex || target.kind === "doc_hash") {
    return "manual_expected_head";
  }
  if (target.kind === "latest" && freshnessUnknownAcknowledged === true) {
    return "supplied_pages_freshness_unknown";
  }
  if (target.kind === "latest") {
    throw new Error(
      "latest recovery requires an expected head hash or explicit freshness-unknown acknowledgement",
    );
  }
  throw new Error("selected recovery target requires an expected head hash");
}

function ensureRootOnlyMatchesAnchor(target, anchor, rootDocHashHex) {
  if (!anchor || target.kind !== "root") return;
  if (anchor.expectedLatestHeadHashHex !== rootDocHashHex) {
    throw new Error("root-only recovery refused because the trusted kit pins a non-root head");
  }
}

function recoveryTrustBasis(anchor) {
  return anchor ? "matched_trusted_kit" : "internally_consistent";
}

function withExpectedHeadDocHash(target, value) {
  if (value === undefined || value === null || value === "") {
    return target;
  }
  const expectedHeadDocHashHex = String(value).toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(expectedHeadDocHashHex)) {
    throw new Error("expected extension head doc_hash must be 64 lowercase hex characters");
  }
  return { ...target, expectedHeadDocHashHex };
}

function ensureExpectedHeadSatisfied(target, actualHeadDocHashHex) {
  if (!target.expectedHeadDocHashHex) {
    return;
  }
  if (actualHeadDocHashHex !== target.expectedHeadDocHashHex) {
    throw new Error(
      `validated extension head doc_hash does not match expected head ${target.expectedHeadDocHashHex}; latest supplied head is ${actualHeadDocHashHex}`,
    );
  }
}

function throwIfSelectedDocHashFailure(target, document, verb, message) {
  if (target.kind !== "doc_hash" || document.docHashHex !== target.docHashHex) {
    return;
  }
  throw new Error(
    `selected extension doc_hash ${target.docHashHex} could not be ${verb}: ${message}`,
  );
}

function deriveRootSigningAuthority(manifest) {
  if (!manifest?.signingSeed) {
    throw new Error("extension replay requires an unsealed root signing authority");
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
  return requireVerifiedDocumentAuth(root.document, expectedSignPub, verifySignature);
}

function selectLatestSuppliedChain(extensions) {
  const byIndex = new Map();
  for (const extension of extensions) {
    const index = extension.header.index;
    const existing = byIndex.get(index);
    if (existing && existing.docHashHex !== extension.docHashHex) {
      throw new Error(
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
      throw new Error(`extension index target was not supplied: ${target.index}`);
    }
    return selected;
  }
  if (target.kind === "doc_hash") {
    const targetExtension = extensions.find(
      (extension) => extension.docHashHex === target.docHashHex,
    );
    if (!targetExtension) {
      throw new Error(`extension doc_hash target was not supplied: ${target.docHashHex}`);
    }
    return selectLatestSuppliedChain(
      extensions.filter((extension) => extension.header.index <= targetExtension.header.index),
    );
  }
  throw new Error("unknown extension recovery target");
}

async function documentHasVerifiedRootAuthority(document, expectedSignPub, verifySignature) {
  try {
    await requireVerifiedDocumentAuth(document, expectedSignPub, verifySignature);
    return true;
  } catch {
    return false;
  }
}

async function requireVerifiedDocumentAuth(document, expectedSignPub, verifySignature) {
  return requireVerifiedAuthPayloadWithVerifier(document, expectedSignPub, verifySignature);
}

async function requireVerifiedAuthPayloadWithVerifier(document, expectedSignPub, verifySignature) {
  const payload = document.authPayload;
  if (!payload) {
    throw new Error("missing AUTH payload");
  }
  if (!bytesEqual(payload.docHash, document.docHash)) {
    throw new Error("AUTH doc_hash does not match ciphertext");
  }
  if (expectedSignPub && !bytesEqual(payload.signPub, expectedSignPub)) {
    throw new Error("AUTH signing key does not match root authority");
  }
  const verified = await verifySignature(document.docHash, payload.signPub, payload.signature);
  if (verified === null) {
    throw new Error("this browser cannot verify extension signatures");
  }
  if (!verified) {
    throw new Error("AUTH signature is invalid");
  }
  return payload;
}
