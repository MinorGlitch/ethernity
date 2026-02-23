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

function setShardStatus(state, statusPrefix, line, type) {
  const lines = statusPrefix.length ? [...statusPrefix, line] : [line];
  setStatus(state, "shardStatus", lines, type);
}

export function autoRecoverShardSecret(state, statusPrefix = []) {
  if (!state.shardThreshold || state.shardFrames.size < state.shardThreshold) {
    return false;
  }
  if (!state.shardDocHashHex) {
    setShardStatus(state, statusPrefix, "Shard recovery blocked: shard payload hash is missing.", "error");
    return false;
  }

  let cipherHash;
  try {
    cipherHash = ensureCiphertextAndHash(state);
  } catch (err) {
    setShardStatus(state, statusPrefix, `Shard recovery blocked: ${String(err)}`, "error");
    return false;
  }
  if (!cipherHash) {
    setShardStatus(
      state,
      statusPrefix,
      "Shard recovery blocked: collect main frames to derive ciphertext hash.",
      "warn"
    );
    return false;
  }

  const cipherHashHex = bytesToHex(cipherHash);
  if (cipherHashHex !== state.shardDocHashHex) {
    setShardStatus(
      state,
      statusPrefix,
      "Shard recovery blocked: shard hash does not match collected ciphertext.",
      "error"
    );
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
    setShardStatus(state, statusPrefix, "Recovered shard secret from shard documents.", "ok");
  } catch (err) {
    setShardStatus(state, statusPrefix, String(err), "error");
    return false;
  }
  return true;
}
