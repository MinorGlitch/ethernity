/*
 * Copyright (C) 2026 Alex Stoyanov
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

import { EXTENSION_DOCUMENT_VERSION, EXTENSION_SCHEMA_VERSION } from "./constants.js";

export function readEmbeddedKitMetadata() {
  const value = globalThis.__ETHERNITY_KIT_METADATA__;
  if (!value || typeof value !== "object") return null;
  if (value.version !== 1) throw new Error("unsupported recovery kit metadata version");
  requireSupportedVersion(
    value.supported_extension_envelope_versions,
    EXTENSION_DOCUMENT_VERSION,
    "extension document",
  );
  requireSupportedVersion(
    value.supported_extension_schema_versions,
    EXTENSION_SCHEMA_VERSION,
    "extension schema",
  );
  if (value.capability !== "ethernity-unanchored-rescue") {
    throw new Error("unsupported recovery kit capability");
  }
  return { capability: value.capability, version: value.version };
}

function requireSupportedVersion(values, expected, label) {
  if (!Array.isArray(values) || !values.includes(expected)) {
    throw new Error(`recovery kit does not support ${label} version ${expected}`);
  }
}
