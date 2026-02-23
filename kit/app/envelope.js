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

import { decodeCanonicalCbor } from "../lib/cbor.js";
import { bytesEqual, readUvarint } from "../lib/encoding.js";
import { validateManifestPath } from "../lib/path_validation.js";
import {
  ENVELOPE_MAGIC,
  ENVELOPE_VERSION,
  MANIFEST_VERSION,
  MAX_MANIFEST_CBOR_BYTES,
  MAX_MANIFEST_FILES,
  PATH_ENCODING_DIRECT,
  PATH_ENCODING_PREFIX_TABLE,
} from "./constants.js";

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
  if (manifestLen > MAX_MANIFEST_CBOR_BYTES) {
    throw new Error(
      `manifest exceeds MAX_MANIFEST_CBOR_BYTES (${MAX_MANIFEST_CBOR_BYTES}): ${manifestLen} bytes`
    );
  }

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

  const manifest = decodeCanonicalCbor(manifestBytes, "manifest");
  return { manifest, payload };
}

function parseManifest(manifest) {
  if (manifest === null || typeof manifest !== "object" || Array.isArray(manifest)) {
    throw new Error("manifest must be a map");
  }
  for (const key of [
    "version",
    "created",
    "sealed",
    "seed",
    "input_origin",
    "input_roots",
    "path_encoding",
    "files",
  ]) {
    if (!(key in manifest)) {
      throw new Error(`manifest ${key} is required`);
    }
  }

  const formatVersion = manifest.version;
  if (!Number.isInteger(formatVersion)) {
    throw new Error("manifest version must be an int");
  }
  if (formatVersion !== MANIFEST_VERSION) {
    throw new Error(`unsupported manifest version: ${formatVersion}`);
  }

  const createdAt = manifest.created;
  if (typeof createdAt !== "number" || !Number.isFinite(createdAt)) {
    throw new Error("manifest created must be a number");
  }

  const sealed = manifest.sealed;
  if (typeof sealed !== "boolean") {
    throw new Error("manifest sealed must be a boolean");
  }

  const signingSeed = manifest.seed;
  if (sealed) {
    if (signingSeed !== null) {
      throw new Error("manifest seed must be null for sealed manifests");
    }
  } else if (!(signingSeed instanceof Uint8Array) || signingSeed.length !== 32) {
    throw new Error("manifest seed must be 32 bytes for unsealed manifests");
  }

  const inputOrigin = manifest.input_origin;
  if (typeof inputOrigin !== "string") {
    throw new Error("manifest input_origin must be a string");
  }
  if (inputOrigin !== "file" && inputOrigin !== "directory" && inputOrigin !== "mixed") {
    throw new Error("manifest input_origin must be one of: file, directory, mixed");
  }

  const inputRootsRaw = manifest.input_roots;
  if (!Array.isArray(inputRootsRaw)) {
    throw new Error("manifest input_roots must be a list");
  }
  const inputRoots = inputRootsRaw.map(normalizeRootLabel);
  if (inputOrigin === "file" && inputRoots.length > 0) {
    throw new Error("manifest input_roots must be empty when input_origin is file");
  }
  if ((inputOrigin === "directory" || inputOrigin === "mixed") && inputRoots.length === 0) {
    throw new Error("manifest input_roots must be non-empty for directory or mixed input");
  }

  const pathEncoding = manifest.path_encoding;
  if (typeof pathEncoding !== "string") {
    throw new Error("manifest path_encoding must be a string");
  }
  if (pathEncoding !== PATH_ENCODING_DIRECT && pathEncoding !== PATH_ENCODING_PREFIX_TABLE) {
    throw new Error("manifest path_encoding must be one of: direct, prefix_table");
  }

  const files = manifest.files;
  if (!Array.isArray(files) || files.length === 0) {
    throw new Error("manifest files are required");
  }
  if (files.length > MAX_MANIFEST_FILES) {
    throw new Error(
      `manifest files exceed MAX_MANIFEST_FILES (${MAX_MANIFEST_FILES}): ${files.length} entries`
    );
  }

  let pathPrefixes = null;
  if (pathEncoding === PATH_ENCODING_PREFIX_TABLE) {
    if (!("path_prefixes" in manifest)) {
      throw new Error("manifest path_prefixes is required for prefix_table encoding");
    }
    pathPrefixes = validatePathPrefixes(manifest.path_prefixes);
  }

  const entries = [];
  const seenPaths = new Set();
  for (const fileEntry of files) {
    const parsedEntry =
      pathEncoding === PATH_ENCODING_DIRECT
        ? parseDirectEntry(fileEntry)
        : parsePrefixEntry(fileEntry, pathPrefixes);
    if (seenPaths.has(parsedEntry.path)) {
      throw new Error(`duplicate manifest file path: ${parsedEntry.path}`);
    }
    seenPaths.add(parsedEntry.path);
    entries.push(parsedEntry);
  }

  return {
    formatVersion,
    createdAt,
    sealed,
    signingSeed,
    inputOrigin,
    inputRoots,
    pathEncoding,
    entries,
  };
}

