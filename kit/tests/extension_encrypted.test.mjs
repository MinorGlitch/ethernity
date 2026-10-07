import { RecoveryError } from "../lib/errors.js";
import assert from "node:assert/strict";
import test from "node:test";
import {
  EXTENSION_DOCUMENT_VERSION,
  MAX_CIPHERTEXT_BYTES,
  MAX_RECOVERY_DOCUMENTS,
  textEncoder,
} from "../app/constants.js";
import { decodeExtensionDocumentHeader } from "../app/extensions/document.js";
import { recoverLatestFromEncryptedDocuments as recoverEncryptedCore } from "../app/extensions/recovery.js";
import { readDocumentVersion } from "../app/backup_document.js";
import { blake2b256 } from "../lib/blake2b.js";
import { bytesToHex } from "../lib/bytes.js";
import {
  ROOT_SIGN_PUB,
  OTHER_SIGN_PUB,
  SIGNATURE,
  buildRootPlaintext,
  buildExtensionPlaintext,
  documentFromPlaintext,
  verifiedSignature,
} from "./extension_test_data.mjs";

function recoverLatestFromEncryptedDocuments(documents, passphrase, decrypt, options = {}) {
  const target = options.extensionTarget ?? "latest";
  if (!options.freshnessUnknownAcknowledged && (target === "latest" || target?.kind === "latest")) {
    return recoverEncryptedCore(documents, passphrase, decrypt, {
      ...options,
      freshnessUnknownAcknowledged: true,
    });
  }
  if (!target?.expectedHeadDocHashHex) {
    if (target === "root" || target?.kind === "root" || target?.index === 0) {
      const root = documents[0];
      return recoverEncryptedCore(documents, passphrase, decrypt, {
        ...options,
        extensionTarget: {
          kind: "root",
          expectedHeadDocHashHex:
            root.docHashHex ?? bytesToHex(root.docHash ?? blake2b256(root.ciphertext)),
        },
      });
    }
    if (target?.kind === "index") {
      const selected = documents.find((document) => {
        if (!document.plaintext) return false;
        if (readDocumentVersion(document.plaintext) !== EXTENSION_DOCUMENT_VERSION) return false;
        return decodeExtensionDocumentHeader(document.plaintext).index === target.index;
      });
      if (selected) {
        return recoverEncryptedCore(documents, passphrase, decrypt, {
          ...options,
          extensionTarget: { ...target, expectedHeadDocHashHex: selected.docHashHex },
        });
      }
    }
  }
  return recoverEncryptedCore(documents, passphrase, decrypt, options);
}

test("browser encrypted recovery fails closed when a supplied document cannot decrypt", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x16),
    plaintext: rootPlaintext,
  });
  const extension = {
    docHash: blake2b256(Uint8Array.of(0x26)),
    docHashHex: bytesToHex(blake2b256(Uint8Array.of(0x26))),
    ciphertext: Uint8Array.of(0x26),
    authPayload: {
      version: 1,
      docHash: blake2b256(Uint8Array.of(0x26)),
      signPub: ROOT_SIGN_PUB,
      signature: SIGNATURE,
    },
  };

  await assert.rejects(
    () =>
      recoverLatestFromEncryptedDocuments(
        [root, extension],
        "pw",
        async (ciphertext) => {
          if (bytesToHex(ciphertext) === bytesToHex(root.ciphertext)) {
            return rootPlaintext;
          }
          throw new Error("damaged age payload");
        },
        { verifySignature: verifiedSignature },
      ),
    /one or more supplied backup documents could not be decrypted/,
  );
});

test("browser latest recovery rejects a failed scrypt preflight before any KDF work", async () => {
  let decryptCalls = 0;
  const decrypt = async () => {
    decryptCalls += 1;
    throw new Error("decrypt must not run");
  };
  decrypt.preflightBatch = () => ({
    errors: [null, "scrypt work factor must be between 1 and 20"],
  });

  await assert.rejects(
    () =>
      recoverLatestFromEncryptedDocuments(
        [{ ciphertext: Uint8Array.of(1) }, { ciphertext: Uint8Array.of(2) }],
        "pw",
        decrypt,
      ),
    /scrypt work factor must be between 1 and 20/,
  );
  assert.equal(decryptCalls, 0);
});

