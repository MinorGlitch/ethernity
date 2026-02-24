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

import {
  decodePayloadString,
  decodeZBase32,
  filterZBase32Lines,
} from "../lib/encoding.js";
import { FRAME_TYPE_KEY, MAX_RECOVERY_TEXT_BYTES } from "./constants.js";
import { addFrame, addShardFrame } from "./frames_apply.js";
import { decodeFrame } from "./frames_protocol.js";
import { bumpError } from "./state/initial.js";

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
    } catch {
      bumpError(state, errorKey);
    }
  }
  return added;
}

function parsePayloadLines(state, text) {
  return parsePayloadLinesWith(state, text, addFrame, "errors");
}

function parseShardPayloadLines(state, text) {
  return parsePayloadLinesWith(state, text, addShardFrame, "shardErrors");
}

function nonEmptyLines(text) {
  return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

function hasMarker(lines, markers) {
  for (const line of lines) {
    const lower = line.toLowerCase();
    if (markers.some((marker) => lower.includes(marker))) {
      return true;
    }
  }
  return false;
}

function allLinesDecodeFrames(lines) {
  if (!lines.length) return false;
  for (const line of lines) {
    const bytes = decodePayloadString(line);
    if (!bytes) return false;
    try {
      decodeFrame(bytes);
    } catch {
      return false;
    }
  }
  return true;
}

function allLinesDecodeShardFrames(lines) {
  if (!lines.length) return false;
  for (const line of lines) {
    const bytes = decodePayloadString(line);
    if (!bytes) return false;
    try {
      const frame = decodeFrame(bytes);
      if (frame.frameType !== FRAME_TYPE_KEY) {
        return false;
      }
    } catch {
      return false;
    }
  }
  return true;
}

function allLinesLookLikeFallback(lines) {
  if (!lines.length) return false;
  const filtered = filterZBase32Lines(lines.join("\n"));
  return filtered.length === lines.length;
}

function parseFallbackText(state, text) {
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
    } catch {
      state.authErrors += 1;
    }
  }
  return added;
}

function parseShardFallbackText(state, text) {
  const filtered = filterZBase32Lines(text);
  if (!filtered.length) {
    throw new Error("no shard fallback lines found");
  }
  const bytes = decodeZBase32(filtered.join(""));
  const frame = decodeFrame(bytes);
  addShardFrame(state, frame);
  return 1;
}

function enforceRecoveryTextLimit(text) {
  const textBytes = new TextEncoder().encode(text).length;
  if (textBytes > MAX_RECOVERY_TEXT_BYTES) {
    throw new Error(
      `recovery text exceeds MAX_RECOVERY_TEXT_BYTES (${MAX_RECOVERY_TEXT_BYTES}): ${textBytes} bytes`
    );
  }
}

export function parseAutoPayload(state, text) {
  enforceRecoveryTextLimit(text);
  const lines = nonEmptyLines(text);
  if (!lines.length) {
    throw new Error("no input lines found");
  }
  if (hasMarker(lines, ["main frame", "auth frame"])) {
    return parseFallbackText(state, text);
  }
  if (allLinesDecodeFrames(lines)) {
    return parsePayloadLines(state, text);
  }
  if (allLinesLookLikeFallback(lines)) {
    return parseFallbackText(state, text);
  }
  throw new Error("input is neither valid QR payloads nor valid fallback text");
}

export function parseAutoShard(state, text) {
  enforceRecoveryTextLimit(text);
  const lines = nonEmptyLines(text);
  if (!lines.length) {
    throw new Error("no input lines found");
  }
  if (hasMarker(lines, ["shard frame", "shard payload"])) {
    return parseShardFallbackText(state, text);
  }
  if (allLinesDecodeShardFrames(lines)) {
    return parseShardPayloadLines(state, text);
  }
  if (allLinesLookLikeFallback(lines)) {
    return parseShardFallbackText(state, text);
  }
  throw new Error("input is neither valid shard payloads nor valid fallback text");
}
