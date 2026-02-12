/*
 * Copyright (C) 2026 Alex Stoyanov
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along with this program.
 * If not, see <https://www.gnu.org/licenses/>.
 */

import { sha256 } from "@noble/hashes/sha2.js";

import { decodeCbor } from "../lib/cbor.js";
import { bytesEqual, readUvarint } from "../lib/encoding.js";
import { ENVELOPE_MAGIC, ENVELOPE_VERSION, MANIFEST_VERSION } from "./constants.js";

function decodeEnvelope(bytes) {
  if (bytes.length < 2) throw new Error("envelope too short");
  if (bytes[0] !== ENVELOPE_MAGIC[0] || bytes[1] !== ENVELOPE_MAGIC[1]) {
    throw new Error("invalid envelope magic");
  }
  let idx = 2;
  const versionRes = readUvarint(bytes, idx);
  const version = versionRes.value;
  idx = versionRes.offset;
  if (version !== ENVELOPE_VERSION) throw new Error(`unsupported envelope version: ${version}`);
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

function parseManifest(manifest) {
  if (manifest === null || typeof manifest !== "object" || Array.isArray(manifest)) {
    throw new Error("manifest must be a map");
  }
  for (const key of ["version", "created", "sealed", "seed", "files"]) {
    if (!(key in manifest)) {
      throw new Error(`manifest ${key} is required`);
    }
  }
  const formatVersion = manifest.version;
  if (formatVersion !== MANIFEST_VERSION) {
    throw new Error(`unsupported manifest version: ${formatVersion}`);
  }
  const createdAt = manifest.created;
  const sealed = manifest.sealed;
  const signingSeed = manifest.seed;
  const files = manifest.files;
  if (typeof createdAt !== "number" || !Number.isFinite(createdAt)) {
    throw new Error("manifest created must be a number");
  }
  if (typeof sealed !== "boolean") {
    throw new Error("manifest sealed must be a boolean");
  }
  if (sealed) {
    if (signingSeed !== null) {
      throw new Error("manifest signing_seed must be null for sealed manifests");
    }
  } else {
    if (!(signingSeed instanceof Uint8Array) || signingSeed.length !== 32) {
      throw new Error("manifest signing_seed must be 32 bytes for unsealed manifests");
    }
  }
  if (!Array.isArray(files)) {
    throw new Error("invalid manifest structure");
  }
  if (!files.length) {
    throw new Error("manifest files are required");
  }
  const entries = [];
  const seenPaths = new Set();
  for (const entry of files) {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error("manifest file entry must be a map");
    }
    for (const key of ["path", "size", "hash", "mtime"]) {
      if (!(key in entry)) {
        throw new Error(`manifest file entry ${key} is required`);
      }
    }
    const path = entry.path;
    const size = entry.size;
    const sha = entry.hash;
    const mtime = entry.mtime;
    if (typeof path !== "string" || !path) {
      throw new Error("manifest file path must be a non-empty string");
    }
    if (!Number.isInteger(size) || size < 0) {
      throw new Error("manifest file size must be a non-negative int");
    }
    if (!(sha instanceof Uint8Array) || sha.length !== 32) {
      throw new Error("manifest file hash must be 32 bytes");
    }
    if (mtime !== null && !Number.isInteger(mtime)) {
      throw new Error("manifest file mtime must be an int");
    }
    const normalizedPath = path.normalize("NFC");
    if (seenPaths.has(normalizedPath)) {
      throw new Error(`duplicate manifest file path: ${path}`);
    }
    seenPaths.add(normalizedPath);
    entries.push({ path: normalizedPath, size, sha, mtime });
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
    const digest = sha256(data);
    if (!bytesEqual(digest, entry.sha)) {
      throw new Error(`sha256 mismatch for ${entry.path}`);
    }
    files.push({ path: entry.path, data });
    offset = end;
  }
  if (offset !== payload.length) {
    throw new Error("payload length does not match manifest sizes");
  }
  return { files, manifest: parsed };
}
