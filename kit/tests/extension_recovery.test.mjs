import assert from "node:assert/strict";
import test from "node:test";
import { gzipSync } from "node:zlib";

import { ed25519 } from "@noble/curves/ed25519.js";
import { sha256 } from "@noble/hashes/sha2.js";

import {
  AUTH_DOMAIN,
  AUTH_VERSION,
  DOC_ID_LEN,
  ENVELOPE_MAGIC,
  ENVELOPE_VERSION,
  EXTENSION_ENVELOPE_VERSION,
  FRAME_TYPE_AUTH,
  FRAME_TYPE_MAIN,
  MAX_DECOMPRESSED_PAYLOAD_BYTES,
  textEncoder,
} from "../app/constants.js";
import { deriveSigningPublicKey, verifyAuthSignature } from "../app/auth.js";
import { decryptCiphertext, extractEnvelope } from "../app/actions_recover.js";
import { decodeExtensionEnvelope, defaultExtensionChunker } from "../app/extension_envelope.js";
import {
  recoverLatestFromEncryptedDocuments,
  recoverLatestFromPlaintextDocuments,
} from "../app/extension_recovery.js";
import { addFrame } from "../app/frames_apply.js";
import { collectedRecoveryDocuments } from "../app/frames_cipher.js";
import { decodeFrame } from "../app/frames_protocol.js";
import { createInitialState } from "../app/state/initial.js";
import { reducer } from "../app/state/reducer.js";
import { encodeCbor } from "../lib/cbor.js";
import { blake2b256 } from "../lib/blake2b.js";
import { bytesToHex } from "../lib/encoding.js";
import { buildFrame, concatBytes, encodeUvarint } from "./test_helpers.mjs";

const CHUNKING = {
  algorithmId: 1,
  targetSize: 16 * 1024,
  minSize: 4 * 1024,
  maxSize: 64 * 1024,
};
const CONFORMANCE_CHUNKING = {
  algorithmId: 1,
  targetSize: 16 * 1024,
  minSize: 4 * 1024,
  maxSize: 64 * 1024,
};
const ROOT_DOC_ID = Uint8Array.from([1, 1, 1, 1, 1, 1, 1, 1]);
const EXT1_DOC_ID = Uint8Array.from([2, 2, 2, 2, 2, 2, 2, 2]);
const EXT2_DOC_ID = Uint8Array.from([3, 3, 3, 3, 3, 3, 3, 3]);
const ROOT_SIGNING_SEED = new Uint8Array(32).fill(0x44);
const ROOT_SIGN_PUB = deriveSigningPublicKey(ROOT_SIGNING_SEED);
const OTHER_SIGN_PUB = new Uint8Array(32).fill(0x55);
const SIGNATURE = new Uint8Array(64).fill(0x66);

function buildRootPlaintext(files, { sealed = false, signingSeed = ROOT_SIGNING_SEED } = {}) {
  const payload = concatBytes(files.map((file) => file.data));
  const manifest = {
    version: 1,
    created: 1_700_000_000,
    sealed,
    seed: sealed ? null : signingSeed,
    input_origin: "file",
    input_roots: [],
    payload_codec: "raw",
    path_encoding: "direct",
    files: files.map((file) => [file.path, file.data.length, sha256(file.data), null]),
  };
  return buildEnvelope(ENVELOPE_VERSION, encodeCbor(manifest), payload);
}

function buildExtensionPlaintext({ index, parentDocHash, rootDocHash, files }) {
  const chunksById = new Map();
  const recipes = files.map((file) => buildExtensionFileRecipe(file, chunksById));
  const chunks = Array.from(chunksById.values())
    .sort((left, right) => left.chunkIdHex.localeCompare(right.chunkIdHex))
    .map((chunk) => [chunk.chunkId, 0, chunk.data.length, chunk.data]);
  const header = new Map([
    [1, 1],
    [2, index],
    [4, parentDocHash],
    [5, rootDocHash],
    [7, 1_700_000_100 + index],
    [10, [1, CHUNKING.targetSize, CHUNKING.minSize, CHUNKING.maxSize]],
    [11, "file"],
    [12, []],
  ]);
  const body = new Map([
    [1, recipes],
    [2, chunks],
  ]);
  return buildEnvelope(EXTENSION_ENVELOPE_VERSION, encodeCbor(header), encodeCbor(body));
}

