import {
  decodePayloadString,
  decodeZBase32,
  filterZBase32Lines,
  readUvarint,
  bytesEqual,
  bytesToHex,
  hexToBytes,
} from "../lib/encoding.js";
import { crc32 } from "../lib/crc32.js";
import { decodeCbor } from "../lib/cbor.js";
import { blake2b256 } from "../lib/blake2b.js";
import {
  FRAME_MAGIC,
  FRAME_TYPE_MAIN,
  FRAME_TYPE_AUTH,
  FRAME_TYPE_KEY,
  SHARD_VERSION,
  SHARD_KEY_PASSPHRASE,
  SHARD_KEY_SIGNING_SEED,
} from "./constants.js";
import { bumpError } from "./state/initial.js";

export function listMissing(total, framesMap) {
  const missing = [];
  for (let i = 0; i < total; i += 1) {
    if (!framesMap.has(i)) missing.push(i);
  }
  return missing.slice(0, 30);
}

export function decodeFrame(payload) {
  if (payload.length < FRAME_MAGIC.length + 4) {
    throw new Error("frame too short");
  }
  if (payload[0] !== FRAME_MAGIC[0] || payload[1] !== FRAME_MAGIC[1]) {
    throw new Error("bad magic");
  }
  let idx = 2;
  const versionRes = readUvarint(payload, idx);
  const version = versionRes.value;
  idx = versionRes.offset;
  if (idx >= payload.length) throw new Error("missing frame type");
  const frameType = payload[idx++];
  const docId = payload.slice(idx, idx + 16);
  if (docId.length !== 16) throw new Error("missing doc_id");
  idx += 16;
  const indexRes = readUvarint(payload, idx);
  const index = indexRes.value;
  idx = indexRes.offset;
  const totalRes = readUvarint(payload, idx);
  const total = totalRes.value;
  idx = totalRes.offset;
  const lenRes = readUvarint(payload, idx);
  const dataLen = lenRes.value;
  idx = lenRes.offset;
  if (idx + dataLen + 4 !== payload.length) {
    throw new Error("frame length mismatch");
  }
  const data = payload.slice(idx, idx + dataLen);
  idx += dataLen;
  const crcExpected = (
    (payload[idx] << 24) |
    (payload[idx + 1] << 16) |
    (payload[idx + 2] << 8) |
    payload[idx + 3]
  ) >>> 0;
  const crcActual = crc32(payload.slice(0, idx));
  if (crcExpected !== crcActual) {
    throw new Error("crc mismatch");
  }
  return { version, frameType, docId, index, total, data, raw: payload };
}

function decodeShardPayload(bytes) {
  const decoded = decodeCbor(bytes);
  if (!Array.isArray(decoded) || decoded.length < 10) {
    throw new Error("shard payload must be a list");
  }
  const [
    version,
    keyType,
    threshold,
    shares,
    index,
    secretLen,
    share,
    docHash,
    signPub,
    signature,
  ] = decoded;

  if (version !== SHARD_VERSION) {
    throw new Error(`unsupported shard payload version: ${version}`);
  }
  if (keyType !== SHARD_KEY_PASSPHRASE && keyType !== SHARD_KEY_SIGNING_SEED) {
    throw new Error(`unsupported shard key type: ${keyType}`);
  }
  if (!Number.isInteger(threshold) || threshold <= 0) {
    throw new Error("shard threshold must be a positive int");
  }
  if (!Number.isInteger(shares) || shares <= 0) {
    throw new Error("shard shares must be a positive int");
  }
  if (!Number.isInteger(index) || index <= 0) {
    throw new Error("shard index must be a positive int");
  }
  if (!Number.isInteger(secretLen) || secretLen <= 0) {
    throw new Error("shard secret length must be a positive int");
  }
  if (!(share instanceof Uint8Array) || !share.length) {
    throw new Error("shard share must be bytes");
  }
  if (!(docHash instanceof Uint8Array) || docHash.length !== 32) {
    throw new Error("shard doc_hash must be 32 bytes");
  }
  if (!(signPub instanceof Uint8Array) || signPub.length !== 32) {
    throw new Error("shard sign_pub must be 32 bytes");
  }
  if (!(signature instanceof Uint8Array) || signature.length !== 64) {
    throw new Error("shard signature must be 64 bytes");
  }
  return {
    version,
    keyType,
    threshold,
    shares,
    index,
    secretLen,
    share,
    docHash,
    signPub,
    signature,
  };
}