test("browser latest recovery rejects an invalid supplied AUTH before any KDF work", async () => {
  const document = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x71),
    plaintext: buildRootPlaintext([{ path: "a.txt", data: textEncoder.encode("root") }]),
  });
  let decryptCalls = 0;
  let verifyCalls = 0;

  await assert.rejects(
    () =>
      recoverLatestFromEncryptedDocuments(
        [document],
        "pw",
        async () => {
          decryptCalls += 1;
          throw new Error("decrypt must not run");
        },
        {
          verifySignature() {
            verifyCalls += 1;
            return false;
          },
        },
      ),
    /AUTH signature is invalid/,
  );
  assert.equal(verifyCalls, 1);
  assert.equal(decryptCalls, 0);
});

test("browser latest recovery rejects mixed advertised authorities before any KDF work", async () => {
  const plaintext = buildRootPlaintext([{ path: "a.txt", data: textEncoder.encode("root") }]);
  const documents = [
    documentFromPlaintext({ ciphertextSeed: Uint8Array.of(0x72), plaintext }),
    documentFromPlaintext({
      ciphertextSeed: Uint8Array.of(0x73),
      plaintext,
      signPub: OTHER_SIGN_PUB,
    }),
  ];
  let decryptCalls = 0;
  let verifyCalls = 0;

  await assert.rejects(
    () =>
      recoverLatestFromEncryptedDocuments(
        documents,
        "pw",
        async () => {
          decryptCalls += 1;
          throw new Error("decrypt must not run");
        },
        {
          verifySignature() {
            verifyCalls += 1;
            return true;
          },
        },
      ),
    /multiple signing keys/,
  );
  assert.equal(verifyCalls, 2);
  assert.equal(decryptCalls, 0);
});

test("browser root-only recovery skips an unrelated document with invalid AUTH", async () => {
  const rootPlaintext = buildRootPlaintext([{ path: "a.txt", data: textEncoder.encode("root") }]);
  const root = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x74),
    plaintext: rootPlaintext,
  });
  const unrelated = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x75),
    plaintext: Uint8Array.of(0),
  });
  unrelated.authPayload = {
    ...unrelated.authPayload,
    signature: new Uint8Array(64).fill(0x77),
  };
  let decryptCalls = 0;

  const result = await recoverLatestFromEncryptedDocuments(
    [root, unrelated],
    "pw",
    async (ciphertext) => {
      decryptCalls += 1;
      assert.equal(bytesToHex(ciphertext), bytesToHex(root.ciphertext));
      return rootPlaintext;
    },
    {
      extensionTarget: "root",
      verifySignature(_docHash, _signPub, signature) {
        return signature[0] === SIGNATURE[0];
      },
    },
  );

  assert.equal(decryptCalls, 1);
  assert.equal(result.replayTarget, "root");
});

test("browser encrypted recovery rejects caller-supplied doc hash metadata", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x56),
    plaintext: rootPlaintext,
  });
  const tampered = {
    ...root,
    docHash: new Uint8Array(32).fill(0xaa),
    docHashHex: "aa".repeat(32),
  };

  await assert.rejects(
    () =>
      recoverLatestFromEncryptedDocuments([tampered], "pw", async () => rootPlaintext, {
        verifySignature: verifiedSignature,
        extensionTarget: "root",
      }),
    /supplied doc_hash does not match derived ciphertext identity/,
  );
});

test("browser encrypted recovery enforces document count cap before decrypting", async () => {
  let decryptCalls = 0;
  const documents = Array.from({ length: MAX_RECOVERY_DOCUMENTS + 1 }, (_value, index) => ({
    ciphertext: Uint8Array.of(index & 0xff),
  }));

  await assert.rejects(
    () =>
      recoverLatestFromEncryptedDocuments(documents, "pw", async () => {
        decryptCalls += 1;
        return new Uint8Array();
      }),
    /MAX_RECOVERY_DOCUMENTS/,
  );
  assert.equal(decryptCalls, 0);
});

test("browser encrypted recovery enforces per-document ciphertext cap before decrypting", async () => {
  let decryptCalls = 0;
  const documents = [{ ciphertext: new Uint8Array(MAX_CIPHERTEXT_BYTES + 1) }];

  await assert.rejects(
    () =>
      recoverLatestFromEncryptedDocuments(documents, "pw", async () => {
        decryptCalls += 1;
        return new Uint8Array();
      }),
    /MAX_CIPHERTEXT_BYTES/,
  );
  assert.equal(decryptCalls, 0);
});

