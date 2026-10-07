import assert from "node:assert/strict";
import test from "node:test";
import { MAX_CIPHERTEXT_BYTES, MAX_RECOVERY_DOCUMENTS, textEncoder } from "../app/constants.js";
import { recoverLatestFromPlaintextDocuments as recoverPlaintextCore } from "../app/extensions/recovery.js";
import { signAuthPayload } from "./protocol_test_data.mjs";
import {
  CHUNKING,
  ROOT_DOC_ID,
  EXT1_DOC_ID,
  EXT2_DOC_ID,
  ROOT_SIGNING_SEED,
  ROOT_SIGN_PUB,
  OTHER_SIGN_PUB,
  buildRootPlaintext,
  buildExtensionPlaintext,
  buildExtensionDocumentBytes,
  documentFromPlaintext,
  recoverLatestFromPlaintextDocuments,
  verifiedSignature,
} from "./extension_test_data.mjs";

for (const mode of ["cumulative", "incremental"]) {
  test(`${mode} recovery enforces its document dependencies`, async () => {
    const root = documentFromPlaintext({
      docId: ROOT_DOC_ID,
      ciphertextSeed: Uint8Array.of(1),
      plaintext: buildRootPlaintext([{ path: "original", data: textEncoder.encode("root") }]),
    });
    const updates = [];
    const files = [];
    for (let index = 1; index <= 3; index += 1) {
      files.push({ path: `file${index}`, data: textEncoder.encode(`data${index}`) });
      const update = documentFromPlaintext({
        docId: new Uint8Array(8).fill(index + 1),
        ciphertextSeed: Uint8Array.of(index + 1),
        plaintext: buildExtensionPlaintext({
          index,
          parentDocHash: mode === "cumulative" ? root.docHash : (updates.at(-1) ?? root).docHash,
          rootDocHash: root.docHash,
          files: mode === "cumulative" ? files : [files.at(-1)],
          updateMode: mode,
        }),
      });
      updates.push(update);
    }
    for (const document of [root, ...updates]) {
      document.authPayload.signature = signAuthPayload(
        document.docHash,
        ROOT_SIGN_PUB,
        ROOT_SIGNING_SEED,
      );
    }
    const complete = await recoverLatestFromPlaintextDocuments([root, ...updates]);
    assert.equal(complete.selectedExtensionIndex, 3);
    assert.equal(complete.files.length, 4);
    if (mode === "cumulative") {
      for (const documents of [
        [root, updates[2]],
        [updates[2], root, updates[0]],
      ]) {
        const sparse = await recoverLatestFromPlaintextDocuments(documents);
        assert.deepEqual(sparse.files, complete.files);
      }
      const selected = await recoverLatestFromPlaintextDocuments([root, updates[0], updates[2]], {
        extensionTarget: { kind: "index", index: 1 },
      });
      assert.equal(selected.files.length, 2);
    } else {
      await assert.rejects(
        () => recoverLatestFromPlaintextDocuments([root, updates[2]]),
        /index sequence/,
      );
    }
  });
}

test("browser recovery labels explicitly acknowledged latest as internally consistent", async () => {
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x12),
    plaintext: buildRootPlaintext([{ path: "a.txt", data: new TextEncoder().encode("root") }]),
  });

  const result = await recoverPlaintextCore([root], {
    verifySignature: verifiedSignature,
    freshnessUnknownAcknowledged: true,
  });

  assert.equal(result.freshnessDecision, "supplied_pages_freshness_unknown");
  assert.equal(result.trustBasis, "internally_consistent");
});

test("extension replay rejects file and directory conflicts across versions in either direction", async () => {
  for (const [rootPath, addedPath] of [
    ["a", "a/b"],
    ["a/b", "a"],
    ["caf\u00e9", "cafe\u0301/notes"],
    ["cafe\u0301/notes", "caf\u00e9"],
  ]) {
    const root = documentFromPlaintext({
      ciphertextSeed: Uint8Array.of(0x86),
      plaintext: buildRootPlaintext([{ path: rootPath, data: Uint8Array.of(1) }]),
    });
    const extension = documentFromPlaintext({
      ciphertextSeed: Uint8Array.of(0x87),
      plaintext: buildExtensionPlaintext({
        index: 1,
        parentDocHash: root.docHash,
        rootDocHash: root.docHash,
        files: [{ path: addedPath, data: Uint8Array.of(2) }],
      }),
    });
    await assert.rejects(
      () =>
        recoverLatestFromPlaintextDocuments([root, extension], {
          verifySignature: verifiedSignature,
        }),
      /logical latest file paths contain a file\/directory conflict/u,
    );
  }
});

test("extension file-tree validation accepts replacements and names sharing only a text prefix", async () => {
  const root = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x88),
    plaintext: buildRootPlaintext([{ path: "a", data: Uint8Array.of(1) }]),
  });
  const extension = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x89),
    plaintext: buildExtensionPlaintext({
      index: 1,
      parentDocHash: root.docHash,
      rootDocHash: root.docHash,
      files: [
        { path: "a", data: Uint8Array.of(2) },
        { path: "ab/notes", data: Uint8Array.of(3) },
      ],
    }),
  });
  const result = await recoverLatestFromPlaintextDocuments([root, extension], {
    verifySignature: verifiedSignature,
  });
  assert.deepEqual(
    result.files.map((file) => [file.path, Array.from(file.data)]),
    [
      ["a", [2]],
      ["ab/notes", [3]],
    ],
  );
});

