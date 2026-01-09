import { bytesToHex } from "../lib/encoding.js";
import { recoverSecretFromShards } from "../lib/shamir.js";
import { SHARD_KEY_PASSPHRASE, SHARD_KEY_SIGNING_SEED, textDecoder } from "./constants.js";
import { setStatus } from "./state/initial.js";

export function autoRecoverShardSecret(state, statusPrefix = []) {
  if (!state.shardThreshold || state.shardFrames.size < state.shardThreshold) {
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
