import { RecoveryError } from "../lib/errors.js";
import assert from "node:assert/strict";
import test from "node:test";
import { FRAME_TYPE_AUTH, FRAME_TYPE_MAIN, textEncoder } from "../app/constants.js";
import { decryptCiphertext } from "../app/actions_recover.js";
import { addFrame } from "../app/frames_apply.js";
import { decodeFrame } from "../app/frames_protocol.js";
import { selectActionState } from "../app/state/selectors.js";
import { encodeCbor } from "../lib/cbor.js";
import { blake2b256 } from "../lib/blake2b.js";
import { bytesToHex } from "../lib/bytes.js";
import { buildFrame } from "./protocol_test_data.mjs";
import {
  EXT1_DOC_ID,
  EXT2_DOC_ID,
  ROOT_SIGN_PUB,
  SIGNATURE,
  buildRootPlaintext,
  buildExtensionPlaintext,
  createStore,
  addSingleFrameDocument,
  verifiedSignature,
} from "./extension_test_data.mjs";

test("browser decrypt action recovers latest supplied extension status", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x17);
  const extCiphertext = Uint8Array.of(0x27);
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const rootDocHash = blake2b256(rootCiphertext);
  const extPlaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: rootDocHash,
    rootDocHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("extension") }],
  });
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  addSingleFrameDocument(state, { ciphertext: extCiphertext });

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    async decrypt(ciphertext, passphrase) {
      assert.equal(passphrase, "pw");
      if (bytesToHex(ciphertext) === bytesToHex(rootCiphertext)) return rootPlaintext;
      if (bytesToHex(ciphertext) === bytesToHex(extCiphertext)) return extPlaintext;
      throw new Error("unexpected ciphertext");
    },
    verifySignature: verifiedSignature,
  });

  const finalState = store.getState();
  assert.equal(finalState.extractedFiles.length > 0, true);
  assert.equal(finalState.decryptStatus.type, "ok");
  assert.deepEqual(
    finalState.extractedFiles.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "extension"]],
  );
  assert.equal(
    finalState.decryptStatus.lines.includes("Replay target: latest supplied extension 1."),
    true,
  );
  assert.equal(
    finalState.decryptStatus.lines.includes(
      "Freshness: unknown beyond supplied pages; explicit acknowledgement used.",
    ),
    true,
  );
  assert.equal(
    finalState.decryptStatus.lines.includes(
      "Trust: Internally consistent; no independently trusted fingerprint matched.",
    ),
    true,
  );
});

test("browser decrypt action attempts a whitespace-only passphrase exactly", async () => {
  const store = createStore();
  const state = store.getState();
  const exactPassphrase = " \t ";
  state.agePassphrase = exactPassphrase;
  const rootCiphertext = Uint8Array.of(0x5a);
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  const attemptedPassphrases = [];

  assert.equal(selectActionState(state).canDecryptCiphertext, true);
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

for (const selectedUpdate of [false, true]) {
  test(`browser decrypt action retries mnemonic whitespace for ${selectedUpdate ? "selected update" : "latest"} after exact auth failure`, async () => {
    const store = createStore();
    const state = store.getState();
    const words = [...Array(11).fill("abandon"), "about"];
    const normalizedPassphrase = words.join(" ");
    const enteredPassphrase = `  ${words.slice(0, 6).join("   ")}\n${words.slice(6).join("\t")}  `;
    state.agePassphrase = enteredPassphrase;
    const rootCiphertext = Uint8Array.of(0x5b);
    const extensionCiphertext = Uint8Array.of(0x6b);
    const rootPlaintext = buildRootPlaintext([
      { path: "a.txt", data: new TextEncoder().encode("root") },
    ]);
    const rootDocHash = blake2b256(rootCiphertext);
    const extensionPlaintext = buildExtensionPlaintext({
      index: 1,
      parentDocHash: rootDocHash,
      rootDocHash,
      files: [{ path: "a.txt", data: new TextEncoder().encode("extension") }],
    });
    addSingleFrameDocument(state, { ciphertext: rootCiphertext });
    addSingleFrameDocument(state, { ciphertext: extensionCiphertext });
    if (selectedUpdate) state.extensionTargetText = bytesToHex(blake2b256(extensionCiphertext));
    const attemptedPassphrases = [];

    await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
      async decrypt(ciphertext, passphrase) {
        attemptedPassphrases.push(passphrase);
        if (passphrase === enteredPassphrase) {
          throw new RecoveryError("PASSPHRASE_AUTH_FAILED", "rejected exact key");
        }
        assert.equal(passphrase, normalizedPassphrase);
        if (bytesToHex(ciphertext) === bytesToHex(rootCiphertext)) return rootPlaintext;
        if (bytesToHex(ciphertext) === bytesToHex(extensionCiphertext)) {
          return extensionPlaintext;
        }
        throw new Error("unexpected ciphertext");
      },
      verifySignature: verifiedSignature,
    });

    assert.deepEqual(attemptedPassphrases, [
      enteredPassphrase,
      enteredPassphrase,
      normalizedPassphrase,
      normalizedPassphrase,
    ]);
    assert.equal(store.getState().extractedFiles.length > 0, true);
  });
}