test("browser recovery resolves extension references to virtual root chunks", async () => {
  const rootBytes = new TextEncoder().encode("same root content");
  const rootPlaintext = buildRootPlaintext([{ path: "a.txt", data: rootBytes }]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x11),
    plaintext: rootPlaintext,
  });
  const extPlaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: rootBytes, inline: false }],
  });
  const extension = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x21),
    plaintext: extPlaintext,
  });

  const result = await recoverLatestFromPlaintextDocuments([root, extension], {
    verifySignature: verifiedSignature,
  });

  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "same root content"]],
  );
});

test("browser plaintext recovery enforces document count cap before decoding", async () => {
  const documents = Array.from({ length: MAX_RECOVERY_DOCUMENTS + 1 }, () => ({
    plaintext: Uint8Array.of(0),
  }));

  await assert.rejects(
    () => recoverLatestFromPlaintextDocuments(documents, { verifySignature: verifiedSignature }),
    /MAX_RECOVERY_DOCUMENTS/,
  );
});

test("browser plaintext recovery enforces per-document byte cap before decoding", async () => {
  const documents = [{ plaintext: new Uint8Array(MAX_CIPHERTEXT_BYTES + 1) }];

  await assert.rejects(
    () => recoverLatestFromPlaintextDocuments(documents, { verifySignature: verifiedSignature }),
    /MAX_CIPHERTEXT_BYTES/,
  );
});

test("browser recovery rejects extensions signed with a different key", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x12),
    plaintext: rootPlaintext,
  });
  const extPlaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const extension = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x22),
    plaintext: extPlaintext,
    signPub: OTHER_SIGN_PUB,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, extension], {
        verifySignature: verifiedSignature,
      }),
    /AUTH signing key does not match root signing key/,
  );
});

test("browser recovery authenticates extension documents before decoding their bodies", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x18),
    plaintext: rootPlaintext,
  });
  const extension = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x28),
    plaintext: buildExtensionDocumentBytes({ bodyBytes: Uint8Array.of(0xff) }),
    signPub: OTHER_SIGN_PUB,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, extension], {
        verifySignature: verifiedSignature,
      }),
    /AUTH signing key does not match root signing key/,
  );
});

test("browser recovery rejects root AUTH signed with a key different from the embedded seed", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x14),
    plaintext: rootPlaintext,
    signPub: OTHER_SIGN_PUB,
  });
  const extPlaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const extension = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x24),
    plaintext: extPlaintext,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, extension], {
        verifySignature: verifiedSignature,
      }),
    /AUTH signing key does not match root signing key/,
  );
});

test("browser recovery rejects extension replay from sealed roots", async () => {
  const rootPlaintext = buildRootPlaintext(
    [{ path: "a.txt", data: new TextEncoder().encode("root") }],
    { sealed: true },
  );
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x15),
    plaintext: rootPlaintext,
  });
  const extPlaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const extension = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x25),
    plaintext: extPlaintext,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, extension], {
        verifySignature: verifiedSignature,
      }),
    /extension replay requires an unsealed root backup with its signing seed/,
  );
});

test("browser recovery rejects broken authenticated extension ancestry", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x13),
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
    ciphertextSeed: Uint8Array.of(0x23),
    plaintext: extPlaintext,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, extension], {
        verifySignature: verifiedSignature,
      }),
    /extension index sequence is invalid/,
  );
});

test("browser recovery rejects extension root_doc_hash mismatch", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x16),
    plaintext: rootPlaintext,
  });
  const extPlaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: new Uint8Array(32).fill(0xee),
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const extension = documentFromPlaintext({
    docId: EXT1_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x26),
    plaintext: extPlaintext,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, extension], {
        verifySignature: verifiedSignature,
      }),
    /extension root_doc_hash does not match root backup/,
  );
});

test("browser recovery rejects extension parent_doc_hash mismatch", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x17),
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
    ciphertextSeed: Uint8Array.of(0x27),
    plaintext: ext1Plaintext,
  });
  const ext2Plaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("two") }],
  });
  const ext2 = documentFromPlaintext({
    docId: EXT2_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x37),
    plaintext: ext2Plaintext,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, ext1, ext2], {
        verifySignature: verifiedSignature,
      }),
    /extension parent_doc_hash does not match previous document/,
  );
});

test("browser recovery rejects a later profile that differs from the locked chain profile", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x18),
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
    ciphertextSeed: Uint8Array.of(0x28),
    plaintext: ext1Plaintext,
  });
  const ext2Plaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: ext1.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("two") }],
    chunking: { ...CHUNKING, targetSize: CHUNKING.targetSize * 2 },
  });
  const ext2 = documentFromPlaintext({
    docId: EXT2_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x38),
    plaintext: ext2Plaintext,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, ext1, ext2], {
        verifySignature: verifiedSignature,
      }),
    /extension chunking profile must match the locked chain profile/,
  );
});
