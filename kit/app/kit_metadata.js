/*
 * Copyright (C) 2026 Alex Stoyanov
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

import { SUPPORTED_DOCUMENT_VERSIONS } from "./constants.js";

export function readEmbeddedKitMetadata() {
  const value = globalThis.__ETHERNITY_KIT_METADATA__;
  if (!value || typeof value !== "object") return null;
  if (value.version !== 1) throw new Error("unsupported recovery kit metadata version");
  for (const version of SUPPORTED_DOCUMENT_VERSIONS) {
    requireSupportedVersion(value.supported_document_versions, version, "document");
  }
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
