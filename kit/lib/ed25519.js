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

import * as ed25519 from "@noble/ed25519";
import { sha512 } from "@noble/hashes/sha2.js";

ed25519.hashes.sha512 = sha512;

export function getSigningPublicKey(signingSeed) {
  return ed25519.getPublicKey(signingSeed);
}

export function signSigningMessage(message, signingSeed) {
  return ed25519.sign(message, signingSeed);
}

export function verifySigningSignature(signature, message, signPub) {
  return ed25519.verify(signature, message, signPub, { zip215: false });
}

export async function verifySignature(signature, message, signPub) {
  const subtle = globalThis.crypto?.subtle;
  if (subtle?.importKey) {
    try {
      const key = await subtle.importKey("raw", signPub, { name: "Ed25519" }, false, ["verify"]);
      return await subtle.verify("Ed25519", key, signature, message);
    } catch {
      // Browsers without native Ed25519 use the same strict portable verifier.
    }
  }
  try {
    return verifySigningSignature(signature, message, signPub);
  } catch {
    return false;
  }
}