function buildExtensionEnvelopeBytes({ headerBytes = validExtensionHeaderBytes(), bodyBytes }) {
  return buildEnvelope(EXTENSION_ENVELOPE_VERSION, headerBytes, bodyBytes);
}

function validExtensionHeaderBytes() {
  return encodeCbor(
    new Map([
      [1, 1],
      [2, 1],
      [4, new Uint8Array(32).fill(1)],
      [5, new Uint8Array(32).fill(2)],
      [7, 1_700_000_100],
      [10, [1, CHUNKING.targetSize, CHUNKING.minSize, CHUNKING.maxSize]],
      [11, "file"],
      [12, []],
    ]),
  );
}

function validExtensionBodyBytes() {
  const data = new TextEncoder().encode("x");
  const chunkId = sha256(data);
  return encodeCbor(
    new Map([
      [1, [["a.txt", data.length, sha256(data), null, [[chunkId, data.length]]]]],
      [2, [[chunkId, 0, data.length, data]]],
    ]),
  );
}

function extensionBodyWithGzipChunkBytes(gzipData) {
  const data = new TextEncoder().encode("x");
  const chunkId = sha256(data);
  return encodeCbor(
    new Map([
      [1, [["a.txt", data.length, sha256(data), null, [[chunkId, data.length]]]]],
      [2, [[chunkId, 1, data.length, gzipData]]],
    ]),
  );
}

function extensionHeaderWithVersionBytes(versionBytes) {
  const pairs = [
    [encodeCbor(1), versionBytes],
    [encodeCbor(2), encodeCbor(1)],
    [encodeCbor(4), encodeCbor(new Uint8Array(32).fill(1))],
    [encodeCbor(5), encodeCbor(new Uint8Array(32).fill(2))],
    [encodeCbor(7), encodeCbor(1_700_000_100)],
    [encodeCbor(10), encodeCbor([1, CHUNKING.targetSize, CHUNKING.minSize, CHUNKING.maxSize])],
    [encodeCbor(11), encodeCbor("file")],
    [encodeCbor(12), encodeCbor([])],
  ];
  return concatBytes([Uint8Array.of(0xa8), ...pairs.flat()]);
}

function extensionHeaderWithInputRootsBytes(inputRoots) {
  return encodeCbor(
    new Map([
      [1, 1],
      [2, 1],
      [4, new Uint8Array(32).fill(1)],
      [5, new Uint8Array(32).fill(2)],
      [7, 1_700_000_100],
      [10, [1, CHUNKING.targetSize, CHUNKING.minSize, CHUNKING.maxSize]],
      [11, "directory"],
      [12, inputRoots],
    ]),
  );
}

function aggregateOverflowExtensionBodyBytes() {
  const firstChunkId = new Uint8Array(32).fill(1);
  const secondChunkId = new Uint8Array(32).fill(2);
  return encodeCbor(
    new Map([
      [
        1,
        [
          [
            "huge.bin",
            MAX_DECOMPRESSED_PAYLOAD_BYTES + 1,
            new Uint8Array(32),
            null,
            [
              [firstChunkId, MAX_DECOMPRESSED_PAYLOAD_BYTES],
              [secondChunkId, 1],
            ],
          ],
        ],
      ],
      [
        2,
        [
          [firstChunkId, 1, MAX_DECOMPRESSED_PAYLOAD_BYTES, Uint8Array.of(0x1f)],
          [secondChunkId, 1, 1, Uint8Array.of(0x1f)],
        ],
      ],
    ]),
  );
}

