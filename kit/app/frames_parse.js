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

import { decodePayloadString, decodeZBase32, filterZBase32Lines } from "../lib/encoding.js";
import {
  FRAME_TYPE_KEY,
  MAX_FALLBACK_LINES,
  MAX_FALLBACK_NORMALIZED_CHARS,
  MAX_RECOVERY_TEXT_BYTES,
} from "./constants.js";
import { addFrame, addShardFrame } from "./frames_apply.js";
import { decodeFrame } from "./frames_protocol.js";
import { bumpError } from "./state/initial.js";

function getScannedText(input) {
  if (typeof input === "string") return input;
  if (input && typeof input === "object" && typeof input.text === "string") {
    return input.text;
  }
  return "";
}

function getScannedBytes(input) {
  if (!input || typeof input !== "object" || input instanceof Uint8Array) {
    return null;
  }
  const { bytes } = input;
  if (!bytes) return null;
  if (bytes instanceof Uint8Array) return bytes;
  try {
    return Uint8Array.from(bytes);
  } catch {
    return null;
  }
}

function nonEmptyLines(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function normalizeMarkerLine(line) {
  return line
    .trim()
    .replace(/^[=:\-\s]+|[=:\-\s]+$/g, "")
    .toLowerCase();
}

function detectMarker(line, markers) {
  const normalized = normalizeMarkerLine(line);
  return markers.find((marker) => normalized === marker) ?? null;
}

function hasMarker(lines, markers) {
  return lines.some((line) => detectMarker(line, markers));
}

function decodeFrameLines(lines, shardOnly) {
  const frames = [];
  for (const line of lines) {
    const bytes = decodePayloadString(line);
    if (!bytes) return null;
    try {
      const frame = decodeFrame(bytes);
      if (shardOnly && frame.frameType !== FRAME_TYPE_KEY) return null;
      frames.push(frame);
    } catch {
      return null;
    }
  }
  return frames;
}

function allLinesLookLikeFallback(lines) {
  if (!lines.length) return false;
  try {
    const filtered = filterZBase32Lines(lines.join("\n"));
    return filtered.length === lines.length;
  } catch {
    return false;
  }
}

function normalizedZbaseChars(lines) {
  let count = 0;
  for (const line of lines) {
    for (const ch of line) {
      if (ch === "-" || /\s/.test(ch)) continue;
      count += 1;
    }
  }
  return count;
}

function enforceFallbackLimits(lines, label) {
  if (lines.length > MAX_FALLBACK_LINES) {
    throw new Error(
      `${label} fallback exceeds MAX_FALLBACK_LINES (${MAX_FALLBACK_LINES}): ${lines.length} lines`,
    );
  }
  const normalizedChars = normalizedZbaseChars(lines);
  if (normalizedChars > MAX_FALLBACK_NORMALIZED_CHARS) {
    throw new Error(
      `${label} fallback exceeds MAX_FALLBACK_NORMALIZED_CHARS (${MAX_FALLBACK_NORMALIZED_CHARS}): ${normalizedChars} chars`,
    );
  }
}

function parseFallbackText(state, text) {
  const lines = text.split(/\r?\n/);
  const sections = { main: [], auth: [], any: [] };
  let current = null;
  let sawMarker = false;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const marker = detectMarker(line, ["main frame", "auth frame"]);
    if (marker === "main frame") {
      sawMarker = true;
      current = "main";
      continue;
    }
    if (marker === "auth frame") {
      sawMarker = true;
      current = "auth";
      continue;
    }
    if (current) {
      sections[current].push(line);
    } else {
      sections.any.push(line);
    }
  }
  if (sawMarker && sections.any.length) {
    throw new Error("unexpected content before the first marked fallback section");
  }
  const target = sections.main.length ? sections.main : sections.any;
  let added = 0;
  if (target.length) {
    const filtered = filterZBase32Lines(target.join("\n"));
    if (!filtered.length) {
      throw new Error("no fallback lines found");
    }
    enforceFallbackLimits(filtered, "main");
    const bytes = decodeZBase32(filtered.join(""));
    const frame = decodeFrame(bytes);
    added = addFrame(state, frame) ? 1 : 0;
  } else if (!sections.auth.length) {
    throw new Error("no fallback lines found");
  }
  if (sections.auth.length) {
    try {
      const authLines = filterZBase32Lines(sections.auth.join("\n"));
      if (authLines.length) {
        enforceFallbackLimits(authLines, "auth");
        const authBytes = decodeZBase32(authLines.join(""));
        const authFrame = decodeFrame(authBytes);
        if (addFrame(state, authFrame)) {
          added += 1;
        }
      }
    } catch {
      state.authParseErrors += 1;
    }
  }
  return added;
}

