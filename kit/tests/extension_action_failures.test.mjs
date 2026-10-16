import { documentCounts } from "../app/documents/store.js";
import { RecoveryError } from "../lib/errors.js";
import assert from "node:assert/strict";
import test from "node:test";
import { FRAME_TYPE_AUTH, FRAME_TYPE_MAIN } from "../app/constants.js";
import { resetAll } from "../app/actions_collect.js";
import { decryptCiphertext } from "../app/actions_recover.js";
import { addFrame } from "../app/frames_apply.js";
import { decodeFrame } from "../app/frames_protocol.js";
import { encodeCbor } from "../lib/cbor.js";
import { blake2b256 } from "../lib/blake2b.js";
import { bytesToHex } from "../lib/bytes.js";
import { buildFrame } from "./protocol_test_data.mjs";
import {
  ROOT_SIGN_PUB,
  buildRootPlaintext,
  buildExtensionPlaintext,
  createStore,
  addSingleFrameDocument,
  docIdForCiphertext,
  verifiedSignature,
} from "./extension_test_data.mjs";

test("browser decrypt action does not rewrite an exact mnemonic-shaped secret", async () => {
  const store = createStore();
  const state = store.getState();
  const words = [...Array(11).fill("abandon"), "about"];
  const exactPassphrase = words.join("  ");
  state.agePassphrase = exactPassphrase;
  const rootCiphertext = Uint8Array.of(0x5d);
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  const attemptedPassphrases = [];

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    async decrypt(_ciphertext, passphrase) {
      attemptedPassphrases.push(passphrase);
      assert.equal(passphrase, exactPassphrase);
      return rootPlaintext;
    },
    verifySignature: verifiedSignature,
  });

  assert.deepEqual(attemptedPassphrases, [exactPassphrase]);
  assert.equal(store.getState().extractedFiles.length > 0, true);
});

test("browser decrypt action does not apply stale results after reset", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x49);
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  let releaseDecrypt;
  let markDecryptStarted;
  const decryptStarted = new Promise((resolve) => {
    markDecryptStarted = resolve;
  });
  const decryptGate = new Promise((resolve) => {
    releaseDecrypt = resolve;
  });

  const decryptTask = decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    async decrypt() {
      markDecryptStarted();
      await decryptGate;
      return rootPlaintext;
    },
    verifySignature: verifiedSignature,
  });
  await decryptStarted;
  store.dispatch({ type: "RESET" });
  releaseDecrypt();
  await decryptTask;

  const finalState = store.getState();
  assert.equal(finalState.extractedFiles.length > 0, false);
  assert.deepEqual(finalState.extractedFiles, []);
  assert.deepEqual(finalState.frameStatus.lines, ["State cleared."]);
});

test("browser reset aborts active scrypt work", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0x4a) });
  let started;
  const decryptStarted = new Promise((resolve) => {
    started = resolve;
  });
  let observedSignal = null;

  const decryptTask = decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    decrypt(_ciphertext, _passphrase, { signal }) {
      observedSignal = signal;
      started();
      return new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new Error("cancelled")), { once: true });
      });
    },
    verifySignature: verifiedSignature,
  });
  await decryptStarted;
  resetAll(store.dispatch.bind(store));
  await decryptTask;

  assert.equal(observedSignal?.aborted, true);
  assert.equal(store.getState().extractedFiles.length > 0, false);
  assert.deepEqual(store.getState().frameStatus.lines, ["State cleared."]);
});

test("browser decrypt action preserves supplied-document decrypt failures", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x5d);
  const extensionCiphertext = Uint8Array.of(0x5e);
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  addSingleFrameDocument(state, { ciphertext: extensionCiphertext });

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    async decrypt(ciphertext) {
      if (bytesToHex(ciphertext) === bytesToHex(rootCiphertext)) return rootPlaintext;
      throw new Error("damaged age payload");
    },
    verifySignature: verifiedSignature,
  });

  const finalState = store.getState();
  assert.equal(finalState.extractedFiles.length > 0, false);
  assert.equal(finalState.decryptStatus.type, "error");
  assert.match(
    finalState.decryptStatus.lines[0],
    /one or more supplied backup documents could not be decrypted/,
  );
});