function buildExtensionFileRecipe(file, chunksById) {
  const refs = [];
  for (const chunk of defaultExtensionChunker(file.data, CHUNKING)) {
    const chunkId = sha256(chunk);
    const chunkIdHex = bytesToHex(chunkId);
    refs.push([chunkId, chunk.length]);
    if (file.inline !== false) {
      chunksById.set(chunkIdHex, { chunkId, chunkIdHex, data: chunk });
    }
  }
  return [file.path, file.data.length, sha256(file.data), null, refs];
}

function buildEnvelope(version, firstSection, secondSection) {
  return concatBytes([
    Uint8Array.from(ENVELOPE_MAGIC),
    encodeUvarint(version),
    encodeUvarint(firstSection.length),
    firstSection,
    encodeUvarint(secondSection.length),
    secondSection,
  ]);
}

function createStore() {
  let state = createInitialState();
  return {
    dispatch(action) {
      state = reducer(state, action);
    },
    getState() {
      return state;
    },
  };
}

function documentFromPlaintext({ docId, ciphertextSeed, plaintext, signPub = ROOT_SIGN_PUB }) {
  const docHash = blake2b256(ciphertextSeed);
  const resolvedDocId = docId ?? docHash.slice(0, DOC_ID_LEN);
  return {
    docId: resolvedDocId,
    docIdHex: bytesToHex(resolvedDocId),
    docHash,
    docHashHex: bytesToHex(docHash),
    ciphertext: ciphertextSeed,
    plaintext,
    authPayload: { version: 1, docHash, signPub, signature: SIGNATURE },
  };
}

function addSingleFrameDocument(
  state,
  { docId, ciphertext, signPub = ROOT_SIGN_PUB, signature = SIGNATURE },
) {
  const resolvedDocId = docId ?? docIdForCiphertext(ciphertext);
  addFrame(
    state,
    decodeFrame(buildFrame({ frameType: FRAME_TYPE_MAIN, docId: resolvedDocId, data: ciphertext })),
  );
  addFrame(
    state,
    decodeFrame(
      buildFrame({
        frameType: FRAME_TYPE_AUTH,
        docId: resolvedDocId,
        data: encodeCbor({
          version: 1,
          hash: blake2b256(ciphertext),
          pub: signPub,
          sig: signature,
        }),
      }),
    ),
  );
}

function docIdForCiphertext(ciphertext) {
  return blake2b256(ciphertext).slice(0, DOC_ID_LEN);
}

function verifiedSignature(docHash, signPub, signature) {
  assert.equal(docHash.length, 32);
  assert.equal(signPub.length, 32);
  assert.equal(signature.length, 64);
  return true;
}

function signAuthPayload(docHash, signPub = ROOT_SIGN_PUB, signingSeed = ROOT_SIGNING_SEED) {
  const signedPayload = { version: AUTH_VERSION, hash: docHash, pub: signPub };
  const signedBytes = encodeCbor(signedPayload);
  return ed25519.sign(concatBytes([textEncoder.encode(AUTH_DOMAIN), signedBytes]), signingSeed);
}

function chunkOffsetsAndHashes(chunks) {
  const offsets = [];
  const hashes = [];
  let offset = 0;
  for (const chunk of chunks) {
    offset += chunk.length;
    offsets.push(offset);
    hashes.push(bytesToHex(sha256(chunk)));
  }
  return { offsets, hashes };
}

function repeatedRange256(times) {
  const out = new Uint8Array(256 * times);
  for (let index = 0; index < out.length; index += 1) {
    out[index] = index % 256;
  }
  return out;
}

function hashSequence(count) {
  const out = new Uint8Array(count * 32);
  const input = new Uint8Array(4);
  const view = new DataView(input.buffer);
  for (let index = 0; index < count; index += 1) {
    view.setUint32(0, index, false);
    out.set(sha256(input), index * 32);
  }
  return out;
}

