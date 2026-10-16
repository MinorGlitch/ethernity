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

import { RecoveryError, asRecoveryError } from "../lib/errors.js";
import { bytesEqual, bytesToHex, concatBytes } from "../lib/bytes.js";
import { encodeCbor } from "../lib/cbor.js";
import { getSigningPublicKey, verifySignature } from "../lib/ed25519.js";
import { AUTH_DOMAIN, AUTH_VERSION, textEncoder } from "./constants.js";
import { ensureDocumentCiphertextAndHash } from "./frames_cipher.js";

let authStatusQueue = Promise.resolve();

export function deriveSigningPublicKey(signingSeed) {
  return getSigningPublicKey(signingSeed);
}

export async function verifyAuthSignature(docHash, signPub, signature) {
  return verifySignature(signature, authSignatureMessage(docHash, signPub), signPub);
}

function authSignatureMessage(docHash, signPub) {
  const signedPayload = { version: AUTH_VERSION, hash: docHash, pub: signPub };
  const signedBytes = encodeCbor(signedPayload);
  return concatBytes(textEncoder.encode(AUTH_DOMAIN), signedBytes);
}

export async function updateAuthStatus(state) {
  const run = authStatusQueue.then(
    () => updateAuthStatusNow(state),
    () => updateAuthStatusNow(state),
  );
  authStatusQueue = run.catch(() => {});
  await run;
}

async function updateAuthStatusNow(state) {
  for (const record of state.documents.values()) {
    await updateDocumentAuthStatus(record);
  }
}

export async function updateDocumentAuthStatus(record) {
  if (!record.authPayload) {
    if (record.authErrors > 0 && record.authStatus === "invalid payload") {
      return;
    }
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

export async function requireVerifiedAuthPayload(
  document,
  expectedSignPub = null,
  verifySignature = verifyAuthSignature,
) {
  const payload = document.authPayload;
  if (!payload) {
    throw new RecoveryError("AUTH_REQUIRED", "missing AUTH payload");
  }
  if (!bytesEqual(payload.docHash, document.docHash)) {
    throw new RecoveryError("AUTH_DOC_HASH_MISMATCH", "AUTH doc_hash does not match ciphertext");
  }
  if (expectedSignPub && !bytesEqual(payload.signPub, expectedSignPub)) {
    throw new RecoveryError(
      "ROOT_SIGNING_KEY_MISMATCH",
      "AUTH signing key does not match root signing key",
    );
  }
  let verified;
  try {
    verified = await verifySignature(document.docHash, payload.signPub, payload.signature);
  } catch (error) {
    throw asRecoveryError(error, "AUTH_VERIFICATION_FAILED");
  }
  if (verified === null) {
    throw new RecoveryError(
      "AUTH_VERIFICATION_FAILED",
      "this browser cannot verify extension signatures",
    );
  }
  if (!verified) {
    throw new RecoveryError("AUTH_SIGNATURE_INVALID", "AUTH signature is invalid");
  }
  return payload;
}