test("browser decrypt action rejects latest target with stale expected head doc hash", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x75);
  const ext1Ciphertext = Uint8Array.of(0x76);
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const rootDocHash = blake2b256(rootCiphertext);
  const ext1Plaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: rootDocHash,
    rootDocHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  state.extensionTargetText = "latest";
  state.expectedHeadDocHashText = bytesToHex(new Uint8Array(32).fill(0xdd));
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  addSingleFrameDocument(state, { ciphertext: ext1Ciphertext });

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    async decrypt(ciphertext) {
      if (bytesToHex(ciphertext) === bytesToHex(rootCiphertext)) return rootPlaintext;
      if (bytesToHex(ciphertext) === bytesToHex(ext1Ciphertext)) return ext1Plaintext;
      throw new Error("unexpected ciphertext");
    },
    verifySignature: verifiedSignature,
  });

  const finalState = store.getState();
  assert.equal(finalState.extractedFiles.length > 0, false);
  assert.equal(finalState.decryptStatus.type, "error");
  assert.match(
    finalState.decryptStatus.lines[0],
    /validated extension head doc_hash does not match expected head/,
  );
});

test("browser decrypt action rejects invalid extension target input before decrypting", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  state.extensionTargetText = "not-a-target";
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0x7d) });

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    async decrypt() {
      throw new Error("decrypt should not be called");
    },
    verifySignature: verifiedSignature,
  });

  const finalState = store.getState();
  assert.equal(finalState.extractedFiles.length > 0, false);
  assert.equal(finalState.decryptStatus.type, "error");
  assert.match(finalState.decryptStatus.lines[0], /extension target/);
});

test("browser decrypt action rejects conflicting AUTH payloads", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x18);
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  addFrame(
    state,
    decodeFrame(
      buildFrame({
        frameType: FRAME_TYPE_AUTH,
        docId: docIdForCiphertext(rootCiphertext),
        data: encodeCbor({
          version: 1,
          hash: blake2b256(rootCiphertext),
          pub: ROOT_SIGN_PUB,
          sig: new Uint8Array(64).fill(0x67),
        }),
      }),
    ),
  );

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    async decrypt() {
      throw new Error("decrypt should not be called");
    },
    verifySignature: verifiedSignature,
  });

  const finalState = store.getState();
  assert.equal(finalState.decryptStatus.type, "error");
  assert.equal(finalState.decryptStatus.lines[0], "conflicting AUTH frames detected");
});

test("browser decrypt action rejects malformed AUTH payloads", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x1a);
  const rootDocId = docIdForCiphertext(rootCiphertext);
  addFrame(
    state,
    decodeFrame(buildFrame({ frameType: FRAME_TYPE_MAIN, docId: rootDocId, data: rootCiphertext })),
  );
  addFrame(
    state,
    decodeFrame(
      buildFrame({
        frameType: FRAME_TYPE_AUTH,
        docId: rootDocId,
        data: Uint8Array.of(0xff),
      }),
    ),
  );

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    async decrypt() {
      throw new Error("decrypt should not be called");
    },
    verifySignature: verifiedSignature,
  });

  const finalState = store.getState();
  assert.equal(documentCounts(finalState).authErrors, 1);
  assert.equal(finalState.decryptStatus.type, "error");
  assert.equal(finalState.decryptStatus.lines[0], "invalid AUTH frames detected");
});

test("mixed document failures retain their cause and cannot trigger passphrase retry", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = `  ${Array(12).fill("abandon").join("   ")}  `;
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0x5e) });
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0x5f) });
  let attempts = 0;
  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    async decrypt(ciphertext) {
      attempts += 1;
      throw ciphertext[0] === 0x5e
        ? new RecoveryError("PASSPHRASE_AUTH_FAILED", "unrelated message")
        : new RecoveryError("DOCUMENT_INTEGRITY_FAILED", "decrypt password invalid passphrase");
    },
    verifySignature: verifiedSignature,
  });
  assert.equal(attempts, 2);
  assert.equal(store.getState().decryptStatus.code, "DOCUMENT_INTEGRITY_FAILED");
  assert.equal(store.getState().decryptStatus.lines[0], "decrypt password invalid passphrase");
});
