import assert from "node:assert/strict";
import test from "node:test";
import { gzipSync } from "node:zlib";

import { sha256 } from "@noble/hashes/sha2.js";

import {
  AUTH_DOMAIN,
  AUTH_VERSION,
  DOC_ID_LEN,
  DOCUMENT_MAGIC,
  BACKUP_DOCUMENT_VERSION,
  EXTENSION_DOCUMENT_VERSION,
  FRAME_TYPE_AUTH,
  FRAME_TYPE_MAIN,
  MAX_CIPHERTEXT_BYTES,
  MAX_DECOMPRESSED_PAYLOAD_BYTES,
  MAX_EXTENSION_INDEX,
  MAX_RECOVERY_DOCUMENTS,
  MAX_RECOVERY_DECODED_CHUNK_BYTES,
  textEncoder,
} from "../app/constants.js";
import { deriveSigningPublicKey, verifyAuthSignature } from "../app/auth.js";
import { resetAll } from "../app/actions_collect.js";
import { decryptCiphertext, extractBackupFiles } from "../app/actions_recover.js";
import {
  decodeExtensionDocument,
  decodeExtensionDocumentHeader,
  reconstructLatestFiles,
  reconstructLatestFilesFromDocuments,
} from "../app/extensions/document.js";
import { defaultExtensionChunker } from "../app/extensions/chunking.js";
import {
  recoverLatestFromEncryptedDocuments as recoverEncryptedCore,
  recoverLatestFromPlaintextDocuments as recoverPlaintextCore,
} from "../app/extensions/recovery.js";
import { readDocumentVersion } from "../app/backup_document.js";
import { addFrame } from "../app/frames_apply.js";
import { collectedRecoveryDocuments } from "../app/frames_cipher.js";
import { decodeFrame } from "../app/frames_protocol.js";
import { parseAutoPayload } from "../app/frames_parse.js";
import { createInitialState } from "../app/state/initial.js";
import { reducer } from "../app/state/reducer.js";
import {
  selectActionState,
  selectFrameCollectionComplete,
  selectFrameDiagnostics,
} from "../app/state/selectors.js";
import { encodeCbor } from "../lib/cbor.js";
import { blake2b256 } from "../lib/blake2b.js";
import { INTENSIVE_SCRYPT_APPROVAL_PREFIX } from "../lib/age_scrypt.js";
import { signSigningMessage } from "../lib/ed25519.js";
import { bytesToHex } from "../lib/bytes.js";
import { buildFrame, concatBytes, encodeUvarint } from "./protocol_test_data.mjs";

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
    files: files.map((file) => [
      file.path,
      file.data.length,
      sha256(file.data),
      file.mtime ?? null,
    ]),
  };
  return buildDocument(BACKUP_DOCUMENT_VERSION, encodeCbor(manifest), payload);
}

function buildExtensionPlaintext({
  index,
  parentDocHash,
  rootDocHash,
  files,
  chunking = CHUNKING,
}) {
  const chunksById = new Map();
  const fileEntries = files.map((file) => buildExtensionFileEntry(file, chunksById, chunking));
  const chunks = Array.from(chunksById.values())
    .sort((left, right) => left.chunkIdHex.localeCompare(right.chunkIdHex))
    .map((chunk) => [chunk.chunkId, 0, chunk.data.length, chunk.data]);
  const header = new Map([
    [1, 1],
    [2, index],
    [4, parentDocHash],
    [5, rootDocHash],
    [7, 1_700_000_100 + index],
    [10, [1, chunking.targetSize, chunking.minSize, chunking.maxSize]],
    [11, "file"],
    [12, []],
  ]);
  const body = new Map([
    [1, fileEntries],
    [2, chunks],
  ]);
  return buildDocument(EXTENSION_DOCUMENT_VERSION, encodeCbor(header), encodeCbor(body));
}

function buildExtensionDocumentBytes({ headerBytes = validExtensionHeaderBytes(), bodyBytes }) {
  return buildDocument(EXTENSION_DOCUMENT_VERSION, headerBytes, bodyBytes);
}

