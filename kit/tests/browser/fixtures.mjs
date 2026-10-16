import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { chacha20poly1305 } from "@noble/ciphers/chacha.js";
import { hmac } from "@noble/hashes/hmac.js";
import { hkdf } from "@noble/hashes/hkdf.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { scrypt } from "@noble/hashes/scrypt.js";
import { FRAME_TYPE_AUTH, FRAME_TYPE_MAIN } from "../../app/constants.js";
import { concatByteParts as concatBytes } from "../../lib/bytes.js";
import { blake2b256 } from "../../lib/blake2b.js";
import { encodeCbor } from "../../lib/cbor.js";
import { buildFrame, signAuthPayload, toUnpaddedBase64 } from "../protocol_test_data.mjs";
import {
  buildRootPlaintext,
  buildExtensionPlaintext,
  ROOT_SIGNING_SEED,
  ROOT_SIGN_PUB,
} from "../extension_test_data.mjs";
import { kitDir } from "./support.mjs";

const textEncoder = new TextEncoder();

export function smokeBackup(updateMode = null) {
  const path = "generated-kit-smoke.txt";
  const passphrase = "generated-kit-smoke";
  const data = textEncoder.encode("recovered in browser");
  const rootFiles = [{ path, data }];
  const ciphertexts = [buildFastAgeCiphertext(buildRootPlaintext(rootFiles), passphrase)];
  if (updateMode) {
    const rootDocHash = blake2b256(ciphertexts[0]);
    for (let index = 1; index <= 2; index += 1) {
      ciphertexts.push(
        buildFastAgeCiphertext(
          buildExtensionPlaintext({
            index,
            rootDocHash,
            parentDocHash:
              updateMode === "cumulative" ? rootDocHash : blake2b256(ciphertexts[index - 1]),
            updateMode,
            files: [
              { path, data, inline: false },
              { path: "update.txt", data: textEncoder.encode(`update ${index}`) },
            ],
          }),
          passphrase,
        ),
      );
    }
  }
  const payload = ciphertexts
    .flatMap((ciphertext) => {
      const hash = blake2b256(ciphertext);
      const docId = hash.slice(0, 8);
      return [
        buildFrame({ frameType: FRAME_TYPE_MAIN, docId, data: ciphertext }),
        buildFrame({
          frameType: FRAME_TYPE_AUTH,
          docId,
          data: encodeCbor({
            version: 1,
            hash,
            pub: ROOT_SIGN_PUB,
            sig: signAuthPayload(hash, ROOT_SIGN_PUB, ROOT_SIGNING_SEED),
          }),
        }),
      ];
    })
    .map(toUnpaddedBase64)
    .join("\n");
  return { path, passphrase, payload, updateMode };
}

function base64NoPad(bytes) {
  return Buffer.from(bytes).toString("base64").replaceAll("=", "");
}

function buildFastAgeCiphertext(plaintext, passphrase) {
  const salt = new Uint8Array(16).fill(0x11);
  const fileKey = new Uint8Array(16).fill(0x22);
  const labelScrypt = textEncoder.encode("age-encryption.org/v1/scrypt");
  const labelAndSalt = concatBytes([labelScrypt, salt]);
  const wrappingKey = scrypt(passphrase, labelAndSalt, {
    N: 2,
    r: 8,
    p: 1,
    dkLen: 32,
  });
  const wrappedFileKey = chacha20poly1305(wrappingKey, new Uint8Array(12)).encrypt(fileKey);
  const headerPrefix = textEncoder.encode(
    `age-encryption.org/v1\n-> scrypt ${base64NoPad(salt)} 1\n${base64NoPad(wrappedFileKey)}\n---`,
  );
  const hmacKey = hkdf(sha256, fileKey, undefined, textEncoder.encode("header"), 32);
  const headerMac = hmac(sha256, hmacKey, headerPrefix);
  const header = concatBytes([headerPrefix, textEncoder.encode(` ${base64NoPad(headerMac)}\n`)]);
  const nonce = new Uint8Array(16).fill(0x33);
  const streamKey = hkdf(sha256, fileKey, nonce, textEncoder.encode("payload"), 32);
  const finalNonce = new Uint8Array(12);
  finalNonce[11] = 1;
  const payload = chacha20poly1305(streamKey, finalNonce).encrypt(plaintext);
  return concatBytes([header, nonce, payload]);
}

export async function frozenBackups() {
  const fixtures = resolve(kitDir, "..", "tests", "fixtures");
  const cases = [];
  for (const [release, scenario] of [
    ["v1_0", "file_no_shard"],
    ["v1_1", "sharded_embedded"],
  ]) {
    const directory = resolve(fixtures, release, "golden", "raw", scenario);
    const snapshot = JSON.parse(await readFile(resolve(directory, "snapshot.json"), "utf8"));
    cases.push({
      path: Object.keys(snapshot.expected_file_sha256)[0],
      payload: await readFile(resolve(directory, "main_payloads.txt"), "utf8"),
      passphrase: snapshot.passphrase,
      shards:
        scenario === "sharded_embedded"
          ? await readFile(resolve(directory, "shard_payloads_threshold.txt"), "utf8")
          : null,
      expectedHashes: snapshot.expected_file_sha256,
    });
  }
  const directory = resolve(
    fixtures,
    "v1_2",
    "extension_golden",
    "base64",
    "gzip_replacement_chain",
  );
  const snapshot = JSON.parse(await readFile(resolve(directory, "snapshot.json"), "utf8"));
  cases.push({
    path: "alpha.txt",
    payload: await readFile(resolve(directory, "chain_payloads.txt"), "utf8"),
    passphrase: snapshot.passphrase,
    expectedHashes: snapshot.states.extension_01,
  });
  return cases;
}
