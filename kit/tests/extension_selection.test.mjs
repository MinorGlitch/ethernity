import assert from "node:assert/strict";
import test from "node:test";
import { textEncoder } from "../app/constants.js";
import { recoverLatestFromPlaintextDocuments as recoverPlaintextCore } from "../app/extensions/recovery.js";
import { encodeCbor } from "../lib/cbor.js";
import {
  CHUNKING,
  ROOT_DOC_ID,
  EXT1_DOC_ID,
  EXT2_DOC_ID,
  OTHER_SIGN_PUB,
  buildRootPlaintext,
  buildExtensionPlaintext,
  buildExtensionDocumentBytes,
  documentFromPlaintext,
  recoverLatestFromPlaintextDocuments,
  verifiedSignature,
} from "./extension_test_data.mjs";

test("browser recovery replays the latest supplied authenticated extension chain", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root"), mtime: 111 },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x10),
    plaintext: rootPlaintext,
  });
  const ext1Plaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one"), mtime: 222 }],
  });
  const ext1 = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x20),
    plaintext: ext1Plaintext,
  });
  const ext2Plaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: ext1.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "b.txt", data: new TextEncoder().encode("two"), mtime: 333 }],
  });
  const ext2 = documentFromPlaintext({
    docId: EXT2_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x30),
    plaintext: ext2Plaintext,
  });

  const result = await recoverLatestFromPlaintextDocuments([ext2, root, ext1], {
    verifySignature: verifiedSignature,
  });

  assert.equal(result.selectedExtensionIndex, 2);
  assert.equal(result.freshnessScope, "supplied_carriers_only");
  assert.equal(result.manifest.inputOrigin, "directory");
  assert.deepEqual(result.manifest.inputRoots, ["reconstructed-state"]);
  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [
      ["a.txt", "one"],
      ["b.txt", "two"],
    ],
  );
  assert.deepEqual(
    result.manifest.entries.map((entry) => [entry.path, entry.mtime]),
    [
      ["a.txt", 222],
      ["b.txt", 333],
    ],
  );
});

test("browser recovery rejects silent latest without a freshness decision", async () => {
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x11),
    plaintext: buildRootPlaintext([{ path: "a.txt", data: new TextEncoder().encode("root") }]),
  });

  await assert.rejects(
    () => recoverPlaintextCore([root], { verifySignature: verifiedSignature }),
    /latest recovery requires an expected head hash or explicit freshness-unknown acknowledgement/u,
  );
});

test("trusted extension fingerprint binds the root signing key after complete replay", async () => {
  const root = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x83),
    plaintext: buildRootPlaintext([{ path: "a.txt", data: textEncoder.encode("root") }]),
  });
  const extension = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x84),
    plaintext: buildExtensionPlaintext({
      index: 1,
      parentDocHash: root.docHash,
      rootDocHash: root.docHash,
      files: [{ path: "a.txt", data: textEncoder.encode("updated") }],
    }),
  });
  for (const extensionTarget of [
    { kind: "latest", expectedHeadDocHashHex: extension.docHashHex },
    { kind: "doc_hash", docHashHex: extension.docHashHex },
  ]) {
    const result = await recoverPlaintextCore([extension, root], {
      verifySignature: verifiedSignature,
      extensionTarget,
    });
    assert.equal(result.trustBasis, "matched_expected_head");
    assert.equal(result.signingKeyVerified, true);
    assert.equal(result.selectedExtensionDocHash, extension.docHashHex);
    await assert.rejects(
      () =>
        recoverPlaintextCore([extension], {
          verifySignature: verifiedSignature,
          extensionTarget,
        }),
      /exactly one root backup/u,
    );
  }
});

test("sealed standalone fingerprint verifies backup identity without verifying its signing key", async () => {
  const root = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x85),
    plaintext: buildRootPlaintext([{ path: "a.txt", data: textEncoder.encode("sealed") }], {
      sealed: true,
    }),
  });
  const result = await recoverPlaintextCore([root], {
    verifySignature: verifiedSignature,
    extensionTarget: { kind: "latest", expectedHeadDocHashHex: root.docHashHex },
  });
  assert.equal(result.trustBasis, "matched_expected_head");
  assert.equal(result.signingKeyVerified, false);
});

test("browser recovery rejects stale latest chain when expected head differs", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x70),
    plaintext: rootPlaintext,
  });
  const ext1Plaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const ext1 = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x71),
    plaintext: ext1Plaintext,
  });
  const ext2Plaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: ext1.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("two") }],
  });
  const ext2 = documentFromPlaintext({
    docId: EXT2_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x72),
    plaintext: ext2Plaintext,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, ext1], {
        verifySignature: verifiedSignature,
        extensionTarget: {
          kind: "latest",
          expectedHeadDocHashHex: ext2.docHashHex,
        },
      }),
    /validated extension head doc_hash does not match expected head/,
  );
});

