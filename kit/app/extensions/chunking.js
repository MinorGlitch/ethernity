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

const ROLLING_HASH_MASK = (1n << 64n) - 1n;
const ROLLING_WINDOW_SIZE = 64;
const MIN_MASK_BITS = 4;
const GEAR_TABLE = buildGearTable();

export function canonicalChunkRefsForBytes(data, chunking) {
  return defaultExtensionChunker(data, chunking).map((chunk) => [sha256(chunk), chunk.length]);
}

export function defaultExtensionChunker(data, profile) {
  if (!data.length) {
    return [];
  }
  const chunks = [];
  let start = 0;
  const [primaryMask, secondaryMask] = rollingMasks(profile.targetSize);
  while (start < data.length) {
    const chunkEnd = nextChunkBoundary(data, {
      start,
      minSize: profile.minSize,
      targetSize: profile.targetSize,
      maxSize: profile.maxSize,
      primaryMask,
      secondaryMask,
    });
    chunks.push(data.slice(start, chunkEnd));
    start = chunkEnd;
  }
  return chunks;
}

function rollingMasks(targetSize) {
  const targetBits = Math.max(MIN_MASK_BITS, Math.round(Math.log2(Math.max(2, targetSize))));
  const primaryBits = Math.min(63, targetBits);
  const secondaryBits = Math.max(MIN_MASK_BITS, targetBits - 2);
  return [(1n << BigInt(primaryBits)) - 1n, (1n << BigInt(secondaryBits)) - 1n];
}

function nextChunkBoundary(data, options) {
  const totalLen = data.length;
  const { start, minSize, targetSize, maxSize, primaryMask, secondaryMask } = options;
  if (totalLen - start <= minSize) {
    return totalLen;
  }
  const minEnd = Math.min(totalLen, start + minSize);
  const targetEnd = Math.min(totalLen, start + targetSize);
  const maxEnd = Math.min(totalLen, start + maxSize);
  let fingerprint = 0n;
  const window = new Uint8Array(ROLLING_WINDOW_SIZE);
  let windowCount = 0;
  let windowPos = 0;
  for (let index = start; index < maxEnd; index += 1) {
    const byteValue = data[index];
    if (windowCount < ROLLING_WINDOW_SIZE) {
      fingerprint = rollFingerprint(fingerprint, byteValue);
      window[windowPos] = byteValue;
      windowPos = (windowPos + 1) % ROLLING_WINDOW_SIZE;
      windowCount += 1;
    } else {
      const outgoing = window[windowPos];
      window[windowPos] = byteValue;
      windowPos = (windowPos + 1) % ROLLING_WINDOW_SIZE;
      fingerprint =
        (rotateLeft(fingerprint, 1) ^ GEAR_TABLE[outgoing] ^ GEAR_TABLE[byteValue]) &
        ROLLING_HASH_MASK;
    }
    if (index + 1 < minEnd) {
      continue;
    }
    const mask = index + 1 < targetEnd ? primaryMask : secondaryMask;
    if ((fingerprint & mask) === 0n) {
      return index + 1;
    }
  }
  return maxEnd;
}

function rollFingerprint(current, byteValue) {
  return rotateLeft(current, 1) ^ GEAR_TABLE[byteValue];
}

function rotateLeft(value, shift) {
  const normalized = BigInt(shift & 63);
  return ((value << normalized) | (value >> (64n - normalized))) & ROLLING_HASH_MASK;
}

function buildGearTable() {
  let state = 0x9e3779b97f4a7c15n;
  const values = [];
  for (let index = 0; index < 256; index += 1) {
    state ^= (state >> 12n) & ROLLING_HASH_MASK;
    state ^= (state << 25n) & ROLLING_HASH_MASK;
    state ^= (state >> 27n) & ROLLING_HASH_MASK;
    state = (state * 0x2545f4914f6cdd1dn) & ROLLING_HASH_MASK;
    values.push(state);
  }
  return values;
}
