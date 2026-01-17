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

import { concatBytes } from "../lib/encoding.js";
import { encodeCbor } from "../lib/cbor.js";
import { SHARD_DOMAIN, SHARD_VERSION, textEncoder } from "./constants.js";

async function verifyShardSignature(payload) {
  if (!crypto || !crypto.subtle || !crypto.subtle.importKey) {
    return null;
  }
  try {
    const key = await crypto.subtle.importKey("raw", payload.signPub, { name: "Ed25519" }, false, [
      "verify",
    ]);
    const signedPayload = {
      version: SHARD_VERSION,
      type: payload.keyType,
      threshold: payload.threshold,
      share_count: payload.shareCount,
      share_index: payload.shareIndex,
      length: payload.secretLen,
      share: payload.share,
      hash: payload.docHash,
      pub: payload.signPub,
    };
    const signedBytes = encodeCbor(signedPayload);
    const message = concatBytes(textEncoder.encode(SHARD_DOMAIN), signedBytes);
    return await crypto.subtle.verify("Ed25519", key, payload.signature, message);
  } catch {
    return null;
  }
}

export async function verifyCollectedShardSignatures(state) {
  if (!state.shardFrames || state.shardFrames.size === 0) {
    return { unavailable: false, verified: 0, invalid: 0 };
  }
  if (!crypto || !crypto.subtle || !crypto.subtle.importKey) {
    return { unavailable: true, verified: 0, invalid: 0 };
  }

  let verified = 0;
  let invalid = 0;

  for (const [shareIndex, payload] of state.shardFrames.entries()) {
    const ok = await verifyShardSignature(payload);
    if (ok === true) {
      verified += 1;
      continue;
    }
    if (ok === false) {
      state.shardFrames.delete(shareIndex);
      invalid += 1;
    }
  }

  return { unavailable: false, verified, invalid };
}
