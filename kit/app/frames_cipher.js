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

import { blake2b256 } from "../lib/blake2b.js";
import { bytesToHex, hexToBytes } from "../lib/encoding.js";
import { MAX_CIPHERTEXT_BYTES } from "./constants.js";

export function reassembleCiphertext(state) {
  if (state.total === null || state.mainFrames.size !== state.total) {
    throw new Error("missing frames");
  }
  const chunks = [];
  for (let i = 0; i < state.total; i += 1) {
    const frame = state.mainFrames.get(i);
    if (!frame) throw new Error(`missing frame ${i}`);
    chunks.push(frame.data);
  }
  const totalLen = chunks.reduce((sum, arr) => sum + arr.length, 0);
  if (totalLen > MAX_CIPHERTEXT_BYTES) {
    throw new Error(
      `reassembled payload exceeds MAX_CIPHERTEXT_BYTES (${MAX_CIPHERTEXT_BYTES}): ${totalLen} bytes`,
    );
  }
  const out = new Uint8Array(totalLen);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

export function ensureCiphertextAndHash(state) {
  if (!state.total || state.mainFrames.size !== state.total) {
    return null;
  }
  if (!state.ciphertext) {
    state.ciphertext = reassembleCiphertext(state);
  }
  if (!state.cipherDocHashHex) {
    const hash = blake2b256(state.ciphertext);
    state.cipherDocHashHex = bytesToHex(hash);
    return hash;
  }
  return hexToBytes(state.cipherDocHashHex);
}

export function syncCollectedCiphertext(state) {
  if (state.total && state.mainFrames.size === state.total) {
    try {
      state.ciphertext = reassembleCiphertext(state);
    } catch {
      // leave ciphertext unset if reassembly fails
    }
  }
}