function buildDocumentWithVersionBytes(versionBytes, firstSection, secondSection) {
  return concatBytes([
    Uint8Array.from(DOCUMENT_MAGIC),
    versionBytes,
    encodeUvarint(firstSection.length),
    firstSection,
    encodeUvarint(secondSection.length),
    secondSection,
  ]);
}

function validExtensionHeaderMap() {
  return new Map([
    [1, 1],
    [2, 1],
    [4, new Uint8Array(32).fill(1)],
    [5, new Uint8Array(32).fill(2)],
    [7, 1_700_000_100],
    [10, [1, CHUNKING.targetSize, CHUNKING.minSize, CHUNKING.maxSize]],
    [11, "file"],
    [12, []],
  ]);
}

function validExtensionHeaderBytes() {
  return encodeCbor(validExtensionHeaderMap());
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

function inlineChunkLimitExtensionBodyBytes() {
  const firstChunkId = new Uint8Array(32).fill(1);
  const secondChunkId = new Uint8Array(32).fill(2);
  return encodeCbor(
    new Map([
      [
        1,
        [
          [
            "a.bin",
            MAX_DECOMPRESSED_PAYLOAD_BYTES,
            new Uint8Array(32),
            null,
            [[firstChunkId, MAX_DECOMPRESSED_PAYLOAD_BYTES]],
          ],
          ["b.bin", 1, new Uint8Array(32), null, [[secondChunkId, 1]]],
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

function buildExtensionFileEntry(file, chunksById, chunking = CHUNKING) {
  const refs = [];
  for (const chunk of defaultExtensionChunker(file.data, chunking)) {
    const chunkId = sha256(chunk);
    const chunkIdHex = bytesToHex(chunkId);
    refs.push([chunkId, chunk.length]);
    if (file.inline !== false) {
      chunksById.set(chunkIdHex, { chunkId, chunkIdHex, data: chunk });
    }
  }
  return [file.path, file.data.length, sha256(file.data), file.mtime ?? null, refs];
}

function buildDocument(version, firstSection, secondSection) {
  return concatBytes([
    Uint8Array.from(DOCUMENT_MAGIC),
    encodeUvarint(version),
    encodeUvarint(firstSection.length),
    firstSection,
    encodeUvarint(secondSection.length),
    secondSection,
  ]);
}

function createStore({ freshnessUnknownAcknowledged = true } = {}) {
  let state = createInitialState();
  state.freshnessUnknownAcknowledged = freshnessUnknownAcknowledged;
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

function explicitPlaintextFreshness(documents, options = {}) {
  const target = options.extensionTarget ?? "latest";
  if (options.freshnessUnknownAcknowledged === true || target?.expectedHeadDocHashHex) {
    return options;
  }
  if (target === "latest" || target?.kind === "latest") {
    return { ...options, freshnessUnknownAcknowledged: true };
  }
  if (target?.kind === "doc_hash") {
    return options;
  }
  if (target === "root" || target?.kind === "root" || target?.index === 0) {
    const root = documents.find(
      (document) => readDocumentVersion(document.plaintext) === BACKUP_DOCUMENT_VERSION,
    );
    return {
      ...options,
      extensionTarget: { kind: "root", expectedHeadDocHashHex: root?.docHashHex },
    };
  }
  if (target?.kind === "index") {
    const selected = documents.find((document) => {
      if (readDocumentVersion(document.plaintext) !== EXTENSION_DOCUMENT_VERSION) return false;
      return decodeExtensionDocumentHeader(document.plaintext).index === target.index;
    });
    return {
      ...options,
      extensionTarget: { ...target, expectedHeadDocHashHex: selected?.docHashHex },
    };
  }
  return options;
}

function recoverLatestFromPlaintextDocuments(documents, options = {}) {
  return recoverPlaintextCore(documents, explicitPlaintextFreshness(documents, options));
}

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
  return signSigningMessage(
    concatBytes([textEncoder.encode(AUTH_DOMAIN), signedBytes]),
    signingSeed,
  );
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

test("extension document rejects float-typed integer fields", async () => {
  const document = buildExtensionDocumentBytes({
    headerBytes: extensionHeaderWithVersionBytes(Uint8Array.of(0xf9, 0x3c, 0x00)),
    bodyBytes: validExtensionBodyBytes(),
  });

  await assert.rejects(
    () => decodeExtensionDocument(document),
    /extension header version must be an int/,
  );
});

test("extension document enforces cross-runtime V2 field bounds", async () => {
  const overIndexHeader = validExtensionHeaderMap();
  overIndexHeader.set(2, MAX_EXTENSION_INDEX + 1);
  const undersizedChunkingHeader = validExtensionHeaderMap();
  undersizedChunkingHeader.set(10, [1, 16 * 1024, 2 * 1024, 64 * 1024]);
  const oversizedChunkingHeader = validExtensionHeaderMap();
  oversizedChunkingHeader.set(10, [1, 16 * 1024, 4 * 1024, MAX_DECOMPRESSED_PAYLOAD_BYTES + 1]);
  const unorderedChunkingHeader = validExtensionHeaderMap();
  unorderedChunkingHeader.set(10, [1, 32 * 1024, 64 * 1024, 128 * 1024]);
  const chunkId = new Uint8Array(32).fill(0x42);
  const overFileSizeBody = new Map([
    [
      1,
      [
        [
          "large.bin",
          MAX_DECOMPRESSED_PAYLOAD_BYTES + 1,
          new Uint8Array(32),
          null,
          [[chunkId, MAX_DECOMPRESSED_PAYLOAD_BYTES + 1]],
        ],
      ],
    ],
    [2, []],
  ]);
  const overChunkRefBody = new Map([
    [
      1,
      [
        [
          "large.bin",
          MAX_DECOMPRESSED_PAYLOAD_BYTES,
          new Uint8Array(32),
          null,
          [[chunkId, MAX_DECOMPRESSED_PAYLOAD_BYTES + 1]],
        ],
      ],
    ],
    [2, []],
  ]);
  const cases = [
    {
      document: buildExtensionDocumentBytes({
        headerBytes: encodeCbor(overIndexHeader),
        bodyBytes: validExtensionBodyBytes(),
      }),
      pattern: /extension header index exceeds MAX_EXTENSION_INDEX/,
    },
    {
      document: buildExtensionDocumentBytes({
        headerBytes: encodeCbor(undersizedChunkingHeader),
        bodyBytes: validExtensionBodyBytes(),
      }),
      pattern: /extension chunking min_size must be >= 4096/,
    },
    {
      document: buildExtensionDocumentBytes({
        headerBytes: encodeCbor(oversizedChunkingHeader),
        bodyBytes: validExtensionBodyBytes(),
      }),
      pattern: /extension chunking max_size must be <= MAX_DECOMPRESSED_PAYLOAD_BYTES/,
    },
    {
      document: buildExtensionDocumentBytes({
        headerBytes: encodeCbor(unorderedChunkingHeader),
        bodyBytes: validExtensionBodyBytes(),
      }),
      pattern: /extension chunking sizes must satisfy min_size <= target_size <= max_size/,
    },
    {
      document: buildExtensionDocumentBytes({ bodyBytes: encodeCbor(overFileSizeBody) }),
      pattern: /extension file size exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES/,
    },
    {
      document: buildExtensionDocumentBytes({ bodyBytes: encodeCbor(overChunkRefBody) }),
      pattern: /extension chunk_ref uncompressed_len exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES/,
    },
  ];

  for (const testCase of cases) {
    await assert.rejects(() => decodeExtensionDocument(testCase.document), testCase.pattern);
  }
});

test("extension document accepts a custom FastCDC profile", async () => {
  const header = validExtensionHeaderMap();
  header.set(10, [1, 32 * 1024, 8 * 1024, 128 * 1024]);

  const decoded = await decodeExtensionDocument(
    buildExtensionDocumentBytes({
      headerBytes: encodeCbor(header),
      bodyBytes: validExtensionBodyBytes(),
    }),
  );

  assert.deepEqual(decoded.header.chunking, {
    algorithmId: 1,
    targetSize: 32 * 1024,
    minSize: 8 * 1024,
    maxSize: 128 * 1024,
  });
});

test("extension document rejects malformed header and body key sets", async () => {
  const headerWithUnknownKey = validExtensionHeaderMap();
  headerWithUnknownKey.set(99, true);
  const headerMissingInputRoots = validExtensionHeaderMap();
  headerMissingInputRoots.delete(12);
  const validData = new TextEncoder().encode("x");
  const validChunkId = sha256(validData);
  const validFile = ["a.txt", validData.length, sha256(validData), null, [[validChunkId, 1]]];
  const validChunk = [validChunkId, 0, validData.length, validData];
  const cases = [
    {
      name: "non-map header",
      headerBytes: encodeCbor([]),
      bodyBytes: validExtensionBodyBytes(),
      pattern: /extension header must be a map/,
    },
    {
      name: "unknown header key",
      headerBytes: encodeCbor(headerWithUnknownKey),
      bodyBytes: validExtensionBodyBytes(),
      pattern: /extension header contains unknown keys/,
    },
    {
      name: "missing required header key",
      headerBytes: encodeCbor(headerMissingInputRoots),
      bodyBytes: validExtensionBodyBytes(),
      pattern: /extension header key 12 is required/,
    },
    {
      name: "unknown body key",
      headerBytes: validExtensionHeaderBytes(),
      bodyBytes: encodeCbor(
        new Map([
          [1, [validFile]],
          [2, [validChunk]],
          [99, []],
        ]),
      ),
      pattern: /extension body contains unknown keys/,
    },
    {
      name: "missing body key",
      headerBytes: validExtensionHeaderBytes(),
      bodyBytes: encodeCbor(new Map([[1, [validFile]]])),
      pattern: /extension body files and chunks are required/,
    },
  ];

  for (const testCase of cases) {
    const document = buildExtensionDocumentBytes({
      headerBytes: testCase.headerBytes,
      bodyBytes: testCase.bodyBytes,
    });

    await assert.rejects(() => decodeExtensionDocument(document), testCase.pattern, testCase.name);
  }
});

test("extension document rejects overlong varints and nondeterministic CBOR", async () => {
  const overlongVersionDocument = buildDocumentWithVersionBytes(
    Uint8Array.of(0x82, 0x00),
    validExtensionHeaderBytes(),
    validExtensionBodyBytes(),
  );
  const nondeterministicHeader = buildExtensionDocumentBytes({
    headerBytes: extensionHeaderWithVersionBytes(Uint8Array.of(0x18, 0x01)),
    bodyBytes: validExtensionBodyBytes(),
  });

  await assert.rejects(() => decodeExtensionDocument(overlongVersionDocument), /overlong varint/);
  await assert.rejects(
    () => decodeExtensionDocument(nondeterministicHeader),
    /deterministic CBOR encoding/,
  );
});

test("extension document rejects path-like input root labels", async () => {
  for (const inputRoot of [".", "..", "docs/\u0001", "C:notes", "docs/root"]) {
    const document = buildExtensionDocumentBytes({
      headerBytes: extensionHeaderWithInputRootsBytes([inputRoot]),
      bodyBytes: validExtensionBodyBytes(),
    });

    await assert.rejects(() => decodeExtensionDocument(document));
  }
});

test("extension document accepts file order by Unicode code point", async () => {
  const codePointSortedBeforeSupplementary = "\ue000.txt";
  const supplementaryPath = "\u{10000}.txt";
  const document = buildExtensionPlaintext({
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

  const decoded = await decodeExtensionDocument(document);

  assert.deepEqual(
    decoded.files.map((file) => file.path),
    [codePointSortedBeforeSupplementary, supplementaryPath],
  );
});

test("extension document preflights total inline raw_len before gzip decode", async () => {
  const document = buildExtensionDocumentBytes({
    bodyBytes: inlineChunkLimitExtensionBodyBytes(),
  });

  await assert.rejects(
    () => decodeExtensionDocument(document),
    /extension inline chunk bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES/,
  );
});

test("extension document accepts single-member gzip chunks", async () => {
  const data = new TextEncoder().encode("x");
  const document = buildExtensionDocumentBytes({
    bodyBytes: extensionBodyWithGzipChunkBytes(gzipSync(data)),
  });

  const decoded = await decodeExtensionDocument(document);
  assert.equal(decoded.files[0].path, "a.txt");
});

test("extension document rejects trailing gzip members", async () => {
  const data = new TextEncoder().encode("x");
  const document = buildExtensionDocumentBytes({
    bodyBytes: extensionBodyWithGzipChunkBytes(
      new Uint8Array([...gzipSync(data), ...gzipSync(new Uint8Array())]),
    ),
  });

  await assert.rejects(
    () => decodeExtensionDocument(document),
    /gzip chunk contains trailing data/,
  );
});

test("extension replay decodes and releases one authenticated document at a time", async () => {
  const rootData = textEncoder.encode("root");
  const rootDocHash = new Uint8Array(32).fill(0x10);
  const extensionOneDocHash = new Uint8Array(32).fill(0x20);
  const extensionOnePlaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: rootDocHash,
    rootDocHash,
    files: [{ path: "a.txt", data: textEncoder.encode("one") }],
  });
  const extensionTwoPlaintext = buildExtensionPlaintext({
    index: 2,
    parentDocHash: extensionOneDocHash,
    rootDocHash,
    files: [{ path: "b.txt", data: textEncoder.encode("two") }],
  });
  const extensionDocuments = [
    {
      header: decodeExtensionDocumentHeader(extensionOnePlaintext),
      plaintext: extensionOnePlaintext,
      docHash: extensionOneDocHash,
    },
    {
      header: decodeExtensionDocumentHeader(extensionTwoPlaintext),
      plaintext: extensionTwoPlaintext,
      docHash: new Uint8Array(32).fill(0x30),
    },
  ];
  const calls = [];
  let liveDecodedDocuments = 0;
  let peakDecodedDocuments = 0;

  const files = await reconstructLatestFilesFromDocuments(
    [{ path: "root.txt", data: rootData }],
    rootDocHash,
    extensionDocuments,
    {
      async decodeDocument(plaintext, options) {
        const decodeChunks = options?.decodeChunks !== false;
        calls.push(decodeChunks ? "decode" : "metadata");
        const decoded = await decodeExtensionDocument(plaintext, options);
        if (decodeChunks) {
          liveDecodedDocuments += 1;
          peakDecodedDocuments = Math.max(peakDecodedDocuments, liveDecodedDocuments);
        }
        return decoded;
      },
      onExtensionReplayed() {
        liveDecodedDocuments -= 1;
      },
    },
  );

  assert.deepEqual(calls, ["metadata", "metadata", "decode", "decode"]);
  assert.equal(peakDecodedDocuments, 1);
  assert.equal(liveDecodedDocuments, 0);
  assert.deepEqual(
    files.map((file) => [file.path, new TextDecoder().decode(file.data)]),
    [
      ["a.txt", "one"],
      ["b.txt", "two"],
      ["root.txt", "root"],
    ],
  );
});

test("extension replay preflights the cumulative decoded chunk budget before decoding", async () => {
  const rootDocHash = new Uint8Array(32).fill(0x40);
  const chunking = CHUNKING;
  const extensionDocuments = [];
  let parentDocHash = rootDocHash;
  for (let index = 1; index <= 5; index += 1) {
    const docHash = new Uint8Array(32).fill(0x40 + index);
    extensionDocuments.push({
      header: {
        version: 1,
        index,
        parentDocHash,
        rootDocHash,
        createdAt: 1_700_000_000 + index,
        chunking,
        inputOrigin: "file",
        inputRoots: [],
      },
      plaintext: index,
      docHash,
    });
    parentDocHash = docHash;
  }
  let fullDecodeCount = 0;

  await assert.rejects(
    () =>
      reconstructLatestFilesFromDocuments([], rootDocHash, extensionDocuments, {
        async decodeDocument(index, options) {
          if (options?.decodeChunks !== false) {
            fullDecodeCount += 1;
            throw new Error("full decode must not start before cumulative preflight");
          }
          const chunkIdHex = index.toString(16).padStart(64, "0");
          return {
            header: extensionDocuments[index - 1].header,
            files: [{ chunkRefs: [{ chunkIdHex }] }],
            chunks: [{ chunkIdHex, rawLen: MAX_DECOMPRESSED_PAYLOAD_BYTES }],
          };
        },
      }),
    new RegExp(
      `extension chain inline chunk bytes exceed MAX_RECOVERY_DECODED_CHUNK_BYTES \\(${MAX_RECOVERY_DECODED_CHUNK_BYTES}\\)`,
    ),
  );
  assert.equal(MAX_RECOVERY_DECODED_CHUNK_BYTES, 4 * MAX_DECOMPRESSED_PAYLOAD_BYTES);
  assert.equal(fullDecodeCount, 0);
});

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
    /selected extension doc_hash .* could not be trusted: Error: AUTH signing key does not match root signing key/,
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

test("browser replay counts unchanged root files in latest-state byte limit", async () => {
  const rootDocHash = new Uint8Array(32).fill(0x9a);
  const rootData = new Uint8Array(MAX_DECOMPRESSED_PAYLOAD_BYTES);
  const extPlaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: rootDocHash,
    rootDocHash,
    files: [{ path: "added.txt", data: Uint8Array.of(1) }],
  });
  const extension = await decodeExtensionDocument(extPlaintext);
  extension.docHash = new Uint8Array(32).fill(0x9b);

  await assert.rejects(
    () => reconstructLatestFiles([{ path: "root.bin", data: rootData }], rootDocHash, [extension]),
    /logical latest state exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES/,
  );
});

test("browser replay rejects oversized logical files before allocating their declared size", async () => {
  const rootDocHash = new Uint8Array(32).fill(0x9c);
  const extension = {
    header: {
      version: 1,
      index: 1,
      parentDocHash: rootDocHash,
      rootDocHash,
      createdAt: 1_700_000_100,
      chunking: CHUNKING,
      inputOrigin: "file",
      inputRoots: [],
    },
    files: [
      {
        path: "oversized.bin",
        size: Number.MAX_SAFE_INTEGER,
        sha: new Uint8Array(32),
        mtime: null,
        chunkRefs: [],
      },
    ],
    chunks: [],
    docHash: new Uint8Array(32).fill(0x9d),
  };

  await assert.rejects(
    () => reconstructLatestFiles([], rootDocHash, [extension]),
    /logical latest state exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES/,
  );
});

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
    /selected extension doc_hash .* could not be decrypted: Error: damaged age payload/,
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
  decrypt.preflightBatch = () => ({ errors: [null, "scrypt work factor is unsupported"] });

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
          [1, 1],
          [2, 1],
          [4, root.docHash],
          [5, root.docHash],
          [7, 1_700_000_101],
          [10, [1, CHUNKING.targetSize, CHUNKING.minSize, CHUNKING.maxSize]],
          [11, "file"],
          [12, []],
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
  assert.equal(store.getState().recoveryComplete, true);
});

test("browser decrypt action retries normalized mnemonic whitespace after exact auth failure", async () => {
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
  const attemptedPassphrases = [];

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    async decrypt(ciphertext, passphrase) {
      attemptedPassphrases.push(passphrase);
      if (passphrase === enteredPassphrase) {
        throw new Error("invalid passphrase");
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
  assert.equal(store.getState().recoveryComplete, true);
});

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
  assert.equal(store.getState().recoveryComplete, true);
});

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
  assert.equal(store.getState().recoveryComplete, true);
});

test("browser decrypt action requires a second explicit action before intensive KDF work", async () => {
  const store = createStore();
  const state = store.getState();
  state.agePassphrase = "pw";
  const rootCiphertext = Uint8Array.of(0x48);
  const rootPlaintext = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  let decryptCalls = 0;
  const decrypt = async () => {
    decryptCalls += 1;
    return rootPlaintext;
  };
  decrypt.preflightBatch = (_documents, { allowResourceIntensive }) => {
    if (!allowResourceIntensive) {
      throw new Error(`${INTENSIVE_SCRYPT_APPROVAL_PREFIX} intensive test warning`);
    }
    return { errors: [null] };
  };
  const options = { decrypt, verifySignature: verifiedSignature };

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), options);

  let finalState = store.getState();
  assert.equal(decryptCalls, 0);
  assert.equal(finalState.decryptStatus.type, "warn");
  assert.deepEqual(finalState.decryptStatus.lines, ["intensive test warning"]);
  assert.deepEqual(finalState.intensiveRecoveryTarget, { kind: "latest" });

  await decryptCiphertext(store.dispatch.bind(store), store.getState.bind(store), {
    ...options,
    allowResourceIntensiveScrypt: true,
  });

  finalState = store.getState();
  assert.equal(decryptCalls, 1);
  assert.equal(finalState.recoveryComplete, true);
  assert.equal(finalState.intensiveRecoveryTarget, null);
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
  assert.equal(finalState.recoveryComplete, false);
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
  assert.equal(store.getState().recoveryComplete, false);
  assert.deepEqual(store.getState().frameStatus.lines, ["State cleared."]);
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
  assert.equal(finalState.recoveryComplete, true);
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
  assert.equal(finalState.recoveryComplete, true);
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
  assert.equal(finalState.recoveryComplete, true);
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
  assert.equal(finalState.recoveryComplete, true);
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
      [1, 1],
      [2, 2],
      [4, ext1.docHash],
      [5, root.docHash],
      [7, 1_700_000_102],
      [10, [1, CHUNKING.targetSize, CHUNKING.minSize, CHUNKING.maxSize]],
      [11, "file"],
      [12, []],
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

test("browser action state blocks latest recovery for AUTH-only extension records", () => {
  const state = createInitialState();
  state.agePassphrase = "pw";
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0x38) });
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

  assert.equal(selectActionState(state).canDecryptCiphertext, false);
  state.expectedHeadDocHashText = "aa".repeat(32);
  state.extensionTargetText = "root";
  assert.equal(selectActionState(state).canDecryptCiphertext, true);
  state.extensionTargetText = "1";
  assert.equal(selectActionState(state).canDecryptCiphertext, true);
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
  assert.equal(finalState.recoveryComplete, true);
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
  assert.equal(finalState.recoveryComplete, true);
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
  assert.equal(finalState.recoveryComplete, false);
  assert.equal(finalState.decryptStatus.type, "error");
  assert.match(
    finalState.decryptStatus.lines[0],
    /selected extension doc_hash .* could not be decrypted: Error: damaged age payload/,
  );
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
  assert.equal(finalState.recoveryComplete, false);
  assert.equal(finalState.decryptStatus.type, "error");
  assert.match(
    finalState.decryptStatus.lines[0],
    /one or more supplied backup documents could not be decrypted/,
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
  assert.equal(finalState.recoveryComplete, true);
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
  assert.equal(store.getState().recoveryComplete, true);
  assert.ok(
    store
      .getState()
      .decryptStatus.lines.includes(
        "Trust: Matched expected fingerprint; backup identity is bound. The sealed backup hash does not bind its signing key.",
      ),
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
  assert.equal(finalState.recoveryComplete, false);
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
  assert.equal(finalState.recoveryComplete, false);
  assert.equal(finalState.decryptStatus.type, "error");
  assert.match(finalState.decryptStatus.lines[0], /extension target/);
});

test("browser extract action extracts an already decrypted root document", async () => {
  const store = createStore();
  const state = store.getState();
  state.decryptedBackup = buildRootPlaintext([
    { path: "a.txt", data: new TextEncoder().encode("root") },
  ]);

  await extractBackupFiles(store.dispatch.bind(store), store.getState.bind(store));

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
  assert.equal(finalState.authErrors, 1);
  assert.equal(finalState.decryptStatus.type, "error");
  assert.equal(finalState.decryptStatus.lines[0], "Error: invalid AUTH frames detected");
});

test("browser frame diagnostics report invalid AUTH payloads", () => {
  const state = createInitialState();
  const frame = buildFrame({
    frameType: FRAME_TYPE_AUTH,
    docId: EXT1_DOC_ID,
    data: Uint8Array.of(0xff),
  });

  const added = parseAutoPayload(state, Buffer.from(frame).toString("base64").replace(/=+$/, ""));
  const diagnostics = selectFrameDiagnostics(state);

  assert.equal(added, 0);
  assert.equal(state.authErrors, 1);
  assert.equal(diagnostics.find((item) => item.label === "AUTH errors")?.value, "1");
});

test("browser frame collection rejects AUTH duplicates with changed signed fields", () => {
  const state = createInitialState();
  const rootCiphertext = Uint8Array.of(0x19);
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
          pub: OTHER_SIGN_PUB,
          sig: SIGNATURE,
        }),
      }),
    ),
  );

  assert.equal(state.authDuplicates, 0);
  assert.equal(state.authConflicts, 1);
  assert.equal(state.authStatus, "conflicting auth payloads");
  assert.equal(
    selectFrameDiagnostics(state).find((item) => item.label === "AUTH conflicts")?.value,
    "1",
  );
});

