/*
 * Copyright (C) 2026 Alex Stoyanov
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

import { EXTENSION_ENVELOPE_VERSION, EXTENSION_SCHEMA_VERSION } from "./constants.js";

const HASH_HEX = /^[0-9a-f]{64}$/u;

export function readEmbeddedKitMetadata() {
  const value = globalThis.__ETHERNITY_KIT_METADATA__;
  if (!value || typeof value !== "object") return null;
  if (value.version !== 1) throw new Error("unsupported recovery kit metadata version");
  requireSupportedVersion(
    value.supported_extension_envelope_versions,
    EXTENSION_ENVELOPE_VERSION,
    "extension envelope",
  );
  requireSupportedVersion(
    value.supported_extension_schema_versions,
    EXTENSION_SCHEMA_VERSION,
    "extension schema",
  );
  if (value.capability === "ethernity-unanchored-rescue") {
    return { capability: value.capability, version: value.version, anchored: false };
  }
  if (value.capability !== "ethernity-chain-bound-recovery") {
    throw new Error("unsupported recovery kit capability");
  }
  return {
    capability: value.capability,
    version: value.version,
    anchored: true,
    rootDocumentHashHex: requireHash(value.root_document_hash, "root document hash"),
    rootSigningPublicKeyFingerprintHex: requireHash(
      value.root_signing_public_key_fingerprint,
      "root signing public key fingerprint",
    ),
    expectedLatestHeadHashHex: requireHash(
      value.expected_latest_head_hash,
      "expected latest head hash",
    ),
  };
}

function requireSupportedVersion(values, expected, label) {
  if (!Array.isArray(values) || !values.includes(expected)) {
    throw new Error(`recovery kit does not support ${label} version ${expected}`);
  }
}

function requireHash(value, label) {
  const normalized = String(value ?? "").toLowerCase();
  if (!HASH_HEX.test(normalized)) throw new Error(`${label} must be 64 hex characters`);
  return normalized;
}