test("extension chunker matches Algorithm 1 conformance vectors", () => {
  const vectors = [
    {
      data: new Uint8Array(),
      offsets: [],
      hashes: [],
    },
    {
      data: repeatedRange256(512),
      offsets: [65536, 131072],
      hashes: [
        "7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2",
        "7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2",
      ],
    },
    {
      data: hashSequence(4096),
      offsets: [18096, 26931, 43917, 62046, 73496, 93396, 110690, 125496, 130017, 131072],
      hashes: [
        "2ee1e2166281185f001965a7c45631c880b8732f3f48a3f23d61805da105dda8",
        "eb1e03f0bac68f0171871be76601ab5e8ff1cd0b6ebe65fec952d4008d49d8ba",
        "715518ae12c7f500032a27dd79d7605f65e3b407ee2fe4b069f6deb8234ad476",
        "878633ff4a700041ebd6d4d852aed0215f6710cf6991d4f321a3b2fd2b2be830",
        "782c360b17d0e7cf76562843a8a199572c79e424f914ec72a79b35c2a5953480",
        "da2fa8816f90d81e80df05a7728bc46329dc0d77ea994cf91a21d4a4ae7d5fb1",
        "67b130801247f8d07cd21510e6bc3f37bb5b6a382b68ce9d622e464585647b38",
        "e8b033381f576d7d299a60c4fde4a718d3ebe2d15f6a914d2e5d5188108cc701",
        "eb32376d8f8546f442fac429456036034c22a9cee10c70fd39c3f575abe5696e",
        "dfd9fa02180e25f17871e98fd975ba8145952dc3e48f01b28ba4f1f8bee17df5",
      ],
    },
    {
      data: new TextEncoder().encode("alpha beta gamma delta\n".repeat(4096)),
      offsets: [65536, 94208],
      hashes: [
        "bfa07175ee95b43642ae3fbcad382d7ecf5dd7fad2d496933ad68e7f14f803af",
        "d4ffdf00862a1b920325b2fabc25e8621cbb7ce8171803702285b078fd0259c2",
      ],
    },
  ];

  for (const vector of vectors) {
    const chunks = defaultExtensionChunker(vector.data, CONFORMANCE_CHUNKING);
    assert.deepEqual(chunkOffsetsAndHashes(chunks), {
      offsets: vector.offsets,
      hashes: vector.hashes,
    });
  }
});

test("auth verification accepts signatures from the embedded root signing seed", async () => {
  const docHash = sha256(new TextEncoder().encode("ciphertext"));
  const signature = signAuthPayload(docHash);

  assert.equal(await verifyAuthSignature(docHash, ROOT_SIGN_PUB, signature), true);
});

test("extension envelope rejects float-typed integer fields", async () => {
  const envelope = buildExtensionEnvelopeBytes({
    headerBytes: extensionHeaderWithVersionBytes(Uint8Array.of(0xf9, 0x3c, 0x00)),
    bodyBytes: validExtensionBodyBytes(),
  });

  await assert.rejects(
    () => decodeExtensionEnvelope(envelope),
    /extension header version must be an int/,
  );
});

test("extension envelope rejects path-like input root labels", async () => {
  for (const inputRoot of [".", "..", "docs/\u0001", "C:notes", "docs/root"]) {
    const envelope = buildExtensionEnvelopeBytes({
      headerBytes: extensionHeaderWithInputRootsBytes([inputRoot]),
      bodyBytes: validExtensionBodyBytes(),
    });

    await assert.rejects(() => decodeExtensionEnvelope(envelope));
  }
});

