import { primaryDocumentRecord } from "../app/documents/store.js";
import {
  createStore,
  createTestDocument,
  buildFrame,
  toUnpaddedBase64,
} from "./protocol_test_data.mjs";
import assert from "node:assert/strict";
import test from "node:test";

import {
  AUTH_DOMAIN,
  AUTH_VERSION,
  FRAME_TYPE_AUTH,
  FRAME_TYPE_KEY,
  FRAME_TYPE_MAIN,
  LEGACY_SHARD_VERSION,
  MAX_CIPHERTEXT_BYTES,
  SHARD_DOMAIN,
  SHARD_KEY_PASSPHRASE,
  textEncoder,
} from "../app/constants.js";
import {
  addPayloads,
  addScannedPayload,
  addScannedShardPayload,
  addShardPayloads,
  resetAll,
  updateField,
} from "../app/actions_collect.js";
import { updateAuthStatus } from "../app/auth.js";
import { createInitialState } from "../app/state/initial.js";
import { hexToBytes } from "../lib/bytes.js";
import { encodeCbor } from "../lib/cbor.js";
import { blake2b256 } from "../lib/blake2b.js";

const MAIN_QR_PAYLOAD_SINGLE_FRAME = "QVABRAAAAAAAAAAAAAEBYSBj2P8";
const FIXTURE_PASSPHRASE = "stable-v1-shamir-meaningful";
const FIXTURE_SHARES = {
  share1: "e7fdbe85696bbbe4b866e834b96163685ef63664d9ea8746f942799aef313b11",
  share2: "5a67deac6678005323ba45d1d1757dc1ca5bc36a016ebc24581b4735de627622",
};
const AUTH_SIGN_PUB = new Uint8Array(32).fill(0x42);
const WRONG_SHARD_SIGN_PUB = new Uint8Array(32).fill(0x24);

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

test("finishing a pre-reset collection cannot clear a newer collection's busy flag", async () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  delete globalThis.crypto;
  const gates = [deferred(), deferred()];
  const started = [deferred(), deferred()];
  let verification = 0;
  globalThis.crypto = {
    subtle: {
      async importKey() {
        return {};
      },
      async verify() {
        const index = verification++;
        started[index].resolve();
        await gates[index].promise;
        return true;
      },
    },
  };
  try {
    const store = createStore();
    const ciphertext = Uint8Array.of(8, 9);
    const hash = blake2b256(ciphertext);
    const docId = hash.slice(0, 8);
    const payload = [
      buildFrame({ frameType: FRAME_TYPE_MAIN, docId, data: ciphertext }),
      buildFrame({
        frameType: FRAME_TYPE_AUTH,
        docId,
        data: encodeCbor({
          version: AUTH_VERSION,
          hash,
          pub: AUTH_SIGN_PUB,
          sig: new Uint8Array(64),
        }),
      }),
    ]
      .map(toUnpaddedBase64)
      .join("\n");
    store.getState().payloadText = payload;
    const first = addPayloads(store.dispatch, store.getState);
    await started[0].promise;
    resetAll(store.dispatch);
    store.getState().payloadText = payload;
    const second = addPayloads(store.dispatch, store.getState);
    gates[0].resolve();
    await started[1].promise;
    await first;
    assert.equal(store.getState().isAddingFrames, true);
    gates[1].resolve();
    await second;
    assert.equal(store.getState().isAddingFrames, false);
    assert.equal(primaryDocumentRecord(store.getState()).authStatus, "verified");
  } finally {
    for (const gate of gates) gate.resolve();
    if (original) Object.defineProperty(globalThis, "crypto", original);
    else delete globalThis.crypto;
  }
});

function shardPayload({ shareIndex, shareHex, docHash }) {
  return {
    version: LEGACY_SHARD_VERSION,
    type: SHARD_KEY_PASSPHRASE,
    threshold: 2,
    share_count: 3,
    share_index: shareIndex,
    length: FIXTURE_PASSPHRASE.length,
    share: hexToBytes(shareHex),
    hash: docHash,
    pub: WRONG_SHARD_SIGN_PUB,
    sig: new Uint8Array(64),
  };
}

function startsWithBytes(bytes, prefix) {
  if (bytes.length < prefix.length) {
    return false;
  }
  return prefix.every((byte, index) => bytes[index] === byte);
}

test("updateAuthStatus clears pending guard after ciphertext errors", async () => {
  const state = createInitialState();
  const document = createTestDocument(state);
  document.authPayload = {
    signPub: new Uint8Array(32),
    signature: new Uint8Array(64),
    docHash: new Uint8Array(32),
  };
  document.total = 1;
  document.mainFrames.set(0, { data: new Uint8Array(MAX_CIPHERTEXT_BYTES + 1) });

  await updateAuthStatus(state);
  assert.equal(document.authStatus, "ciphertext error");

  document.mainFrames.set(0, { data: new Uint8Array([1, 2, 3]) });
  document.ciphertext = null;
  document.cipherDocHashHex = null;
  document.authDocHashHex = null;

  await updateAuthStatus(state);
  assert.notEqual(document.authStatus, "ciphertext error");
});

