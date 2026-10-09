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

import { encodeCbor } from "../lib/cbor.js";
import { verifySignature } from "../lib/ed25519.js";
import { concatBytes } from "../lib/bytes.js";
import { SHARD_DOMAIN, SHARD_VERSION, textEncoder } from "./constants.js";

function shardSignatureMessage(payload) {
  const signedPayload = {
    version: payload.version,
    type: payload.keyType,
    threshold: payload.threshold,
    share_count: payload.shareCount,
    share_index: payload.shareIndex,
    length: payload.secretLen,
    share: payload.share,
    hash: payload.docHash,
    pub: payload.signPub,
  };
  if (payload.version === SHARD_VERSION) {
    signedPayload.set_id = payload.shardSetId;
  }
  const signedBytes = encodeCbor(signedPayload);
  return concatBytes(textEncoder.encode(SHARD_DOMAIN), signedBytes);
}

export async function verifyCollectedShardSignatures(state) {
  let verified = 0;
  let invalid = 0;

  for (const record of state.shardSets.values()) {
    for (const [shareIndex, payload] of record.shardFrames.entries()) {
      payload.signatureVerified = false;
      const ok = await verifySignature(
        payload.signature,
        shardSignatureMessage(payload),
        payload.signPub,
      );
      if (ok === true) {
        payload.signatureVerified = true;
        verified += 1;
        continue;
      }
      record.shardFrames.delete(shareIndex);
      invalid += 1;
    }
  }

  return { verified, invalid };
}