test("extension envelope accepts file order by Unicode code point", async () => {
  const codePointSortedBeforeSupplementary = "\ue000.txt";
  const supplementaryPath = "\u{10000}.txt";
  const envelope = buildExtensionPlaintext({
    index: 1,
    parentDocHash: new Uint8Array(32).fill(1),
    rootDocHash: new Uint8Array(32).fill(2),
    files: [
      {
        path: codePointSortedBeforeSupplementary,
        data: textEncoder.encode("first"),
      },
      {
        path: supplementaryPath,
        data: textEncoder.encode("second"),
      },
    ],
  });

  const decoded = await decodeExtensionEnvelope(envelope);

  assert.deepEqual(
    decoded.files.map((file) => file.path),
    [codePointSortedBeforeSupplementary, supplementaryPath],
  );
});

test("extension envelope preflights aggregate inline raw_len before gzip decode", async () => {
  const envelope = buildExtensionEnvelopeBytes({
    bodyBytes: aggregateOverflowExtensionBodyBytes(),
  });

  await assert.rejects(
    () => decodeExtensionEnvelope(envelope),
    /extension inline chunk bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES/,
  );
});

test("extension envelope accepts single-member gzip chunks", async () => {
  const data = new TextEncoder().encode("x");
  const envelope = buildExtensionEnvelopeBytes({
    bodyBytes: extensionBodyWithGzipChunkBytes(gzipSync(data)),
  });

  const decoded = await decodeExtensionEnvelope(envelope);
  assert.equal(decoded.files[0].path, "a.txt");
});

test("extension envelope rejects trailing gzip members", async () => {
  const data = new TextEncoder().encode("x");
  const envelope = buildExtensionEnvelopeBytes({
    bodyBytes: extensionBodyWithGzipChunkBytes(
      new Uint8Array([...gzipSync(data), ...gzipSync(new Uint8Array())]),
    ),
  });

  await assert.rejects(
    () => decodeExtensionEnvelope(envelope),
    /gzip chunk contains trailing data/,
  );
});

test("browser recovery replays the latest supplied authenticated extension chain", async () => {
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
    files: [{ path: "b.txt", data: new TextEncoder().encode("two") }],
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
  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [
      ["a.txt", "one"],
      ["b.txt", "two"],
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

test("browser encrypted recovery fails closed when a supplied document cannot decrypt", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x16),
    plaintext: rootPlaintext,
  });
  const extension = {
    docId: EXT1_DOC_ID,
    docIdHex: bytesToHex(EXT1_DOC_ID),
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

test("browser root-only encrypted recovery ignores a supplied extension decrypt failure", async () => {
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  const root = documentFromPlaintext({
    docId: ROOT_DOC_ID,
    ciphertextSeed: Uint8Array.of(0x1a),
    plaintext: rootPlaintext,
  });
  const extension = {
    docId: EXT1_DOC_ID,
    docIdHex: bytesToHex(EXT1_DOC_ID),
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

  const result = await recoverLatestFromEncryptedDocuments(
    [root, extension],
    "pw",
    async (ciphertext) => {
      if (bytesToHex(ciphertext) === bytesToHex(root.ciphertext)) return rootPlaintext;
      throw new Error("damaged age payload");
    },
    { verifySignature: verifiedSignature, extensionTarget: "root" },
  );

  assert.equal(result.replayTarget, "root");
  assert.equal(result.selectedExtensionIndex, null);
  assert.deepEqual(
    result.files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "root"]],
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
    plaintext: buildExtensionEnvelopeBytes({ bodyBytes: Uint8Array.of(0xff) }),
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, malformedDocument], {
        verifySignature: verifiedSignature,
      }),
    /root-authority extension could not be decoded/,
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
  assert.equal(finalState.recoveryComplete, true);
  assert.equal(finalState.decryptStatus.type, "ok");
  assert.deepEqual(
    finalState.extractedFiles.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "extension"]],
  );
  assert.equal(
    finalState.decryptStatus.lines.includes(
      "Replay target: latest supplied authenticated extension 1.",
    ),
    true,
  );
  assert.equal(
    finalState.decryptStatus.lines.includes("Freshness scope: supplied carriers only."),
    true,
  );
});