test("browser decrypt action accepts an invalid-checksum wordlist phrase exactly", async () => {
  const store = createStore();
  const state = store.getState();
  const exactPassphrase = [...Array(11).fill("abandon"), "above"].join(" ");
  state.agePassphrase = exactPassphrase;
  const rootCiphertext = Uint8Array.of(0x5c);
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

test("browser decrypt action stops at the resource limit without starting a KDF", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0x48) });
  let decryptCalls = 0;
  const decrypt = async () => {
    decryptCalls += 1;
    throw new Error("must not start decryption");
  };
  decrypt.preflightBatch = () => {
    throw new Error("cumulative scrypt work exceeds the recovery work limit");
  };
  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    decrypt,
    verifySignature: verifiedSignature,
  });
  const finalState = store.getState();
  assert.equal(decryptCalls, 0);
  assert.equal(finalState.decryptStatus.type, "error");
  assert.match(finalState.decryptStatus.lines.join("\n"), /cumulative scrypt work/);
  assert.equal(finalState.extractedFiles.length > 0, false);
  assert.equal(finalState.isDecrypting, false);
});

test("browser decrypt action can recover root only from multiple supplied documents", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x1c);
  const extCiphertext = Uint8Array.of(0x2c);
  state.expectedHeadDocHashText = bytesToHex(blake2b256(rootCiphertext));
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const rootDocHash = blake2b256(rootCiphertext);
  const extPlaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: rootDocHash,
    rootDocHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("extension") }],
  });
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  addSingleFrameDocument(state, { ciphertext: extCiphertext });

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    extensionTarget: "root",
    async decrypt(ciphertext, passphrase) {
      assert.equal(passphrase, "pw");
      if (bytesToHex(ciphertext) === bytesToHex(rootCiphertext)) return rootPlaintext;
      if (bytesToHex(ciphertext) === bytesToHex(extCiphertext)) return extPlaintext;
      throw new Error("unexpected ciphertext");
    },
    verifySignature: verifiedSignature,
  });

  const finalState = store.getState();
  assert.equal(finalState.extractedFiles.length > 0, true);
  assert.equal(finalState.decryptStatus.type, "ok");
  assert.notEqual(finalState.decryptedBackup, null);
  assert.deepEqual(
    finalState.extractedFiles.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "root"]],
  );
  assert.equal(finalState.decryptStatus.lines.includes("Replay target: root backup only."), true);
  assert.equal(
    finalState.decryptStatus.lines.includes("Freshness scope: supplied carriers only."),
    false,
  );
});

test("browser decrypt action can recover root only with incomplete extension frames", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x1d);
  state.expectedHeadDocHashText = bytesToHex(blake2b256(rootCiphertext));
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  addFrame(
    state,
    decodeFrame(
      buildFrame({
        frameType: FRAME_TYPE_MAIN,
        docId: EXT1_DOC_ID,
        index: 0,
        total: 2,
        data: Uint8Array.of(0x2d),
      }),
    ),
  );

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    extensionTarget: "root",
    async decrypt(ciphertext) {
      if (bytesToHex(ciphertext) === bytesToHex(rootCiphertext)) return rootPlaintext;
      throw new Error("unexpected ciphertext");
    },
    verifySignature: verifiedSignature,
  });

  const finalState = store.getState();
  assert.equal(finalState.extractedFiles.length > 0, true);
  assert.equal(finalState.decryptStatus.type, "ok");
  assert.equal(finalState.decryptStatus.lines.includes("Replay target: root backup only."), true);
  assert.equal(
    finalState.decryptStatus.lines.includes("Ignored 1 incomplete non-root backup document(s)."),
    true,
  );
});

