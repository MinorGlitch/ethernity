import { createInitialState } from "../app/state/initial.js";
import { reducer } from "../app/state/reducer.js";
import { AUTH_DOMAIN, AUTH_VERSION, textEncoder } from "../app/constants.js";
import { encodeCbor } from "../lib/cbor.js";
import { signSigningMessage } from "../lib/ed25519.js";
import { getOrCreateDocumentRecord } from "../app/documents/store.js";
import { blake2b256 } from "../lib/blake2b.js";
import { DOC_ID_LEN, FRAME_MAGIC, FRAME_VERSION } from "../app/constants.js";
import { concatByteParts as concatBytes } from "../lib/bytes.js";
import { crc32 } from "../lib/crc32.js";
import { encodeUvarint } from "../lib/encoding.js";

const ZBASE32_ALPHABET = "ybndrfg8ejkmcpqxot1uwisza345h769";

export function ensureAtob() {
  if (typeof globalThis.atob !== "function") {
    globalThis.atob = (value) => Buffer.from(value, "base64").toString("binary");
  }
}

export { encodeUvarint };
export { concatBytes };

export function toUnpaddedBase64(bytes) {
  return Buffer.from(bytes).toString("base64").replace(/=+$/u, "");
}

export function encodeZBase32(bytes) {
  let bits = 0;
  let bitCount = 0;
  let out = "";
  for (const byte of bytes) {
    bits = bits * 256 + byte;
    bitCount += 8;
    while (bitCount >= 5) {
      const shift = bitCount - 5;
      const idx = Math.floor(bits / 2 ** shift) & 0x1f;
      out += ZBASE32_ALPHABET[idx];
      bitCount -= 5;
      bits &= 2 ** bitCount - 1;
    }
  }
  if (bitCount > 0) {
    out += ZBASE32_ALPHABET[(bits * 2 ** (5 - bitCount)) & 0x1f];
  }
  return out;
}

export function buildFrame({
  frameType,
  data,
  index = 0,
  total = 1,
  docId = Uint8Array.from(Array.from({ length: DOC_ID_LEN }, (_, idx) => idx + 1)),
}) {
  const body = concatBytes([
    Uint8Array.from(FRAME_MAGIC),
    encodeUvarint(FRAME_VERSION),
    Uint8Array.of(frameType),
    docId,
    encodeUvarint(index),
    encodeUvarint(total),
    encodeUvarint(data.length),
    data,
  ]);
  const crc = crc32(body);
  return concatBytes([
    body,
    Uint8Array.of((crc >>> 24) & 0xff, (crc >>> 16) & 0xff, (crc >>> 8) & 0xff, crc & 0xff),
  ]);
}

export function mutateFrameCrc(frame) {
  const out = frame.slice();
  out[out.length - 1] ^= 0x01;
  return out;
}

// Synthetic records for tests of recovery gates and mutable-state isolation.
export function createTestDocument(state, ciphertext = Uint8Array.of(1, 2, 3)) {
  const record = getOrCreateDocumentRecord(state, blake2b256(ciphertext).slice(0, 8));
  state.primaryDocIdHex = record.docIdHex;
  return record;
}

export function createTestShardSet(state) {
  const record = {
    docId: new Uint8Array(8),
    docIdHex: null,
    docHashHex: null,
    shardFrames: new Map(),
    duplicates: 0,
    conflicts: 0,
  };
  state.shardSets.set("test", record);
  state.activeShardSetKey = "test";
  return record;
}

export function createStore(initial = {}) {
  let state = Object.assign(createInitialState(), initial);
  return {
    dispatch(action) {
      state = reducer(state, action);
    },
    getState() {
      return state;
    },
  };
}

export function signAuthPayload(docHash, signPub, signingSeed) {
  const signed = encodeCbor({ version: AUTH_VERSION, hash: docHash, pub: signPub });
  return signSigningMessage(concatBytes([textEncoder.encode(AUTH_DOMAIN), signed]), signingSeed);
}
