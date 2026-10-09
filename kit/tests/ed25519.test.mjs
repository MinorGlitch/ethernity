import assert from "node:assert/strict";
import test from "node:test";

import {
  getSigningPublicKey,
  signSigningMessage,
  verifySigningSignature,
  verifySignature,
} from "../lib/ed25519.js";
import { bytesToHex, hexToBytes } from "../lib/bytes.js";

test("Ed25519 adapter matches the RFC8032 empty-message test vector", () => {
  const seed = hexToBytes("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60");
  const message = new Uint8Array();
  const expectedPub = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a";
  const expectedSignature =
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b";

  const publicKey = getSigningPublicKey(seed);
  const signature = signSigningMessage(message, seed);

  assert.equal(bytesToHex(publicKey), expectedPub);
  assert.equal(bytesToHex(signature), expectedSignature);
  assert.equal(verifySigningSignature(signature, message, publicKey), true);

  const alteredSignature = signature.slice();
  alteredSignature[0] ^= 0x01;
  assert.equal(verifySigningSignature(alteredSignature, message, publicKey), false);
});

test("signature verification uses the portable implementation when native Ed25519 is absent or throws", async () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  delete globalThis.crypto;
  const seed = new Uint8Array(32).fill(7);
  const publicKey = getSigningPublicKey(seed);
  const message = Uint8Array.of(1, 2, 3);
  const signature = signSigningMessage(message, seed);
  try {
    for (const crypto of [
      undefined,
      {
        subtle: {
          importKey() {
            throw new Error("unsupported");
          },
        },
      },
    ]) {
      globalThis.crypto = crypto;
      assert.equal(await verifySignature(signature, message, publicKey), true);
      assert.equal(await verifySignature(signature, Uint8Array.of(4), publicKey), false);
      assert.equal(await verifySignature(new Uint8Array(), message, publicKey), false);
    }
  } finally {
    if (original) Object.defineProperty(globalThis, "crypto", original);
    else delete globalThis.crypto;
  }
});