test("browser decrypt action reports ignored AUTH-only frames for root-only recovery", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x1f);
  state.expectedHeadDocHashText = bytesToHex(blake2b256(rootCiphertext));
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  addFrame(
    state,
    decodeFrame(
      buildFrame({
        frameType: FRAME_TYPE_AUTH,
        docId: EXT1_DOC_ID,
        data: encodeCbor({
          version: 1,
          hash: new Uint8Array(32).fill(0xaa),
          pub: ROOT_SIGN_PUB,
          sig: SIGNATURE,
        }),
      }),
    ),
  );

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    extensionTarget: "root",
    async decrypt(ciphertext) {
      if (bytesToHex(ciphertext) === bytesToHex(rootCiphertext)) return rootPlaintext;
      throw new Error("unexpected ciphertext");
    },
    verifySignature: verifiedSignature,
  });

  const finalState = store.getState();
  assert.equal(finalState.extractedFiles.length > 0, true);
  assert.equal(finalState.decryptStatus.type, "ok");
  assert.equal(
    finalState.decryptStatus.lines.includes("Ignored 1 AUTH-only non-root backup document(s)."),
    true,
  );
});

test("browser decrypt action can recover selected extension with incomplete later frames", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  state.extensionTargetText = "1";
  const rootCiphertext = Uint8Array.of(0x35);
  const ext1Ciphertext = Uint8Array.of(0x36);
  state.expectedHeadDocHashText = bytesToHex(blake2b256(ext1Ciphertext));
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
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  addSingleFrameDocument(state, { ciphertext: ext1Ciphertext });
  addFrame(
    state,
    decodeFrame(
      buildFrame({
        frameType: FRAME_TYPE_MAIN,
        docId: EXT2_DOC_ID,
        index: 0,
        total: 2,
        data: Uint8Array.of(0x37),
      }),
    ),
  );

  assert.equal(selectActionState(state).canDecryptCiphertext, true);

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    async decrypt(ciphertext) {
      if (bytesToHex(ciphertext) === bytesToHex(rootCiphertext)) return rootPlaintext;
      if (bytesToHex(ciphertext) === bytesToHex(ext1Ciphertext)) return ext1Plaintext;
      throw new Error("unexpected ciphertext");
    },
    verifySignature: verifiedSignature,
  });

  const finalState = store.getState();
  assert.equal(finalState.extractedFiles.length > 0, true);
  assert.equal(finalState.decryptStatus.type, "ok");
  assert.equal(
    finalState.decryptStatus.lines.includes("Replay target: supplied extension 1."),
    true,
  );
  assert.equal(
    finalState.decryptStatus.lines.includes("Ignored 1 incomplete non-root backup document(s)."),
    true,
  );
  assert.deepEqual(
    finalState.extractedFiles.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "one"]],
  );
});

test("browser decrypt action accepts extension target input by index", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  state.extensionTargetText = "1";
  const rootCiphertext = Uint8Array.of(0x3c);
  const ext1Ciphertext = Uint8Array.of(0x4c);
  state.expectedHeadDocHashText = bytesToHex(blake2b256(ext1Ciphertext));
  const ext2Ciphertext = Uint8Array.of(0x5c);
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
  const ext2Plaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: blake2b256(ext1Ciphertext),
    rootDocHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("two") }],
  });
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  addSingleFrameDocument(state, { ciphertext: ext1Ciphertext });
  addSingleFrameDocument(state, { ciphertext: ext2Ciphertext });

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    async decrypt(ciphertext) {
      if (bytesToHex(ciphertext) === bytesToHex(rootCiphertext)) return rootPlaintext;
      if (bytesToHex(ciphertext) === bytesToHex(ext1Ciphertext)) return ext1Plaintext;
      if (bytesToHex(ciphertext) === bytesToHex(ext2Ciphertext)) return ext2Plaintext;
      throw new Error("unexpected ciphertext");
    },
    verifySignature: verifiedSignature,
  });

  const finalState = store.getState();
  assert.equal(finalState.extractedFiles.length > 0, true);
  assert.equal(finalState.decryptStatus.type, "ok");
  assert.equal(
    finalState.decryptStatus.lines.includes("Replay target: supplied extension 1."),
    true,
  );
  assert.deepEqual(
    finalState.extractedFiles.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "one"]],
  );
});

test("browser decrypt action accepts extension target input by doc hash", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x6c);
  const ext1Ciphertext = Uint8Array.of(0x7c);
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
  const extDocHashHex = bytesToHex(blake2b256(ext1Ciphertext));
  state.extensionTargetText = extDocHashHex.toUpperCase();
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
  assert.equal(finalState.extractedFiles.length > 0, true);
  assert.equal(finalState.decryptStatus.type, "ok");
  assert.equal(
    finalState.decryptStatus.lines.includes(`Extension doc hash: ${extDocHashHex}.`),
    true,
  );
  assert.deepEqual(
    finalState.extractedFiles.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "one"]],
  );
});

