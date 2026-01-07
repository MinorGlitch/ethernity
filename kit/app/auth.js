import { concatBytes, bytesToHex } from "../lib/encoding.js";
import { AUTH_DOMAIN, textEncoder } from "./constants.js";
import { ensureCiphertextAndHash } from "./frames.js";

let authStatusPending = false;

async function verifyAuthSignature(docHash, signPub, signature) {
  if (!crypto || !crypto.subtle || !crypto.subtle.importKey) {
    return null;
  }
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      signPub,
      { name: "Ed25519" },
      false,
      ["verify"]
    );
    const message = concatBytes(textEncoder.encode(AUTH_DOMAIN), docHash);
    const ok = await crypto.subtle.verify("Ed25519", key, signature, message);
    return ok;
  } catch (err) {
    return null;
  }
}

export async function updateAuthStatus(state) {
  if (authStatusPending) {
    return;
  }
  authStatusPending = true;
  if (!state.authPayload) {
    state.authStatus = "missing";
    authStatusPending = false;
    return;
  }
  if (state.authConflicts > 0) {
    state.authStatus = "conflict";
    authStatusPending = false;
    return;
  }
  if (state.authErrors > 0 && state.authStatus === "invalid payload") {
    authStatusPending = false;
    return;
  }
  if (state.docIdHex && state.authDocIdHex && state.docIdHex !== state.authDocIdHex) {
    state.authStatus = "doc_id mismatch";
    authStatusPending = false;
    return;
  }
  const docHash = ensureCiphertextAndHash(state);
  if (!docHash) {
    state.authStatus = "waiting for main frames";
    authStatusPending = false;
    return;
  }
  const docHashHex = bytesToHex(docHash);
  if (state.authDocHashHex && state.authDocHashHex !== docHashHex) {
    state.authStatus = "doc_hash mismatch";
    authStatusPending = false;
    return;
  }
  const verified = await verifyAuthSignature(docHash, state.authPayload.signPub, state.authPayload.signature);
  if (verified === true) {
    state.authStatus = "verified";
    authStatusPending = false;
    return;
  }
  if (verified === false) {
    state.authStatus = "invalid signature";
    authStatusPending = false;
    return;
  }
  state.authStatus = "doc_hash matches; signature not verified";
  authStatusPending = false;
}