test("browser decrypt action can recover root only from multiple supplied documents", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x1c);
  const extCiphertext = Uint8Array.of(0x2c);
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
  assert.equal(finalState.recoveryComplete, true);
  assert.equal(finalState.decryptStatus.type, "ok");
  assert.notEqual(finalState.decryptedEnvelope, null);
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

test("browser extract action extracts an already decrypted root envelope", async () => {
  const store = createStore();
  const state = store.getState();
  state.decryptedEnvelope = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);

  await extractEnvelope(store.dispatch.bind(store), store.getState.bind(store));

  const finalState = store.getState();
  assert.equal(finalState.extractStatus.type, "ok");
  assert.deepEqual(
    finalState.extractedFiles.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [["a.txt", "root"]],
  );
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
  assert.equal(finalState.decryptStatus.lines[0], "Error: conflicting AUTH frames detected");
});

test("browser recovery rejects extensions outside the root signing authority", async () => {
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
    /AUTH signing key does not match root authority/,
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
    plaintext: buildExtensionEnvelopeBytes({ bodyBytes: Uint8Array.of(0xff) }),
    signPub: OTHER_SIGN_PUB,
  });

  await assert.rejects(
    () =>
      recoverLatestFromPlaintextDocuments([root, extension], {
        verifySignature: verifiedSignature,
      }),
    /AUTH signing key does not match root authority/,
  );
});

test("browser recovery rejects root AUTH outside embedded signing authority", async () => {
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
    /AUTH signing key does not match root authority/,
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
    /extension replay requires an unsealed root signing authority/,
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

test("frame collection accepts multiple MAIN documents without doc_id conflicts", () => {
  const state = createInitialState();
  const rootCiphertext = Uint8Array.of(0xaa);
  const extensionCiphertext = Uint8Array.of(0xbb);
  const rootDocId = docIdForCiphertext(rootCiphertext);
  const extensionDocId = docIdForCiphertext(extensionCiphertext);
  const rootAuthPayload = encodeCbor({
    version: 1,
    hash: blake2b256(rootCiphertext),
    pub: ROOT_SIGN_PUB,
    sig: SIGNATURE,
  });
  const extensionAuthPayload = encodeCbor({
    version: 1,
    hash: blake2b256(extensionCiphertext),
    pub: ROOT_SIGN_PUB,
    sig: SIGNATURE,
  });

  addFrame(
    state,
    decodeFrame(buildFrame({ frameType: FRAME_TYPE_MAIN, docId: rootDocId, data: rootCiphertext })),
  );
  addFrame(
    state,
    decodeFrame(
      buildFrame({ frameType: FRAME_TYPE_AUTH, docId: rootDocId, data: rootAuthPayload }),
    ),
  );
  addFrame(
    state,
    decodeFrame(
      buildFrame({ frameType: FRAME_TYPE_MAIN, docId: extensionDocId, data: extensionCiphertext }),
    ),
  );
  addFrame(
    state,
    decodeFrame(
      buildFrame({ frameType: FRAME_TYPE_AUTH, docId: extensionDocId, data: extensionAuthPayload }),
    ),
  );

  assert.equal(state.documents.size, 2);
  assert.equal(state.conflicts, 0);
  assert.equal(state.authConflicts, 0);
  assert.equal(state.mainFrames.size, 1);
  assert.equal(bytesToHex(state.authPayload.docHash), bytesToHex(blake2b256(rootCiphertext)));
});

test("collected recovery documents reject frame doc_id not derived from ciphertext", () => {
  const state = createInitialState();
  const ciphertext = Uint8Array.of(0x99);
  const fakeDocId = Uint8Array.from([1, 2, 3, 4, 5, 6, 7, 8]);

  addFrame(
    state,
    decodeFrame(buildFrame({ frameType: FRAME_TYPE_MAIN, docId: fakeDocId, data: ciphertext })),
  );

  assert.throws(() => collectedRecoveryDocuments(state), /doc_id/);
});
