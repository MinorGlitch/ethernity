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

import { ed25519 } from "@noble/curves/ed25519.js";

import { bytesEqual, bytesToHex, concatBytes } from "../lib/encoding.js";
import { encodeCbor } from "../lib/cbor.js";
import { AUTH_DOMAIN, AUTH_VERSION, textEncoder } from "./constants.js";
import { primaryDocumentRecord, syncLegacyDocumentFields } from "./document_store.js";
import { ensureDocumentCiphertextAndHash } from "./frames_cipher.js";

let authStatusPending = false;

export function deriveSigningPublicKey(signingSeed) {
  return ed25519.getPublicKey(signingSeed);
}

export async function verifyAuthSignature(docHash, signPub, signature) {
  const message = authSignatureMessage(docHash, signPub);
  const cryptoApi = globalThis.crypto;
  if (!cryptoApi?.subtle?.importKey) {
    return verifyAuthSignaturePortable(signature, message, signPub);
  }
  try {
    const key = await cryptoApi.subtle.importKey("raw", signPub, { name: "Ed25519" }, false, [
      "verify",
    ]);
    const ok = await cryptoApi.subtle.verify("Ed25519", key, signature, message);
    return ok;
  } catch (_err) {
    return verifyAuthSignaturePortable(signature, message, signPub);
  }
}

function authSignatureMessage(docHash, signPub) {
  const signedPayload = { version: AUTH_VERSION, hash: docHash, pub: signPub };
  const signedBytes = encodeCbor(signedPayload);
  return concatBytes(textEncoder.encode(AUTH_DOMAIN), signedBytes);
}

function verifyAuthSignaturePortable(signature, message, signPub) {
  try {
    return ed25519.verify(signature, message, signPub, { zip215: false });
  } catch (_err) {
    return null;
  }
}

export async function updateAuthStatus(state) {
  if (authStatusPending) {
    return;
  }
  authStatusPending = true;
  try {
    const record = primaryDocumentRecord(state) ?? state;
    if (!record.authPayload && record !== state) {
      syncLegacyDocumentFields(state);
      return;
    }
    await updateDocumentAuthStatus(record);
    if (record !== state) {
      syncLegacyDocumentFields(state);
    }
  } finally {
    authStatusPending = false;
  }
}

export async function updateDocumentAuthStatus(record) {
  if (!record.authPayload) {
    record.authStatus = "missing";
    return;
  }
  if (record.authConflicts > 0) {
    record.authStatus = "conflict";
    return;
  }
  if (record.authErrors > 0 && record.authStatus === "invalid payload") {
    return;
  }
  let docHash;
  try {
    docHash = ensureDocumentCiphertextAndHash(record);
  } catch {
    record.authStatus = "ciphertext error";
    return;
  }
  if (!docHash) {
    record.authStatus = "waiting for main frames";
    return;
  }
  const docHashHex = bytesToHex(docHash);
  if (record.authDocHashHex && record.authDocHashHex !== docHashHex) {
    record.authStatus = "doc_hash mismatch";
    return;
  }
  const verified = await verifyAuthSignature(
    docHash,
    record.authPayload.signPub,
    record.authPayload.signature,
  );
  if (verified === true) {
    record.authStatus = "verified";
    return;
  }
  if (verified === false) {
    record.authStatus = "invalid signature";
    return;
  }
  record.authStatus = "doc_hash matches; signature not verified";
}

export async function requireVerifiedAuthPayload(document, expectedSignPub = null) {
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
  const verified = await verifyAuthSignature(document.docHash, payload.signPub, payload.signature);
  if (verified === null) {
    throw new Error("this browser cannot verify extension signatures");
  }
  if (!verified) {
    throw new Error("AUTH signature is invalid");
  }
  return payload;
}
