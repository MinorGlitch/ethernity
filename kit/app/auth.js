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

import { concatBytes, bytesToHex } from "../lib/encoding.js";
import { encodeCbor } from "../lib/cbor.js";
import { AUTH_DOMAIN, AUTH_VERSION, textEncoder } from "./constants.js";
import { ensureCiphertextAndHash } from "./frames_cipher.js";

let authStatusPending = false;

async function verifyAuthSignature(docHash, signPub, signature) {
  const cryptoApi = globalThis.crypto;
  if (!cryptoApi || !cryptoApi.subtle || !cryptoApi.subtle.importKey) {
    return null;
  }
  try {
    const key = await cryptoApi.subtle.importKey("raw", signPub, { name: "Ed25519" }, false, [
      "verify",
    ]);
    const signedPayload = { version: AUTH_VERSION, hash: docHash, pub: signPub };
    const signedBytes = encodeCbor(signedPayload);
    const message = concatBytes(textEncoder.encode(AUTH_DOMAIN), signedBytes);
    const ok = await cryptoApi.subtle.verify("Ed25519", key, signature, message);
    return ok;
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
    if (!state.authPayload) {
      state.authStatus = "missing";
      return;
    }
    if (state.authConflicts > 0) {
      state.authStatus = "conflict";
      return;
    }
    if (state.authErrors > 0 && state.authStatus === "invalid payload") {
      return;
    }
    if (state.docIdHex && state.authDocIdHex && state.docIdHex !== state.authDocIdHex) {
      state.authStatus = "doc_id mismatch";
      return;
    }
    let docHash;
    try {
      docHash = ensureCiphertextAndHash(state);
    } catch {
      state.authStatus = "ciphertext error";
      return;
    }
    if (!docHash) {
      state.authStatus = "waiting for main frames";
      return;
    }
    const docHashHex = bytesToHex(docHash);
    if (state.authDocHashHex && state.authDocHashHex !== docHashHex) {
      state.authStatus = "doc_hash mismatch";
      return;
    }
    const verified = await verifyAuthSignature(
      docHash,
      state.authPayload.signPub,
      state.authPayload.signature,
    );
    if (verified === true) {
      state.authStatus = "verified";
      return;
    }
    if (verified === false) {
      state.authStatus = "invalid signature";
      return;
    }
    state.authStatus = "doc_hash matches; signature not verified";
  } finally {
    authStatusPending = false;
  }
}