const SHARD_FALLBACK_MARKERS = ["key frame", "shard frame", "shard payload"];

function parseShardFallbackText(state, text) {
  const payloadLines = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    if (detectMarker(line, SHARD_FALLBACK_MARKERS)) {
      continue;
    }
    payloadLines.push(line);
  }
  const filtered = filterZBase32Lines(payloadLines.join("\n"));
  if (!filtered.length) {
    throw new Error("no shard fallback lines found");
  }
  enforceFallbackLimits(filtered, "shard");
  const bytes = decodeZBase32(filtered.join(""));
  const frame = decodeFrame(bytes);
  return addShardFrame(state, frame) ? 1 : 0;
}

function enforceRecoveryTextLimit(text) {
  const textBytes = new TextEncoder().encode(text).length;
  if (textBytes > MAX_RECOVERY_TEXT_BYTES) {
    throw new Error(
      `recovery text exceeds MAX_RECOVERY_TEXT_BYTES (${MAX_RECOVERY_TEXT_BYTES}): ${textBytes} bytes`,
    );
  }
}

const BACKUP_INPUT = {
  add: addFrame,
  fallback: parseFallbackText,
  markers: ["main frame", "auth frame"],
  errorKey: "errors",
  label: "QR",
  shardOnly: false,
};
const SHARD_INPUT = {
  add: addShardFrame,
  fallback: parseShardFallbackText,
  markers: SHARD_FALLBACK_MARKERS,
  errorKey: "shardErrors",
  label: "shard",
  shardOnly: true,
};

function parseAuto(state, text, input) {
  enforceRecoveryTextLimit(text);
  const lines = nonEmptyLines(text);
  if (!lines.length) throw new Error("no input lines found");
  if (hasMarker(lines, input.markers)) return input.fallback(state, text);
  const frames = decodeFrameLines(lines, input.shardOnly);
  if (frames !== null) {
    let added = 0;
    for (const frame of frames) {
      try {
        if (input.add(state, frame)) added += 1;
      } catch {
        bumpError(state, input.errorKey);
      }
    }
    return added;
  }
  if (allLinesLookLikeFallback(lines)) return input.fallback(state, text);
  throw new Error(`input is neither valid ${input.label} payloads nor valid fallback text`);
}

function parseScanned(state, scanned, input) {
  const text = getScannedText(scanned).trim();
  const bytes = getScannedBytes(scanned);
  if (bytes?.length) {
    try {
      const frame = decodeFrame(bytes);
      if (input.shardOnly && frame.frameType !== FRAME_TYPE_KEY) {
        bumpError(state, input.errorKey);
        return 0;
      }
      return input.add(state, frame) ? 1 : 0;
    } catch {
      // Some scanners return the ASCII bytes of a text-encoded QR.
    }
  }
  if (text) {
    try {
      return parseAuto(state, text, input);
    } catch {
      // Count one invalid scan regardless of which representation failed.
    }
  }
  bumpError(state, input.errorKey);
  return 0;
}

export function parseAutoPayload(state, text) {
  return parseAuto(state, text, BACKUP_INPUT);
}

export function parseAutoShard(state, text) {
  return parseAuto(state, text, SHARD_INPUT);
}

export function parseScannedPayload(state, scanned) {
  return parseScanned(state, scanned, BACKUP_INPUT);
}

export function parseScannedShard(state, scanned) {
  return parseScanned(state, scanned, SHARD_INPUT);
}

export { detectMarker };
