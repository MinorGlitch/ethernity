import assert from "node:assert/strict";
import test from "node:test";
import { sha256 } from "@noble/hashes/sha2.js";
import { encodeCbor } from "../lib/cbor.js";
import { bytesToHex, concatByteParts } from "../lib/bytes.js";
import {
  MAX_DECOMPRESSED_PAYLOAD_BYTES,
  MAX_RECOVERY_DECODED_CHUNK_BYTES,
  textEncoder,
} from "../app/constants.js";
import {
  decodeExtensionDocument,
  decodeExtensionDocumentHeader,
  reconstructLatestFilesFromDocuments,
} from "../app/extensions/document.js";
import {
  CHUNKING,
  buildExtensionPlaintext,
  buildExtensionDocumentBytes,
  validExtensionHeaderMap,
} from "./extension_test_data.mjs";

for (const failure of ["profile", "hash", "reference length"]) {
  test(`extension replay rejects an invalid ${failure} after chunk decoding`, async () => {
    const root = new Uint8Array(32).fill(2);
    const header = validExtensionHeaderMap();
    header.set(4, root);
    const parts = [Uint8Array.of(1, 2), Uint8Array.of(3, 4)];
    const data = concatByteParts(parts);
    const chunks = failure === "profile" ? parts : [data];
    const refs = chunks.map((chunk) => [sha256(chunk), chunk.length]);
    if (failure === "reference length") refs[0][1] += 1;
    const body = new Map([
      [
        1,
        [
          [
            "file",
            refs.reduce((n, ref) => n + ref[1], 0),
            failure === "hash" ? new Uint8Array(32) : sha256(data),
            null,
            refs,
          ],
        ],
      ],
      [
        2,
        chunks
          .map((chunk) => [sha256(chunk), 0, chunk.length, chunk])
          .sort((a, b) => bytesToHex(a[0]).localeCompare(bytesToHex(b[0]))),
      ],
    ]);
    const plaintext = buildExtensionDocumentBytes({
      headerBytes: encodeCbor(header),
      bodyBytes: encodeCbor(body),
    });
    await assert.rejects(
      () =>
        reconstructLatestFilesFromDocuments([], root, [
          {
            plaintext,
            header: decodeExtensionDocumentHeader(plaintext),
            docHash: new Uint8Array(32).fill(3),
          },
        ]),
      failure === "profile"
        ? /locked chunking profile/
        : failure === "hash"
          ? /sha256 mismatch/
          : /length does not match/,
    );
  });
}

test("cumulative replay cannot borrow earlier chunks or retain an earlier file state", async () => {
  const rootHash = new Uint8Array(32).fill(1);
  const data = textEncoder.encode("added data");
  const decode = async (index, files, updateMode = "cumulative") => {
    const plaintext = buildExtensionPlaintext({
      index,
      parentDocHash: rootHash,
      rootDocHash: rootHash,
      files,
      updateMode,
    });
    return {
      plaintext,
      header: decodeExtensionDocumentHeader(plaintext),
      docHash: new Uint8Array(32).fill(index + 1),
    };
  };
  const first = await decode(1, [{ path: "added", data }]);
  const unresolved = await decode(3, [{ path: "added", data, inline: false }]);
  await assert.rejects(
    () => reconstructLatestFilesFromDocuments([], rootHash, [first, unresolved]),
    /unresolved/,
  );
  const reverted = await decode(3, []);
  assert.deepEqual(await reconstructLatestFilesFromDocuments([], rootHash, [first, reverted]), []);
  const mixed = await decode(2, [{ path: "next", data }], "incremental");
  await assert.rejects(
    () => reconstructLatestFilesFromDocuments([], rootHash, [first, mixed]),
    /update mode/,
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

test("browser replay counts unchanged root files in latest-state byte limit", async () => {
  const rootDocHash = new Uint8Array(32).fill(0x9a);
  const rootData = new Uint8Array(MAX_DECOMPRESSED_PAYLOAD_BYTES);
  const extPlaintext = buildExtensionPlaintext({
    index: 1,
    parentDocHash: rootDocHash,
    rootDocHash,
    files: [{ path: "added.txt", data: Uint8Array.of(1) }],
  });
  const extension = {
    plaintext: extPlaintext,
    header: decodeExtensionDocumentHeader(extPlaintext),
    docHash: new Uint8Array(32).fill(0x9b),
  };

  await assert.rejects(
    () =>
      reconstructLatestFilesFromDocuments([{ path: "root.bin", data: rootData }], rootDocHash, [
        extension,
      ]),
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
    () =>
      reconstructLatestFilesFromDocuments([], rootDocHash, [extension], {
        decodeDocument: async () => extension,
      }),
    /logical latest state exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES/,
  );
});