test("browser frame collection rejects AUTH duplicates with changed doc hash", () => {
  const state = createInitialState();
  const rootCiphertext = Uint8Array.of(0x1e);
  addSingleFrameDocument(state, { ciphertext: rootCiphertext });
  addFrame(
    state,
    decodeFrame(
      buildFrame({
        frameType: FRAME_TYPE_AUTH,
        docId: docIdForCiphertext(rootCiphertext),
        data: encodeCbor({
          version: 1,
          hash: new Uint8Array(32).fill(0xaa),
          pub: ROOT_SIGN_PUB,
          sig: SIGNATURE,
        }),
      }),
    ),
  );

  assert.equal(state.authDuplicates, 0);
  assert.equal(state.authConflicts, 1);
  assert.equal(state.authStatus, "conflicting auth payloads");
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

test("collected recovery documents reject AUTH frames without MAIN documents", () => {
  const state = createInitialState();
  const ciphertext = Uint8Array.of(0x9a);
  addSingleFrameDocument(state, { ciphertext });
  addFrame(
    state,
    decodeFrame(
      buildFrame({
        frameType: FRAME_TYPE_AUTH,
        docId: EXT1_DOC_ID,
        data: encodeCbor({
          version: 1,
          hash: new Uint8Array(32).fill(0xab),
          pub: ROOT_SIGN_PUB,
          sig: SIGNATURE,
        }),
      }),
    ),
  );

  assert.throws(() => collectedRecoveryDocuments(state), /AUTH frame\(s\) without MAIN/);
});

test("encrypted file download is disabled for multi-document scans", () => {
  const state = createInitialState();
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0xa1) });
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0xa2) });

  const actionState = selectActionState(state);

  assert.equal(actionState.canDownloadCipher, false);
  assert.equal(
    actionState.downloadCipherDisabledReason,
    "Encrypted file download is only available for one backup document.",
  );
});