test("browser decrypt action preserves selected doc hash decrypt errors", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x6d);
  const ext1Ciphertext = Uint8Array.of(0x7d);
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const extDocHashHex = bytesToHex(blake2b256(ext1Ciphertext));
  state.extensionTargetText = extDocHashHex;
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  addSingleFrameDocument(state, { ciphertext: ext1Ciphertext });

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
    /selected extension doc_hash .* could not be decrypted: damaged age payload/,
  );
});

test("browser decrypt action accepts dedicated expected head doc hash", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x73);
  const ext1Ciphertext = Uint8Array.of(0x74);
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
  const expectedHeadDocHashHex = bytesToHex(blake2b256(ext1Ciphertext));
  state.extensionTargetText = "latest";
  state.expectedHeadDocHashText = expectedHeadDocHashHex.toUpperCase();
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
  assert.equal(finalState.extractedFiles.length > 0, true);
  assert.equal(finalState.decryptStatus.type, "ok");
  assert.equal(
    finalState.decryptStatus.lines.includes("Replay target: latest supplied extension 1."),
    true,
  );
  assert.equal(
    finalState.decryptStatus.lines.includes(
      "Freshness: matched the manually entered expected head hash.",
    ),
    true,
  );
  assert.equal(
    finalState.decryptStatus.lines.includes(
      "Trust: Matched expected fingerprint; root identity, signing key, and selected head are bound.",
    ),
    true,
  );
  assert.deepEqual(
    finalState.extractedFiles.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "one"]],
  );
});

test("browser sealed recovery status states the manual fingerprint signing-key limit", async () => {
  const store = createStore();
  const ciphertext = Uint8Array.of(0x8a);
  const plaintext = buildRootPlaintext([{ path: "a.txt", data: textEncoder.encode("sealed") }], {
    sealed: true,
  });
  store.getState().agePassphrase = "pw";
  store.getState().expectedHeadDocHashText = bytesToHex(blake2b256(ciphertext));
  addSingleFrameDocument(store.getState(), { ciphertext });
  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    decrypt: async () => plaintext,
    verifySignature: verifiedSignature,
  });
  assert.equal(store.getState().extractedFiles.length > 0, true);
  assert.ok(
    store
      .getState()
      .decryptStatus.lines.includes(
        "Trust: Matched expected fingerprint; backup identity is bound. The sealed backup hash does not bind its signing key.",
      ),
  );
});

test("browser unlock action also extracts the root document", async () => {
  const store = createStore();
  const state = store.getState();
  const plaintext = buildRootPlaintext([{ path: "a.txt", data: new TextEncoder().encode("root") }]);
  state.agePassphrase = "pw";
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0x81) });
  await decryptCiphertext(store.dispatch, store.getState, {
    decrypt: async () => plaintext,
    verifySignature: verifiedSignature,
  });

  const finalState = store.getState();
  assert.equal(finalState.extractedFiles.length > 0, true);
  assert.deepEqual(finalState.extractStatus.lines, []);
  assert.deepEqual(
    finalState.extractedFiles.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "root"]],
  );
});

for (const [code, message] of [
  [null, "invalid passphrase: password decrypt"],
  ["DOCUMENT_INTEGRITY_FAILED", "invalid passphrase: password decrypt"],
  ["RECOVERY_RESOURCE_LIMIT", "invalid passphrase: password decrypt"],
  ["AUTH_SIGNATURE_INVALID", "invalid passphrase: password decrypt"],
  ["PASSPHRASE_AUTH_FAILED", "a different explanation"],
]) {
  test(`browser retry and hint depend on code ${code}, not wording`, async () => {
    const store = createStore();
    const state = store.getState();
    state.agePassphrase = `  ${Array(12).fill("abandon").join("   ")}  `;
    addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0x5d) });
    let attempts = 0;
    await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
      async decrypt() {
        attempts += 1;
        throw code ? new RecoveryError(code, message) : new Error(message);
      },
      verifySignature: verifiedSignature,
    });
    const status = store.getState().decryptStatus;
    assert.equal(attempts, code === "PASSPHRASE_AUTH_FAILED" ? 2 : 1);
    assert.equal(
      status.lines[0],
      code === "PASSPHRASE_AUTH_FAILED" ? "Incorrect passphrase." : message,
    );
    assert.equal(status.code, code ?? "DOCUMENT_INVALID");
    assert.equal(
      status.stage,
      code === "AUTH_SIGNATURE_INVALID"
        ? "authentication"
        : ["PASSPHRASE_AUTH_FAILED", "RECOVERY_RESOURCE_LIMIT"].includes(code)
          ? "unlock"
          : "source",
    );
  });
}