function decodeAuthPayload(bytes) {
  const decoded = decodeCbor(bytes);
  if (!Array.isArray(decoded) || decoded.length < 4) {
    throw new Error("auth payload must be a list");
  }
  const [version, docHash, signPub, signature] = decoded;
  if (version !== 1) {
    throw new Error(`unsupported auth version: ${version}`);
  }
  if (!(docHash instanceof Uint8Array) || docHash.length !== 32) {
    throw new Error("auth doc_hash must be 32 bytes");
  }
  if (!(signPub instanceof Uint8Array) || signPub.length !== 32) {
    throw new Error("auth sign_pub must be 32 bytes");
  }
  if (!(signature instanceof Uint8Array) || signature.length !== 64) {
    throw new Error("auth signature must be 64 bytes");
  }
  return { version, docHash, signPub, signature };
}

export function addFrame(state, frame) {
  if (frame.frameType === FRAME_TYPE_AUTH) {
    addAuthFrame(state, frame);
    return;
  }
  if (frame.frameType !== FRAME_TYPE_MAIN) {
    state.ignored += 1;
    return;
  }
  const docIdHex = bytesToHex(frame.docId);
  if (!state.docIdHex) {
    state.docIdHex = docIdHex;
  } else if (state.docIdHex !== docIdHex) {
    state.ignored += 1;
    return;
  }
  if (state.total === null) {
    state.total = frame.total;
  } else if (state.total !== frame.total) {
    state.conflicts += 1;
    return;
  }
  if (state.mainFrames.has(frame.index)) {
    const existing = state.mainFrames.get(frame.index);
    if (!bytesEqual(existing.data, frame.data) || existing.total !== frame.total) {
      state.conflicts += 1;
    } else {
      state.duplicates += 1;
    }
    return;
  }
  state.mainFrames.set(frame.index, frame);
  state.ciphertext = null;
  state.cipherDocHashHex = null;
}

function addAuthFrame(state, frame) {
  if (frame.frameType !== FRAME_TYPE_AUTH) {
    state.authErrors += 1;
    return;
  }
  if (frame.total !== 1 || frame.index !== 0) {
    state.authErrors += 1;
    return;
  }
  const docIdHex = bytesToHex(frame.docId);
  if (state.authDocIdHex && state.authDocIdHex !== docIdHex) {
    state.authConflicts += 1;
    return;
  }
  if (state.docIdHex && state.docIdHex !== docIdHex) {
    state.authConflicts += 1;
    return;
  }
  let payload;
  try {
    payload = decodeAuthPayload(frame.data);
  } catch (err) {
    state.authErrors += 1;
    state.authStatus = "invalid payload";
    return;
  }
  if (state.authPayload) {
    if (!bytesEqual(state.authPayload.signature, payload.signature)) {
      state.authConflicts += 1;
      state.authStatus = "conflicting auth payloads";
      return;
    }
    state.authDuplicates += 1;
    return;
  }
  state.authPayload = payload;
  state.authDocIdHex = docIdHex;
  state.authDocHashHex = bytesToHex(payload.docHash);
  state.authSignPubHex = bytesToHex(payload.signPub);
  state.authSignatureHex = bytesToHex(payload.signature);
  state.authStatus = "pending";
}

export function addShardFrame(state, frame) {
  if (frame.frameType !== FRAME_TYPE_KEY) {
    state.shardErrors += 1;
    return;
  }
  if (frame.total !== 1 || frame.index !== 0) {
    state.shardErrors += 1;
    return;
  }
  const docIdHex = bytesToHex(frame.docId);
  if (!state.shardDocIdHex) {
    state.shardDocIdHex = docIdHex;
  } else if (state.shardDocIdHex !== docIdHex) {
    state.shardConflicts += 1;
    return;
  }
  let payload;
  try {
    payload = decodeShardPayload(frame.data);
  } catch (err) {
    state.shardErrors += 1;
    return;
  }
  if (state.shardThreshold === null) {
    state.shardThreshold = payload.threshold;
    state.shardShares = payload.shares;
    state.shardKeyType = payload.keyType;
    state.shardSecretLen = payload.secretLen;
    state.shardDocHashHex = bytesToHex(payload.docHash);
    state.shardSignPubHex = bytesToHex(payload.signPub);
  } else {
    if (state.shardThreshold !== payload.threshold || state.shardShares !== payload.shares) {
      state.shardConflicts += 1;
      return;
    }
    if (state.shardKeyType !== payload.keyType || state.shardSecretLen !== payload.secretLen) {
      state.shardConflicts += 1;
      return;
    }
    if (state.shardDocHashHex !== bytesToHex(payload.docHash)) {
      state.shardConflicts += 1;
      return;
    }
    if (state.shardSignPubHex !== bytesToHex(payload.signPub)) {
      state.shardConflicts += 1;
      return;
    }
  }

  const existing = state.shardFrames.get(payload.index);
  if (existing) {
    if (!bytesEqual(existing.share, payload.share)) {
      state.shardConflicts += 1;
    } else {
      state.shardDuplicates += 1;
    }
    return;
  }
  state.shardFrames.set(payload.index, payload);
}

