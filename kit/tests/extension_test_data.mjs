import assert from "node:assert/strict";
import { sha256 } from "@noble/hashes/sha2.js";
import {
  DOC_ID_LEN,
  DOCUMENT_MAGIC,
  DOCUMENT_VERSION,
  DOCUMENT_KIND_BACKUP,
  DOCUMENT_KIND_UPDATE,
  FRAME_TYPE_AUTH,
  FRAME_TYPE_MAIN,
} from "../app/constants.js";
import { deriveSigningPublicKey } from "../app/auth.js";
import { decodeExtensionDocumentHeader } from "../app/extensions/document.js";
import { defaultExtensionChunker } from "../app/extensions/chunking.js";
import { recoverLatestFromPlaintextDocuments as recoverPlaintextCore } from "../app/extensions/recovery.js";
import { readDocumentHeader } from "../app/document_header.js";
import { addFrame } from "../app/frames_apply.js";
import { decodeFrame } from "../app/frames_protocol.js";
import { encodeCbor } from "../lib/cbor.js";
import { blake2b256 } from "../lib/blake2b.js";
import { bytesToHex } from "../lib/bytes.js";
import {
  createStore as createTestStore,
  buildFrame,
  concatBytes,
  encodeUvarint,
} from "./protocol_test_data.mjs";

const CHUNKING = {
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
    created: 1_700_000_000,
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
  return buildDocument(DOCUMENT_KIND_BACKUP, encodeCbor(manifest), payload);
}

function buildExtensionPlaintext({
  index,
  parentDocHash,
  rootDocHash,
  files,
  chunking = CHUNKING,
  updateMode = "incremental",
}) {
  const chunksById = new Map();
  const fileEntries = files.map((file) => buildExtensionFileEntry(file, chunksById, chunking));
  const chunks = Array.from(chunksById.values())
    .sort((left, right) => left.chunkIdHex.localeCompare(right.chunkIdHex))
    .map((chunk) => [chunk.chunkId, 0, chunk.data.length, chunk.data]);
  const header = new Map([
    [2, index],
    [4, parentDocHash],
    [5, rootDocHash],
    [7, 1_700_000_100 + index],
    [10, [1, chunking.targetSize, chunking.minSize, chunking.maxSize]],
    [13, updateMode],
  ]);
  const body = new Map([
    [1, fileEntries],
    [2, chunks],
  ]);
  return buildDocument(DOCUMENT_KIND_UPDATE, encodeCbor(header), encodeCbor(body));
}

function buildExtensionDocumentBytes({ headerBytes = validExtensionHeaderBytes(), bodyBytes }) {
  return buildDocument(DOCUMENT_KIND_UPDATE, headerBytes, bodyBytes);
}

function validExtensionHeaderMap() {
  return new Map([
    [2, 1],
    [4, new Uint8Array(32).fill(1)],
    [5, new Uint8Array(32).fill(2)],
    [7, 1_700_000_100],
    [10, [1, CHUNKING.targetSize, CHUNKING.minSize, CHUNKING.maxSize]],
    [13, "incremental"],
  ]);
}

function validExtensionHeaderBytes() {
  return encodeCbor(validExtensionHeaderMap());
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

function buildDocument(kind, firstSection, secondSection) {
  return concatBytes([
    Uint8Array.from(DOCUMENT_MAGIC),
    encodeUvarint(DOCUMENT_VERSION),
    encodeUvarint(kind),
    encodeUvarint(firstSection.length),
    firstSection,
    encodeUvarint(secondSection.length),
    secondSection,
  ]);
}

function createStore() {
  return createTestStore({ freshnessUnknownAcknowledged: true });
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
      (document) => readDocumentHeader(document.plaintext).kind === DOCUMENT_KIND_BACKUP,
    );
    return {
      ...options,
      extensionTarget: { kind: "root", expectedHeadDocHashHex: root?.docHashHex },
    };
  }
  if (target?.kind === "index") {
    const selected = documents.find((document) => {
      if (readDocumentHeader(document.plaintext).kind !== DOCUMENT_KIND_UPDATE) return false;
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

export {
  CHUNKING,
  ROOT_DOC_ID,
  EXT1_DOC_ID,
  EXT2_DOC_ID,
  ROOT_SIGNING_SEED,
  ROOT_SIGN_PUB,
  OTHER_SIGN_PUB,
  SIGNATURE,
  buildRootPlaintext,
  buildExtensionPlaintext,
  buildExtensionDocumentBytes,
  validExtensionHeaderMap,
  validExtensionHeaderBytes,
  buildExtensionFileEntry,
  buildDocument,
  createStore,
  documentFromPlaintext,
  explicitPlaintextFreshness,
  recoverLatestFromPlaintextDocuments,
  addSingleFrameDocument,
  docIdForCiphertext,
  verifiedSignature,
};