test("updateAuthStatus uses portable verification when WebCrypto is unavailable", async () => {
  const original = globalThis.crypto;
  const state = createInitialState();
  const document = createTestDocument(state);
  document.authPayload = {
    signPub: new Uint8Array(32),
    signature: new Uint8Array(64),
    docHash: new Uint8Array(32),
  };
  document.total = 1;
  document.mainFrames.set(0, { data: new Uint8Array([1, 2, 3]) });

  try {
    delete globalThis.crypto;
    await updateAuthStatus(state);
  } finally {
    if (original) {
      globalThis.crypto = original;
    }
  }

  assert.equal(document.authStatus, "invalid signature");
});

test("async main followups do not overwrite reset state", async () => {
  const store = createStore();
  const state = store.getState();
  const document = createTestDocument(state);
  state.payloadText = MAIN_QR_PAYLOAD_SINGLE_FRAME;
  document.authPayload = {
    signPub: new Uint8Array(32),
    signature: new Uint8Array(64),
    docHash: new Uint8Array(32),
  };
  document.authDocHashHex = null;

  const pending = addPayloads(store.dispatch.bind(store), store.getState.bind(store));
  resetAll(store.dispatch.bind(store));
  await pending;

  const finalState = store.getState();
  assert.equal(primaryDocumentRecord(finalState), null);
  assert.equal(finalState.frameStatus.lines[0], "State cleared.");
});

test("shard followups wait for pending AUTH before recovering a shard secret", async () => {
  const originalCrypto = globalThis.crypto;
  const authPrefix = textEncoder.encode(AUTH_DOMAIN);
  const shardPrefix = textEncoder.encode(SHARD_DOMAIN);
  let releaseAuthVerify;
  let resolveAuthVerifyStarted;
  const authVerifyGate = new Promise((resolve) => {
    releaseAuthVerify = resolve;
  });
  const authVerifyStarted = new Promise((resolve) => {
    resolveAuthVerifyStarted = resolve;
  });
  globalThis.crypto = {
    subtle: {
      async importKey() {
        return {};
      },
      async verify(_algorithm, _key, _signature, message) {
        const bytes = message instanceof Uint8Array ? message : new Uint8Array(message);
        if (startsWithBytes(bytes, authPrefix)) {
          resolveAuthVerifyStarted();
          await authVerifyGate;
          return true;
        }
        if (startsWithBytes(bytes, shardPrefix)) {
          return true;
        }
        return false;
      },
    },
  };

  try {
    const store = createStore();
    const ciphertext = Uint8Array.of(8, 7, 6);
    const docHash = blake2b256(ciphertext);
    const docId = docHash.slice(0, 8);
    await addScannedPayload(store.dispatch.bind(store), store.getState.bind(store), {
      bytes: buildFrame({ frameType: FRAME_TYPE_MAIN, docId, data: ciphertext }),
    });

    const authPending = addScannedPayload(store.dispatch.bind(store), store.getState.bind(store), {
      bytes: buildFrame({
        frameType: FRAME_TYPE_AUTH,
        docId,
        data: encodeCbor({
          version: AUTH_VERSION,
          hash: docHash,
          pub: AUTH_SIGN_PUB,
          sig: new Uint8Array(64),
        }),
      }),
    });
    await authVerifyStarted;

    const shardFrames = [
      [1, FIXTURE_SHARES.share1],
      [2, FIXTURE_SHARES.share2],
    ].map(([shareIndex, shareHex]) =>
      toUnpaddedBase64(
        buildFrame({
          frameType: FRAME_TYPE_KEY,
          docId,
          data: encodeCbor(shardPayload({ shareIndex, shareHex, docHash })),
        }),
      ),
    );
    store.getState().shardPayloadText = shardFrames.join("\n");
    const shardPending = addShardPayloads(store.dispatch.bind(store), store.getState.bind(store));

    releaseAuthVerify();
    await Promise.all([authPending, shardPending]);

    const finalState = store.getState();
    assert.equal(finalState.recoveredShardSecret, "");
    assert.equal(finalState.agePassphrase, "");
    assert.match(
      finalState.shardStatus.lines.join("\n"),
      /signing key does not match verified document AUTH/,
    );
  } finally {
    globalThis.crypto = originalCrypto;
  }
});

