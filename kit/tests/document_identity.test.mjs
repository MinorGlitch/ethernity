import assert from "node:assert/strict";
import test from "node:test";

import {
  documentIdentityFromCiphertext,
  documentIdentityFromDocHash,
} from "../app/documents/identity.js";
import { blake2b256 } from "../lib/blake2b.js";
import { bytesToHex } from "../lib/bytes.js";

test("document identity derives the hash and ID from ciphertext", () => {
  const ciphertext = Uint8Array.of(1, 2, 3, 4);
  const expectedHash = blake2b256(ciphertext);

  const identity = documentIdentityFromCiphertext(ciphertext);

  assert.deepEqual(identity.docHash, expectedHash);
  assert.equal(identity.docHashHex, bytesToHex(expectedHash));
  assert.deepEqual(identity.docId, expectedHash.slice(0, 8));
  assert.equal(identity.docIdHex, bytesToHex(expectedHash.slice(0, 8)));
});

test("document identity can reuse an existing document hash", () => {
  const docHash = Uint8Array.from({ length: 32 }, (_, index) => index);

  const identity = documentIdentityFromDocHash(docHash);

  assert.equal(identity.docHash, docHash);
  assert.equal(identity.docHashHex, bytesToHex(docHash));
  assert.deepEqual(identity.docId, docHash.slice(0, 8));
});

test("ciphertext identity rejects non-byte inputs", () => {
  assert.throws(
    () => documentIdentityFromCiphertext("ciphertext"),
    /document ciphertext must be bytes/,
  );
});
