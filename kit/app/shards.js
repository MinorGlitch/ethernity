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

import { bytesToHex } from "../lib/encoding.js";
import { recoverSecretFromShards } from "../lib/shamir.js";
import { SHARD_KEY_PASSPHRASE, SHARD_KEY_SIGNING_SEED, textDecoder } from "./constants.js";
import { ensureCiphertextAndHash } from "./frames.js";
import { setStatus } from "./state/initial.js";

export function autoRecoverShardSecret(state, statusPrefix = []) {
  if (!state.shardThreshold || state.shardFrames.size < state.shardThreshold) {
    return false;
  }
  if (!state.shardDocHashHex) {
    const lines = statusPrefix.length
      ? [...statusPrefix, "Shard recovery blocked: shard payload hash is missing."]
      : ["Shard recovery blocked: shard payload hash is missing."];
    setStatus(state, "shardStatus", lines, "error");
    return false;
  }

  const cipherHash = ensureCiphertextAndHash(state);
  if (!cipherHash) {
    const lines = statusPrefix.length
      ? [...statusPrefix, "Shard recovery blocked: collect main frames to derive ciphertext hash."]
      : ["Shard recovery blocked: collect main frames to derive ciphertext hash."];
    setStatus(state, "shardStatus", lines, "warn");
    return false;
  }

  const cipherHashHex = bytesToHex(cipherHash);
  if (cipherHashHex !== state.shardDocHashHex) {
    const lines = statusPrefix.length
      ? [...statusPrefix, "Shard recovery blocked: shard hash does not match collected ciphertext."]
      : ["Shard recovery blocked: shard hash does not match collected ciphertext."];
    setStatus(state, "shardStatus", lines, "error");
    return false;
  }

  try {
    const shares = Array.from(state.shardFrames.values());
    const secretBytes = recoverSecretFromShards(shares);
    if (state.shardKeyType === SHARD_KEY_SIGNING_SEED) {
      const recoveredHex = bytesToHex(secretBytes);
      state.recoveredShardSecret = recoveredHex;
    } else if (state.shardKeyType === SHARD_KEY_PASSPHRASE) {
      const recoveredText = textDecoder.decode(secretBytes);
      state.recoveredShardSecret = recoveredText;
      if (!state.agePassphrase) {
        state.agePassphrase = recoveredText;
      }
    } else {
      state.recoveredShardSecret = bytesToHex(secretBytes);
    }
    const lines = statusPrefix.length
      ? [...statusPrefix, "Recovered shard secret from shard documents."]
      : ["Recovered shard secret from shard documents."];
    setStatus(state, "shardStatus", lines, "ok");
  } catch (err) {
    const lines = statusPrefix.length ? [...statusPrefix, String(err)] : [String(err)];
    setStatus(state, "shardStatus", lines, "error");
    return false;
  }
  return true;
}