test("browser recovery can select a supplied extension by index", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x10),
    plaintext: rootPlaintext,
  });
  const ext1Plaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const ext1 = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x20),
    plaintext: ext1Plaintext,
  });
  const ext2Plaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: ext1.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("two") }],
  });
  const ext2 = documentFromPlaintext({
    docId: EXT2_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x30),
    plaintext: ext2Plaintext,
  });

  const result = await recoverLatestFromPlaintextDocuments([root, ext2, ext1], {
    verifySignature: verifiedSignature,
    extensionTarget: { kind: "index", index: 1 },
  });

  assert.equal(result.replayTarget, "extension");
  assert.equal(result.selectedExtensionIndex, 1);
  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "one"]],
  );
});

test("browser recovery can select a supplied extension by doc hash", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x11),
    plaintext: rootPlaintext,
  });
  const ext1Plaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const ext1 = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x21),
    plaintext: ext1Plaintext,
  });
  const ext2Plaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: ext1.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("two") }],
  });
  const ext2 = documentFromPlaintext({
    docId: EXT2_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x31),
    plaintext: ext2Plaintext,
  });

  const result = await recoverLatestFromPlaintextDocuments([ext2, root, ext1], {
    verifySignature: verifiedSignature,
    extensionTarget: { kind: "doc_hash", docHashHex: ext1.docHashHex },
  });

  assert.equal(result.replayTarget, "extension");
  assert.equal(result.selectedExtensionIndex, 1);
  assert.equal(result.selectedExtensionDocHash, ext1.docHashHex);
  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "one"]],
  );
});

test("browser recovery reports bad selected doc hash AUTH instead of not supplied", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x12),
    plaintext: rootPlaintext,
  });
  const ext1Plaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const ext1 = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x22),
    plaintext: ext1Plaintext,
    signPub: OTHER_SIGN_PUB,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, ext1], {
        verifySignature: verifiedSignature,
        extensionTarget: { kind: "doc_hash", docHashHex: ext1.docHashHex },
      }),
    /selected extension doc_hash .* could not be trusted: AUTH signing key does not match root signing key/,
  );
});

test("browser recovery ignores later duplicate indexes for an explicit index target", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x61),
    plaintext: rootPlaintext,
  });
  const ext1Plaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const ext1 = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x62),
    plaintext: ext1Plaintext,
  });
  const ext2Plaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: ext1.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("two") }],
  });
  const ext2 = documentFromPlaintext({
    docId: EXT2_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x63),
    plaintext: ext2Plaintext,
  });
  const conflictingExt2 = documentFromPlaintext({
    docId: Uint8Array.from([4, 4, 4, 4, 4, 4, 4, 4]),
    ciphertextSeed: Uint8Array.of(0x64),
    plaintext: ext2Plaintext,
  });

  const result = await recoverLatestFromPlaintextDocuments([root, ext2, ext1, conflictingExt2], {
    verifySignature: verifiedSignature,
    extensionTarget: { kind: "index", index: 1 },
  });

  assert.equal(result.selectedExtensionIndex, 1);
  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "one"]],
  );
});

test("browser recovery ignores later duplicate indexes for an explicit doc hash target", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x65),
    plaintext: rootPlaintext,
  });
  const ext1Plaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const ext1 = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x66),
    plaintext: ext1Plaintext,
  });
  const ext2Plaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: ext1.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("two") }],
  });
  const ext2 = documentFromPlaintext({
    docId: EXT2_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x67),
    plaintext: ext2Plaintext,
  });
  const conflictingExt2 = documentFromPlaintext({
    docId: Uint8Array.from([5, 5, 5, 5, 5, 5, 5, 5]),
    ciphertextSeed: Uint8Array.of(0x68),
    plaintext: ext2Plaintext,
  });

  const result = await recoverLatestFromPlaintextDocuments([conflictingExt2, root, ext1, ext2], {
    verifySignature: verifiedSignature,
    extensionTarget: { kind: "doc_hash", docHashHex: ext1.docHashHex },
  });

  assert.equal(result.selectedExtensionIndex, 1);
  assert.equal(result.selectedExtensionDocHash, ext1.docHashHex);
  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "one"]],
  );
});

