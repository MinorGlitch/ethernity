import { primaryDocumentRecord, documentCounts } from "../app/documents/store.js";
import assert from "node:assert/strict";
import test from "node:test";
import { gzipSync } from "node:zlib";
import { sha256 } from "@noble/hashes/sha2.js";
import {
  DOCUMENT_MAGIC,
  FRAME_TYPE_AUTH,
  FRAME_TYPE_MAIN,
  MAX_DECOMPRESSED_PAYLOAD_BYTES,
  MAX_EXTENSION_INDEX,
  textEncoder,
} from "../app/constants.js";
import { verifyAuthSignature } from "../app/auth.js";
import { decodeExtensionDocument } from "../app/extensions/document.js";
import { defaultExtensionChunker } from "../app/extensions/chunking.js";
import { addFrame } from "../app/frames_apply.js";
import { decodeFrame } from "../app/frames_protocol.js";
import { createInitialState } from "../app/state/initial.js";
import { selectFrameDiagnostics } from "../app/state/selectors.js";
import { encodeCbor } from "../lib/cbor.js";
import { blake2b256 } from "../lib/blake2b.js";
import { bytesToHex } from "../lib/bytes.js";
import { signAuthPayload, buildFrame, concatBytes, encodeUvarint } from "./protocol_test_data.mjs";
import {
  CHUNKING,
  ROOT_SIGNING_SEED,
  ROOT_SIGN_PUB,
  OTHER_SIGN_PUB,
  SIGNATURE,
  buildExtensionPlaintext,
  buildExtensionDocumentBytes,
  validExtensionHeaderMap,
  validExtensionHeaderBytes,
  addSingleFrameDocument,
  docIdForCiphertext,
} from "./extension_test_data.mjs";

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

function extensionHeaderWithIndexBytes(versionBytes) {
  const pairs = [
    [encodeCbor(2), versionBytes],
    [encodeCbor(4), encodeCbor(new Uint8Array(32).fill(1))],
    [encodeCbor(5), encodeCbor(new Uint8Array(32).fill(2))],
    [encodeCbor(7), encodeCbor(1_700_000_100)],
    [encodeCbor(10), encodeCbor([1, CHUNKING.targetSize, CHUNKING.minSize, CHUNKING.maxSize])],
    [encodeCbor(13), encodeCbor("incremental")],
  ];
  return concatBytes([Uint8Array.of(0xa6), ...pairs.flat()]);
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

test("extension headers require a supported mode and reject a nested schema", async () => {
  for (const mode of [undefined, null, "", "differential", true, 1]) {
    const header = validExtensionHeaderMap();
    if (mode === undefined) header.delete(13);
    else header.set(13, mode);
    await assert.rejects(
      () =>
        decodeExtensionDocument(
          buildExtensionDocumentBytes({
            headerBytes: encodeCbor(header),
            bodyBytes: validExtensionBodyBytes(),
          }),
        ),
      /update mode|key 13 is required/,
    );
  }
  const unsupported = validExtensionHeaderMap();
  unsupported.set(1, 2);
  await assert.rejects(
    () =>
      decodeExtensionDocument(
        buildExtensionDocumentBytes({
          headerBytes: encodeCbor(unsupported),
          bodyBytes: validExtensionBodyBytes(),
        }),
      ),
    /unknown keys/,
  );
});

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
    const chunks = defaultExtensionChunker(vector.data, CHUNKING);
    assert.deepEqual(chunkOffsetsAndHashes(chunks), {
      offsets: vector.offsets,
      hashes: vector.hashes,
    });
  }
});

test("auth verification accepts signatures from the embedded root signing seed", async () => {
  const docHash = sha256(new TextEncoder().encode("ciphertext"));
  const signature = signAuthPayload(docHash, ROOT_SIGN_PUB, ROOT_SIGNING_SEED);

  assert.equal(await verifyAuthSignature(docHash, ROOT_SIGN_PUB, signature), true);
});

test("extension document rejects float-typed integer fields", async () => {
  const document = buildExtensionDocumentBytes({
    headerBytes: extensionHeaderWithIndexBytes(Uint8Array.of(0xf9, 0x3c, 0x00)),
    bodyBytes: validExtensionBodyBytes(),
  });

  await assert.rejects(
    () => decodeExtensionDocument(document),
    /extension header index must be an int/,
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
  const headerMissingMode = validExtensionHeaderMap();
  headerMissingMode.delete(13);
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
      headerBytes: encodeCbor(headerMissingMode),
      bodyBytes: validExtensionBodyBytes(),
      pattern: /extension header key 13 is required/,
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
    headerBytes: extensionHeaderWithIndexBytes(Uint8Array.of(0x18, 0x01)),
    bodyBytes: validExtensionBodyBytes(),
  });

  await assert.rejects(() => decodeExtensionDocument(overlongVersionDocument), /overlong varint/);
  await assert.rejects(
    () => decodeExtensionDocument(nondeterministicHeader),
    /deterministic CBOR encoding/,
  );
});

test("extension document rejects removed draft fields", async () => {
  for (const key of [1, 11, 12]) {
    const header = validExtensionHeaderMap();
    header.set(key, null);
    await assert.rejects(
      () =>
        decodeExtensionDocument(
          buildExtensionDocumentBytes({
            headerBytes: encodeCbor(header),
            bodyBytes: validExtensionBodyBytes(),
          }),
        ),
      /unknown keys/,
    );
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

  await assert.rejects(() => decodeExtensionDocument(document), /invalid gzip chunk/);
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

  assert.equal(documentCounts(state).authDuplicates, 0);
  assert.equal(documentCounts(state).authConflicts, 1);
  assert.equal(primaryDocumentRecord(state).authStatus, "conflicting auth payloads");
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

  assert.equal(documentCounts(state).authDuplicates, 0);
  assert.equal(documentCounts(state).authConflicts, 1);
  assert.equal(primaryDocumentRecord(state).authStatus, "conflicting auth payloads");
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
  assert.equal(documentCounts(state).conflicts, 0);
  assert.equal(documentCounts(state).authConflicts, 0);
  assert.equal(primaryDocumentRecord(state).mainFrames.size, 1);
  assert.equal(
    bytesToHex(primaryDocumentRecord(state).authPayload.docHash),
    bytesToHex(blake2b256(rootCiphertext)),
  );
});