test("changing recovery target clears stale recovered output", () => {
  const store = createStore();
  const state = store.getState();
  state.extractedFiles = [{ path: "old.txt", data: new Uint8Array([1]) }];
  state.decryptedBackup = new Uint8Array([2]);
  state.extractStatus = { lines: ["1 file(s) ready."], type: "ok" };
  state.decryptStatus = { lines: ["Recovery complete."], type: "ok" };
  state.isDecrypting = true;
  state.decryptRequestId = 3;

  updateField(
    store.dispatch.bind(store),
    store.getState.bind(store),
    "extensionTargetText",
    "root",
  );

  const finalState = store.getState();
  assert.deepEqual(finalState.extractedFiles, []);
  assert.equal(finalState.decryptedBackup, null);
  assert.equal(finalState.extractedFiles.length > 0, false);
  assert.deepEqual(finalState.extractStatus.lines, []);
  assert.deepEqual(finalState.decryptStatus.lines, []);
  assert.equal(finalState.isDecrypting, false);
  assert.equal(finalState.decryptRequestId, 4);
});

test("changing expected head clears stale recovered output", () => {
  const store = createStore();
  const state = store.getState();
  state.extractedFiles = [{ path: "old.txt", data: new Uint8Array([1]) }];
  state.decryptedBackup = new Uint8Array([2]);
  state.extractStatus = { lines: ["1 file(s) ready."], type: "ok" };
  state.decryptStatus = { lines: ["Recovery complete."], type: "ok" };
  state.isDecrypting = true;
  state.decryptRequestId = 3;

  updateField(
    store.dispatch.bind(store),
    store.getState.bind(store),
    "expectedHeadDocHashText",
    "a".repeat(64),
  );

  const finalState = store.getState();
  assert.deepEqual(finalState.extractedFiles, []);
  assert.equal(finalState.decryptedBackup, null);
  assert.equal(finalState.extractedFiles.length > 0, false);
  assert.deepEqual(finalState.extractStatus.lines, []);
  assert.deepEqual(finalState.decryptStatus.lines, []);
  assert.equal(finalState.isDecrypting, false);
  assert.equal(finalState.decryptRequestId, 4);
});

test("accepted pasted main frames clear stale recovered output", async () => {
  const store = createStore();
  const state = store.getState();
  state.payloadText = MAIN_QR_PAYLOAD_SINGLE_FRAME;
  state.extractedFiles = [{ path: "old.txt", data: new Uint8Array([1]) }];
  state.extractStatus = { lines: ["1 file(s) ready."], type: "ok" };
  state.decryptStatus = { lines: ["Recovery complete."], type: "ok" };

  await addPayloads(store.dispatch.bind(store), store.getState.bind(store));

  const finalState = store.getState();
  assert.deepEqual(finalState.extractedFiles, []);
  assert.equal(finalState.extractedFiles.length > 0, false);
  assert.deepEqual(finalState.extractStatus.lines, []);
  assert.deepEqual(finalState.decryptStatus.lines, []);
});

test("scanned payload parse failures report an error status", async () => {
  const store = createStore();

  await addScannedPayload(store.dispatch.bind(store), store.getState.bind(store), {
    text: "not a valid payload",
  });

  const finalState = store.getState();
  assert.equal(finalState.errors, 1);
  assert.equal(finalState.frameStatus.type, "error");
  assert.equal(finalState.frameStatus.lines[0], "Scanned QR could not be decoded.");
});

for (const method of ["paste", "scan"]) {
  test(`unrecognized JSON from ${method} cannot change the expected version`, async () => {
    const store = createStore();
    const expected = "aa".repeat(32);
    const payload = JSON.stringify({ expected_latest_head_hash: "bb".repeat(32) });
    store.getState().expectedHeadDocHashText = expected;

    if (method === "paste") {
      store.getState().payloadText = payload;
      await addPayloads(store.dispatch.bind(store), store.getState.bind(store));
    } else {
      await addScannedPayload(store.dispatch.bind(store), store.getState.bind(store), {
        bytes: new TextEncoder().encode(payload),
      });
    }

    assert.equal(store.getState().expectedHeadDocHashText, expected);
    assert.equal(store.getState().frameStatus.type, "error");
    assert.ok(store.getState().errors > 0);
  });
}

test("scanned shard parse failures report an error status", async () => {
  const store = createStore();
  const state = store.getState();
  state.extractedFiles = [{ path: "old.txt", data: new Uint8Array([1]) }];

  await addScannedShardPayload(store.dispatch.bind(store), store.getState.bind(store), {
    text: "not a valid shard payload",
  });

  const finalState = store.getState();
  assert.equal(finalState.shardErrors, 1);
  assert.deepEqual(finalState.extractedFiles, []);
  assert.equal(finalState.extractedFiles.length > 0, false);
  assert.equal(finalState.shardStatus.type, "error");
  assert.equal(finalState.shardStatus.lines[0], "Scanned shard QR could not be decoded.");
});