test("browser recovery rejects duplicate authenticated extension indexes for latest target", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x69),
    plaintext: rootPlaintext,
  });
  const ext1Plaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const ext1 = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x6a),
    plaintext: ext1Plaintext,
  });
  const ext2Plaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: ext1.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("two") }],
  });
  const ext2 = documentFromPlaintext({
    docId: EXT2_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x6b),
    plaintext: ext2Plaintext,
  });
  const conflictingExt2 = documentFromPlaintext({
    docId: Uint8Array.from([6, 6, 6, 6, 6, 6, 6, 6]),
    ciphertextSeed: Uint8Array.of(0x6c),
    plaintext: ext2Plaintext,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, ext2, ext1, conflictingExt2], {
        verifySignature: verifiedSignature,
      }),
    /multiple authenticated extensions for index 2/,
  );
});

test("browser recovery ignores a damaged later document for an explicit index target", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x41),
    plaintext: rootPlaintext,
  });
  const ext1Plaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const ext1 = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x42),
    plaintext: ext1Plaintext,
  });
  const ext2Plaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: ext1.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("two") }],
  });
  const ext2 = documentFromPlaintext({
    docId: EXT2_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x43),
    plaintext: ext2Plaintext,
    signPub: OTHER_SIGN_PUB,
  });

  const result = await recoverLatestFromPlaintextDocuments([root, ext1, ext2], {
    verifySignature: verifiedSignature,
    extensionTarget: { kind: "index", index: 1 },
  });

  assert.equal(result.selectedExtensionIndex, 1);
  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "one"]],
  );
});

test("browser root-only recovery validates supplied root AUTH", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x1d),
    plaintext: rootPlaintext,
    signPub: OTHER_SIGN_PUB,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root], {
        verifySignature: verifiedSignature,
        extensionTarget: "root",
      }),
    /AUTH signing key does not match root signing key/,
  );
});

test("browser root-only recovery rejects supplied root AUTH doc hash mismatch", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x1e),
    plaintext: rootPlaintext,
  });
  root.authPayload = {
    ...root.authPayload,
    docHash: new Uint8Array(32).fill(0xaa),
  };

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root], {
        verifySignature: verifiedSignature,
        extensionTarget: "root",
      }),
    /AUTH doc_hash does not match ciphertext/,
  );
});

test("browser root-only recovery rejects supplied root AUTH invalid signature", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x1f),
    plaintext: rootPlaintext,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root], {
        verifySignature() {
          return false;
        },
        extensionTarget: "root",
      }),
    /AUTH signature is invalid/,
  );
});

test("browser recovery fails closed when a supplied document cannot decode", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x19),
    plaintext: rootPlaintext,
  });
  const malformedDocument = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x29),
    plaintext: buildExtensionDocumentBytes({
      headerBytes: encodeCbor(
        new Map([
          [2, 1],
          [4, root.docHash],
          [5, root.docHash],
          [7, 1_700_000_101],
          [10, [1, CHUNKING.targetSize, CHUNKING.minSize, CHUNKING.maxSize]],
          [13, "incremental"],
        ]),
      ),
      bodyBytes: Uint8Array.of(0xff),
    }),
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, malformedDocument], {
        verifySignature: verifiedSignature,
      }),
    /extension signed by the root key could not be decoded/,
  );
});

test("browser root-only recovery bypasses broken authenticated extension ancestry", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x1b),
    plaintext: rootPlaintext,
  });
  const extPlaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("two") }],
  });
  const extension = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x2b),
    plaintext: extPlaintext,
  });

  const result = await recoverLatestFromPlaintextDocuments([root, extension], {
    verifySignature: verifiedSignature,
    extensionTarget: "root",
  });

  assert.equal(result.replayTarget, "root");
  assert.equal(result.selectedExtensionIndex, null);
  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "root"]],
  );
});

test("browser recovery does not decode later extension bodies for explicit index targets", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x39),
    plaintext: rootPlaintext,
  });
  const ext1Plaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const ext1 = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x3a),
    plaintext: ext1Plaintext,
  });
  const ext2Header = encodeCbor(
    new Map([
      [2, 2],
      [4, ext1.docHash],
      [5, root.docHash],
      [7, 1_700_000_102],
      [10, [1, CHUNKING.targetSize, CHUNKING.minSize, CHUNKING.maxSize]],
      [13, "incremental"],
    ]),
  );
  const ext2 = documentFromPlaintext({
    docId: EXT2_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x3b),
    plaintext: buildExtensionDocumentBytes({
      headerBytes: ext2Header,
      bodyBytes: Uint8Array.of(0xff),
    }),
  });

  const result = await recoverLatestFromPlaintextDocuments([root, ext1, ext2], {
    verifySignature: verifiedSignature,
    extensionTarget: { kind: "index", index: 1 },
  });
  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "one"]],
  );

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, ext1, ext2], {
        verifySignature: verifiedSignature,
      }),
    /extension signed by the root key could not be decoded/,
  );
});
