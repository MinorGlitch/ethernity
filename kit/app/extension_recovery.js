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

import { bytesEqual } from "../lib/encoding.js";
import { EXTENSION_ENVELOPE_VERSION, ENVELOPE_VERSION } from "./constants.js";
import { extractFiles, readEnvelopeVersion } from "./envelope.js";
import { decodeExtensionEnvelope, reconstructLatestFiles } from "./extension_envelope.js";
import { deriveSigningPublicKey, verifyAuthSignature } from "./auth.js";

export async function recoverLatestFromPlaintextDocuments(
  documents,
  { verifySignature = verifyAuthSignature, extensionTarget = "latest" } = {},
) {
  if (!documents.length) {
    throw new Error("Collected ciphertext not available yet.");
  }
  const target = normalizeExtensionTarget(extensionTarget);
  const rootOnly = target === "root";
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
  const rawExtensions = decoded.filter((item) => item.kind === "extension");
  if (decodeErrors.length && documents.length > 1 && !rootOnly) {
    throw new Error("one or more supplied backup documents could not be decoded");
  }
  const suppliedRootAuthPayload = await verifySuppliedRootAuth(root, verifySignature);
  if (rootOnly || !rawExtensions.length) {
    return {
      files: root.extracted.files,
      manifest: root.extracted.manifest,
      selectedExtensionIndex: null,
      selectedExtensionDocHash: null,
      freshnessScope: null,
      decryptedEnvelope: root.document.plaintext,
      replayTarget: rootOnly ? "root" : "latest",
      suppliedDocumentCount: documents.length,
    };
  }

  const rootAuthoritySignPub = deriveRootSigningAuthority(root.extracted.manifest);
  if (!suppliedRootAuthPayload) {
    await requireVerifiedDocumentAuth(root.document, rootAuthoritySignPub, verifySignature);
  }
  const extensions = [];
  for (const item of rawExtensions) {
    const authPayload = await requireVerifiedDocumentAuth(
      item.document,
      rootAuthoritySignPub,
      verifySignature,
    );
    let extension;
    try {
      extension = await decodeExtensionEnvelope(item.document.plaintext);
    } catch (err) {
      throw new Error(`root-authority extension could not be decoded: ${String(err)}`);
    }
    if (!bytesEqual(extension.header.rootDocHash, root.document.docHash)) {
      throw new Error("extension root_doc_hash does not match root backup");
    }
    extensions.push({
      ...extension,
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
      throw new Error(`root-authority extension could not be decoded: ${failure.message}`);
    }
  }

  const selected = selectLatestSuppliedChain(extensions);
  const files = await reconstructLatestFiles(root.extracted.files, root.document.docHash, selected);
  const latest = selected.at(-1);
  return {
    files,
    manifest: root.extracted.manifest,
    selectedExtensionIndex: latest?.header.index ?? null,
    selectedExtensionDocHash: latest?.docHashHex ?? null,
    freshnessScope: selected.length ? "supplied_carriers_only" : null,
    decryptedEnvelope: root.document.plaintext,
    replayTarget: "latest",
    suppliedDocumentCount: documents.length,
  };
}

export async function recoverLatestFromEncryptedDocuments(
  documents,
  passphrase,
  decrypt,
  { verifySignature = verifyAuthSignature, extensionTarget = "latest" } = {},
) {
  const target = normalizeExtensionTarget(extensionTarget);
  const plaintextDocuments = [];
  const decryptErrors = [];
  for (const document of documents) {
    try {
      plaintextDocuments.push({
        ...document,
        plaintext: await decrypt(document.ciphertext, passphrase),
      });
    } catch (err) {
      decryptErrors.push({ document, message: String(err) });
    }
  }
  if (!plaintextDocuments.length) {
    throw new Error(decryptErrors[0]?.message ?? "Could not unlock backup. Check passphrase.");
  }
  if (decryptErrors.length && documents.length > 1 && target !== "root") {
    throw new Error("one or more supplied backup documents could not be decrypted");
  }
  const result = await recoverLatestFromPlaintextDocuments(plaintextDocuments, {
    verifySignature,
    extensionTarget: target,
  });
  return result;
}

function normalizeExtensionTarget(extensionTarget) {
  if (extensionTarget === "latest" || extensionTarget === "root") {
    return extensionTarget;
  }
  throw new Error("unknown extension recovery target");
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
