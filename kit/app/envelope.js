import { decodeCbor } from "../lib/cbor.js";
import { readUvarint } from "../lib/encoding.js";
import { ENVELOPE_MAGIC } from "./constants.js";

export function decodeEnvelope(bytes) {
  if (bytes.length < 2) throw new Error("envelope too short");
  if (bytes[0] !== ENVELOPE_MAGIC[0] || bytes[1] !== ENVELOPE_MAGIC[1]) {
    throw new Error("invalid envelope magic");
  }
  let idx = 2;
  const versionRes = readUvarint(bytes, idx);
  const version = versionRes.value;
  idx = versionRes.offset;
  if (version !== 1) throw new Error(`unsupported envelope version: ${version}`);
  const manifestLenRes = readUvarint(bytes, idx);
  const manifestLen = manifestLenRes.value;
  idx = manifestLenRes.offset;
  const manifestEnd = idx + manifestLen;
  if (manifestEnd > bytes.length) throw new Error("truncated manifest");
  const manifestBytes = bytes.slice(idx, manifestEnd);
  idx = manifestEnd;
  const payloadLenRes = readUvarint(bytes, idx);
  const payloadLen = payloadLenRes.value;
  idx = payloadLenRes.offset;
  const payloadEnd = idx + payloadLen;
  if (payloadEnd !== bytes.length) throw new Error("payload length mismatch");
  const payload = bytes.slice(idx, payloadEnd);
  const manifest = decodeCbor(manifestBytes);
  return { manifest, payload };
}

export function parseManifest(manifest) {
  if (!Array.isArray(manifest) || manifest.length < 6) {
    throw new Error("manifest must be a list");
  }
  const formatVersion = manifest[0];
  if (formatVersion !== 5) {
    throw new Error(`unsupported manifest version: ${formatVersion}`);
  }
  const createdAt = manifest[1];
  const sealed = manifest[2];
  const signingSeed = manifest[3];
  const prefixes = manifest[4];
  const files = manifest[5];
  if (signingSeed !== null && !(signingSeed instanceof Uint8Array)) {
    throw new Error("manifest signing_seed must be bytes or null");
  }
  if (!Array.isArray(prefixes) || !Array.isArray(files)) {
    throw new Error("invalid manifest structure");
  }
  const entries = [];
  for (const entry of files) {
    if (!Array.isArray(entry) || entry.length < 5) continue;
    const prefixIdx = entry[0];
    const suffix = entry[1];
    const size = entry[2];
    const sha = entry[3];
    const mtime = entry[4];
    const prefix = prefixes[prefixIdx] || "";
    const path = prefix ? `${prefix}/${suffix}` : suffix;
    entries.push({ path, size, sha, mtime });
  }
  return { formatVersion, createdAt, sealed, signingSeed, entries };
}

export function extractFiles(envelopeBytes) {
  const { manifest, payload } = decodeEnvelope(envelopeBytes);
  const parsed = parseManifest(manifest);
  const files = [];
  let offset = 0;
  for (const entry of parsed.entries) {
    const end = offset + entry.size;
    if (end > payload.length) throw new Error("payload shorter than manifest");
    const data = payload.slice(offset, end);
    files.push({ path: entry.path, data });
    offset = end;
  }
  if (offset !== payload.length) {
    throw new Error("payload length does not match manifest sizes");
  }
  return { files, manifest: parsed };
}
