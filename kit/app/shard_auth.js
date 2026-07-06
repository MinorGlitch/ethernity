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

import { ed25519 } from "@noble/curves/ed25519.js";

import { encodeCbor } from "../lib/cbor.js";
import { concatBytes } from "../lib/encoding.js";
import { SHARD_DOMAIN, SHARD_VERSION, textEncoder } from "./constants.js";
import { shardSetRecords, syncLegacyShardFields } from "./shard_store.js";

async function verifyShardSignature(payload) {
  const message = shardSignatureMessage(payload);
  const cryptoApi = globalThis.crypto;
  if (cryptoApi?.subtle?.importKey) {
    try {
      const key = await cryptoApi.subtle.importKey(
        "raw",
        payload.signPub,
        { name: "Ed25519" },
        false,
        ["verify"],
      );
      return await cryptoApi.subtle.verify("Ed25519", key, payload.signature, message);
    } catch {
      return verifyShardSignaturePortable(payload.signature, message, payload.signPub);
    }
  }
  return verifyShardSignaturePortable(payload.signature, message, payload.signPub);
}

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

function verifyShardSignaturePortable(signature, message, signPub) {
  try {
    return ed25519.verify(signature, message, signPub, { zip215: false });
  } catch {
    return false;
  }
}

export async function verifyCollectedShardSignatures(state) {
  const records = shardSetRecords(state);
  if (!records.length) {
    return { unavailable: false, verified: 0, invalid: 0 };
  }

  let verified = 0;
  let invalid = 0;

  for (const { record } of records) {
    for (const [shareIndex, payload] of record.shardFrames.entries()) {
      payload.signatureVerified = false;
      const ok = await verifyShardSignature(payload);
      if (ok === true) {
        payload.signatureVerified = true;
        verified += 1;
        continue;
      }
      record.shardFrames.delete(shareIndex);
      invalid += 1;
    }
  }
  syncLegacyShardFields(state);

  return { unavailable: false, verified, invalid };
}