function parsePayloadLinesWith(state, text, addFrameFn, errorKey) {
  const lines = text.split(/\r?\n/);
  let added = 0;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const bytes = decodePayloadString(trimmed);
    if (!bytes) {
      bumpError(state, errorKey);
      continue;
    }
    try {
      const frame = decodeFrame(bytes);
      addFrameFn(state, frame);
      added += 1;
    } catch (err) {
      bumpError(state, errorKey);
    }
  }
  return added;
}

export function parsePayloadLines(state, text) {
  return parsePayloadLinesWith(state, text, addFrame, "errors");
}

function isFallbackText(text) {
  const lower = text.toLowerCase();
  if (lower.includes("main frame") || lower.includes("auth frame")) {
    return true;
  }
  const lines = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (!lines.length) return false;
  const filtered = filterZBase32Lines(text);
  return filtered.length > 0 && filtered.length === lines.length;
}

export function parseAutoPayload(state, text) {
  if (isFallbackText(text)) {
    return parseFallbackText(state, text);
  }
  return parsePayloadLines(state, text);
}

export function parseFallbackText(state, text) {
  const lines = text.split(/\r?\n/);
  const sections = { main: [], auth: [], any: [] };
  let current = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const lower = line.toLowerCase();
    if (lower.includes("main frame")) {
      current = "main";
      continue;
    }
    if (lower.includes("auth frame")) {
      current = "auth";
      continue;
    }
    if (current) {
      sections[current].push(line);
    } else {
      sections.any.push(line);
    }
  }
  const target = sections.main.length ? sections.main : sections.any;
  const filtered = filterZBase32Lines(target.join("\n"));
  if (!filtered.length) {
    throw new Error("no fallback lines found");
  }
  const bytes = decodeZBase32(filtered.join(""));
  const frame = decodeFrame(bytes);
  addFrame(state, frame);

  let added = 1;
  if (sections.auth.length) {
    try {
      const authLines = filterZBase32Lines(sections.auth.join("\n"));
      if (authLines.length) {
        const authBytes = decodeZBase32(authLines.join(""));
        const authFrame = decodeFrame(authBytes);
        addFrame(state, authFrame);
        added += 1;
      }
    } catch (err) {
      state.authErrors += 1;
    }
  }
  return added;
}

export function parseShardFallbackText(state, text) {
  const filtered = filterZBase32Lines(text);
  if (!filtered.length) {
    throw new Error("no shard fallback lines found");
  }
  const bytes = decodeZBase32(filtered.join(""));
  const frame = decodeFrame(bytes);
  addShardFrame(state, frame);
  return 1;
}

export function parseShardPayloadLines(state, text) {
  return parsePayloadLinesWith(state, text, addShardFrame, "shardErrors");
}

export function parseAutoShard(state, text) {
  if (isFallbackText(text)) {
    return parseShardFallbackText(state, text);
  }
  return parseShardPayloadLines(state, text);
}

export function reassembleCiphertext(state) {
  if (state.total === null || state.mainFrames.size !== state.total) {
    throw new Error("missing frames");
  }
  const chunks = [];
  for (let i = 0; i < state.total; i += 1) {
    const frame = state.mainFrames.get(i);
    if (!frame) throw new Error(`missing frame ${i}`);
    chunks.push(frame.data);
  }
  const totalLen = chunks.reduce((sum, arr) => sum + arr.length, 0);
  const out = new Uint8Array(totalLen);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

export function ensureCiphertextAndHash(state) {
  if (!state.total || state.mainFrames.size !== state.total) {
    return null;
  }
  if (!state.ciphertext) {
    state.ciphertext = reassembleCiphertext(state);
  }
  if (!state.cipherDocHashHex) {
    const hash = blake2b256(state.ciphertext);
    state.cipherDocHashHex = bytesToHex(hash);
    return hash;
  }
  return hexToBytes(state.cipherDocHashHex);
}

export function syncCollectedCiphertext(state) {
  if (state.total && state.mainFrames.size === state.total) {
    try {
      state.ciphertext = reassembleCiphertext(state);
    } catch (err) {
      // leave ciphertext unset if reassembly fails
    }
  }
}