function normalizeRootLabel(root) {
  if (typeof root !== "string") {
    throw new Error("manifest input_root must be a non-empty string");
  }
  const normalized = root.normalize("NFC").trim();
  if (!normalized) {
    throw new Error("manifest input_root must be a non-empty string");
  }
  if (normalized.includes("/") || normalized.includes("\\")) {
    throw new Error("manifest input_root must be a leaf label without path separators");
  }
  return normalized;
}

function validatePathPrefixes(value) {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error("manifest path_prefixes must be a non-empty list");
  }
  if (value[0] !== "") {
    throw new Error("manifest path_prefixes must start with empty string");
  }
  const prefixes = [];
  const seen = new Set();
  for (let idx = 0; idx < value.length; idx += 1) {
    const prefix = value[idx];
    if (typeof prefix !== "string") {
      throw new Error("manifest path_prefixes values must be strings");
    }
    const normalized = idx === 0 ? "" : validateManifestPath(prefix, "manifest path_prefix");
    if (seen.has(normalized)) {
      throw new Error("manifest path_prefixes must be unique");
    }
    seen.add(normalized);
    prefixes.push(normalized);
  }
  return prefixes;
}

function parseDirectEntry(entry) {
  if (entry !== null && typeof entry === "object" && !Array.isArray(entry)) {
    throw new Error("manifest file entry must use array encoding");
  }
  if (!Array.isArray(entry)) {
    throw new Error("manifest file entry must be an array");
  }
  if (entry.length !== 4) {
    throw new Error("manifest file entry must contain exactly 4 values");
  }
  return buildManifestEntry({
    path: entry[0],
    size: entry[1],
    sha: entry[2],
    mtime: entry[3],
  });
}

function parsePrefixEntry(entry, pathPrefixes) {
  if (entry !== null && typeof entry === "object" && !Array.isArray(entry)) {
    throw new Error("manifest file entry must use array encoding");
  }
  if (!Array.isArray(entry)) {
    throw new Error("manifest file entry must be an array");
  }
  if (entry.length !== 5) {
    throw new Error("manifest file entry must contain exactly 5 values");
  }
  const prefixIndex = entry[0];
  const suffix = entry[1];
  if (!Number.isInteger(prefixIndex)) {
    throw new Error("manifest file prefix_index must be an int");
  }
  if (prefixIndex < 0 || prefixIndex >= pathPrefixes.length) {
    throw new Error("manifest file prefix_index out of range");
  }
  if (typeof suffix !== "string" || !suffix) {
    throw new Error("manifest file suffix must be a non-empty string");
  }
  const prefix = pathPrefixes[prefixIndex];
  const path = prefix ? `${prefix}/${suffix}` : suffix;
  return buildManifestEntry({ path, size: entry[2], sha: entry[3], mtime: entry[4] });
}

function buildManifestEntry({ path, size, sha, mtime }) {
  const normalizedPath = validateManifestPath(path, "manifest file path");
  if (!Number.isInteger(size) || size < 0) {
    throw new Error("manifest file size must be a non-negative int");
  }
  if (!(sha instanceof Uint8Array) || sha.length !== 32) {
    throw new Error("manifest file hash must be 32 bytes");
  }
  if (mtime !== null && !Number.isInteger(mtime)) {
    throw new Error("manifest file mtime must be an int");
  }
  return { path: normalizedPath, size, sha, mtime };
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