test("browser action state requires an explicit latest freshness decision", () => {
  const state = createInitialState();
  state.agePassphrase = "pw";
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0xa0) });

  const blocked = selectActionState(state);
  assert.equal(blocked.canDecryptCiphertext, false);
  assert.equal(
    blocked.decryptDisabledReason,
    "Enter an expected head hash or acknowledge unknown freshness.",
  );

  state.freshnessUnknownAcknowledged = true;
  assert.equal(selectActionState(state).canDecryptCiphertext, true);
});

test("browser action state accepts the inline latest head hash", () => {
  const state = createInitialState();
  state.agePassphrase = "pw";
  state.extensionTargetText = `latest:${"ab".repeat(32)}`;
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0xa1) });

  const actionState = selectActionState(state);

  assert.equal(actionState.freshnessDecisionReady, true);
  assert.equal(actionState.canDecryptCiphertext, true);
});

test("multi-document collection waits for incomplete extensions before latest recovery", () => {
  const state = createInitialState();
  state.agePassphrase = "pw";
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0xa3) });
  addFrame(
    state,
    decodeFrame(
      buildFrame({
        frameType: FRAME_TYPE_MAIN,
        docId: EXT1_DOC_ID,
        index: 0,
        total: 2,
        data: Uint8Array.of(0xa4),
      }),
    ),
  );

  state.expectedHeadDocHashText = bytesToHex(blake2b256(Uint8Array.of(0xa3)));
  const latestActionState = selectActionState(state);
  assert.equal(selectFrameCollectionComplete(state), false);
  assert.equal(latestActionState.canDecryptCiphertext, false);
  assert.equal(latestActionState.canDecryptRootOnly, true);

  state.extensionTargetText = "root";
  assert.equal(selectActionState(state).canDecryptCiphertext, true);
});