test("browser encrypted recovery ignores later decrypt failures for an explicit index target", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x46),
    plaintext: rootPlaintext,
  });
  const ext1Plaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: root.docHash,
    rootDocHash: root.docHash,
    files: [{ path: "a.txt", data: new TextEncoder().encode("one") }],
  });
  const ext1 = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x47),
    plaintext: ext1Plaintext,
  });
  const ext2 = {
    docHash: blake2b256(Uint8Array.of(0x48)),
    docHashHex: bytesToHex(blake2b256(Uint8Array.of(0x48))),
    ciphertext: Uint8Array.of(0x48),
    authPayload: {
      version: 1,
      docHash: blake2b256(Uint8Array.of(0x48)),
      signPub: ROOT_SIGN_PUB,
      signature: SIGNATURE,
    },
  };

  const result = await recoverLatestFromEncryptedDocuments(
    [root, ext2, ext1],
    "pw",
    async (ciphertext) => {
      if (bytesToHex(ciphertext) === bytesToHex(root.ciphertext)) return rootPlaintext;
      if (bytesToHex(ciphertext) === bytesToHex(ext1.ciphertext)) return ext1Plaintext;
      throw new Error("damaged age payload");
    },
    { verifySignature: verifiedSignature, extensionTarget: { kind: "index", index: 1 } },
  );

  assert.equal(result.selectedExtensionIndex, 1);
  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "one"]],
  );
});

test("browser encrypted recovery reports selected doc hash decrypt failure", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x49),
    plaintext: rootPlaintext,
  });
  const extensionCiphertext = Uint8Array.of(0x4a);
  const extensionDocHash = blake2b256(extensionCiphertext);
  const extension = {
    docHash: extensionDocHash,
    docHashHex: bytesToHex(extensionDocHash),
    ciphertext: extensionCiphertext,
    authPayload: {
      version: 1,
      docHash: extensionDocHash,
      signPub: ROOT_SIGN_PUB,
      signature: SIGNATURE,
    },
  };

  await assert.rejects(
    () =>
      recoverLatestFromEncryptedDocuments(
        [root, extension],
        "pw",
        async (ciphertext) => {
          if (bytesToHex(ciphertext) === bytesToHex(root.ciphertext)) return rootPlaintext;
          throw new Error("damaged age payload");
        },
        {
          verifySignature: verifiedSignature,
          extensionTarget: { kind: "doc_hash", docHashHex: extension.docHashHex },
        },
      ),
    /selected extension doc_hash .* could not be decrypted: damaged age payload/,
  );
});

test("browser root-only encrypted recovery ignores a supplied extension decrypt failure", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    ciphertextSeed: Uint8Array.of(0x1a),
    plaintext: rootPlaintext,
  });
  const extension = {
    docHash: blake2b256(Uint8Array.of(0x2a)),
    docHashHex: bytesToHex(blake2b256(Uint8Array.of(0x2a))),
    ciphertext: Uint8Array.of(0x2a),
    authPayload: {
      version: 1,
      docHash: blake2b256(Uint8Array.of(0x2a)),
      signPub: ROOT_SIGN_PUB,
      signature: SIGNATURE,
    },
  };

  let decryptCalls = 0;
  const decrypt = async (ciphertext) => {
    decryptCalls += 1;
    if (bytesToHex(ciphertext) === bytesToHex(root.ciphertext)) return rootPlaintext;
    throw new Error("preflight-rejected document must not be decrypted");
  };
  decrypt.preflightBatch = () => ({
    errors: [
      null,
      new RecoveryError("RECOVERY_RESOURCE_LIMIT", "scrypt work factor is unsupported"),
    ],
  });

  const result = await recoverLatestFromEncryptedDocuments([root, extension], "pw", decrypt, {
    verifySignature: verifiedSignature,
    extensionTarget: "root",
  });

  assert.equal(decryptCalls, 1);
  assert.equal(result.replayTarget, "root");
  assert.equal(result.selectedExtensionIndex, null);
  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "root"]],
  );
});
