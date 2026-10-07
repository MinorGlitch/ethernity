/*
 * Copyright (C) 2026 Alex Stoyanov
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.
 */

import { RecoveryError } from "../../lib/errors.js";

const DOC_HASH_PATTERN = /^[0-9a-f]{64}$/;

export function normalizeExpectedHeadDocHash(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const hash = text.toLowerCase();
  if (!DOC_HASH_PATTERN.test(hash)) {
    throw new RecoveryError(
      "RECOVERY_TARGET_INVALID",
      "expected head doc hash must be 64 hex characters",
    );
  }
  return hash;
}

export function normalizeExtensionTarget(value, expectedHeadValue = null) {
  const expectedHeadDocHashHex = normalizeExpectedHeadDocHash(expectedHeadValue);
  let target;

  if (value === undefined || value === null || value === "") {
    target = { kind: "latest" };
  } else if (typeof value === "string") {
    target = targetFromText(value);
  } else if (value === 0) {
    target = { kind: "root" };
  } else if (Number.isInteger(value) && value > 0) {
    target = { kind: "index", index: value };
  } else if (typeof value === "object") {
    target = targetFromObject(value);
  } else {
    throw invalidTargetError();
  }

  return attachExpectedHead(target, expectedHeadDocHashHex);
}

export function inspectExtensionTarget(
  value,
  expectedHeadValue = null,
  freshnessUnknownAcknowledged = false,
) {
  try {
    const target = normalizeExtensionTarget(value, expectedHeadValue);
    try {
      return {
        target,
        decision: requireFreshnessDecision(target, freshnessUnknownAcknowledged),
        error: null,
      };
    } catch (error) {
      return { target, decision: null, error };
    }
  } catch (error) {
    return { target: null, decision: null, error };
  }
}

export function isLatestExtensionTarget(target) {
  return target?.kind === "latest";
}

function targetFromText(value) {
  const text = value.trim();
  const lower = text.toLowerCase();
  if (!text || lower === "latest") return { kind: "latest" };
  if (lower === "root" || text === "0") return { kind: "root" };

  const latestMatch = text.match(/^latest:([0-9a-fA-F]{64})$/);
  if (latestMatch) {
    return { kind: "latest", expectedHeadDocHashHex: latestMatch[1].toLowerCase() };
  }
  if (/^[1-9]\d*$/.test(text)) {
    return { kind: "index", index: Number.parseInt(text, 10) };
  }
  if (DOC_HASH_PATTERN.test(lower)) {
    return { kind: "doc_hash", docHashHex: lower };
  }
  throw invalidTargetError();
}

function targetFromObject(value) {
  const expectedHeadDocHashHex = normalizeExpectedHeadDocHash(value.expectedHeadDocHashHex);
  let target;
  if (value.kind === "latest") {
    target = { kind: "latest" };
  } else if (value.kind === "root") {
    target = { kind: "root" };
  } else if (value.kind === "index") {
    if (!Number.isInteger(value.index) || value.index < 0) {
      throw new RecoveryError(
        "RECOVERY_TARGET_INVALID",
        "extension index target must be a non-negative integer",
      );
    }
    target = value.index === 0 ? { kind: "root" } : { kind: "index", index: value.index };
  } else if (value.kind === "doc_hash") {
    const docHashHex = String(value.docHashHex ?? "").toLowerCase();
    if (!DOC_HASH_PATTERN.test(docHashHex)) {
      throw new RecoveryError(
        "RECOVERY_TARGET_INVALID",
        "extension doc_hash target must be 64 hex characters",
      );
    }
    target = { kind: "doc_hash", docHashHex };
  } else {
    throw invalidTargetError();
  }
  return attachExpectedHead(target, expectedHeadDocHashHex);
}

function attachExpectedHead(target, expectedHeadDocHashHex) {
  if (!expectedHeadDocHashHex) return target;
  if (target.expectedHeadDocHashHex && target.expectedHeadDocHashHex !== expectedHeadDocHashHex) {
    throw new RecoveryError(
      "RECOVERY_TARGET_INVALID",
      "expected head doc hash conflicts with extension recovery target",
    );
  }
  return { ...target, expectedHeadDocHashHex };
}

function invalidTargetError() {
  return new RecoveryError(
    "RECOVERY_TARGET_INVALID",
    "extension target must be latest, latest:<doc hash>, root, an extension index, or a doc hash",
  );
}

export function requireFreshnessDecision(target, freshnessUnknownAcknowledged) {
  if (target.expectedHeadDocHashHex || target.kind === "doc_hash") {
    return "manual_expected_head";
  }
  if (target.kind === "latest" && freshnessUnknownAcknowledged === true) {
    return "supplied_pages_freshness_unknown";
  }
  if (target.kind === "latest") {
    throw new RecoveryError(
      "RECOVERY_TARGET_INVALID",
      "latest recovery requires an expected head hash or explicit freshness-unknown acknowledgement",
    );
  }
  throw new RecoveryError(
    "RECOVERY_TARGET_INVALID",
    "selected recovery target requires an expected head hash",
  );
}
