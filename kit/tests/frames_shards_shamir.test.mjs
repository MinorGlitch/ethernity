import assert from "node:assert/strict";
import test from "node:test";

import {
  FRAME_MAGIC,
  FRAME_TYPE_AUTH,
  FRAME_TYPE_KEY,
  FRAME_TYPE_MAIN,
  FRAME_VERSION,
  MAX_CIPHERTEXT_BYTES,
  SHARD_KEY_PASSPHRASE,
  SHARD_KEY_SIGNING_SEED,
} from "../app/constants.js";
import {
  parseAutoPayload,
  parseAutoShard,
} from "../app/frames_parse.js";
import { listMissing } from "../app/frame_list.js";
import {
  ensureCiphertextAndHash,
  reassembleCiphertext,
  syncCollectedCiphertext,
} from "../app/frames_cipher.js";
import { autoRecoverShardSecret } from "../app/shards.js";
import { createInitialState } from "../app/state/initial.js";
import { encodeCbor } from "../lib/cbor.js";
import { blake2b256 } from "../lib/blake2b.js";
import { bytesToHex, hexToBytes } from "../lib/encoding.js";
import { recoverSecretFromShards } from "../lib/shamir.js";
import {
  buildFrame,
  concatBytes,
  encodeUvarint,
  encodeZBase32,
  ensureAtob,
  mutateFrameCrc,
  toUnpaddedBase64,
} from "./test_helpers.mjs";

ensureAtob();

const FIXTURE_PASSPHRASE = "stable-v1-shamir-meaningful";
const FIXTURE_SHARES = {
  docHashHex: "61edf49ad177241230eed9b9ce9279a4a3c2f4ecf4258a0de53f041a134f3ce4",
  share1: "e7fdbe85696bbbe4b866e834b96163685ef63664d9ea8746f942799aef313b11",
  share2: "5a67deac6678005323ba45d1d1757dc1ca5bc36a016ebc24581b4735de627622",
  share3: "ceee014b637696c1aaf1de8d097977dbb9c0906fb6ed5505c72c52af31534d33",
};

function shardPayload({
  keyType = SHARD_KEY_PASSPHRASE,
  threshold = 2,
  shareCount = 3,
  shareIndex = 1,
  secretLen = FIXTURE_PASSPHRASE.length,
  shareHex = FIXTURE_SHARES.share1,
  docHash = hexToBytes(FIXTURE_SHARES.docHashHex),
  signPub = new Uint8Array(32),
  signature = new Uint8Array(64),
}) {
  return {
    version: 1,
    type: keyType,
    threshold,
    share_count: shareCount,
    share_index: shareIndex,
    length: secretLen,
    share: hexToBytes(shareHex),
    hash: docHash,
    pub: signPub,
    sig: signature,
  };
}

function authPayload(signature = new Uint8Array(64)) {
  return {
    version: 1,
    hash: new Uint8Array(32),
    pub: new Uint8Array(32),
    sig: signature,
  };
}

function rawFrameBytes({ version = FRAME_VERSION, frameType = FRAME_TYPE_MAIN, data = new Uint8Array(0) }) {
  const body = concatBytes([
    Uint8Array.from(FRAME_MAGIC),
    encodeUvarint(version),
    Uint8Array.of(frameType),
    Uint8Array.of(1, 2, 3, 4, 5, 6, 7, 8),
    encodeUvarint(0),
    encodeUvarint(1),
    encodeUvarint(data.length),
    data,
  ]);
  return buildFrame({ frameType, data, index: 0, total: 1 });
}

test("parseAutoPayload handles frame state transitions and hash caching", () => {
  const state = createInitialState();
  const docId = Uint8Array.of(9, 9, 9, 9, 9, 9, 9, 9);

  const main0 = toUnpaddedBase64(buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(1, 2), index: 0, total: 2, docId }));
  const main0Dup = toUnpaddedBase64(buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(1, 2), index: 0, total: 2, docId }));
  const main0Conflict = toUnpaddedBase64(buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(3, 4), index: 0, total: 2, docId }));
  const foreignDoc = toUnpaddedBase64(buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(5), index: 1, total: 2, docId: Uint8Array.of(1, 1, 1, 1, 1, 1, 1, 1) }));
  const keyFrame = toUnpaddedBase64(
    buildFrame({
      frameType: FRAME_TYPE_KEY,
      data: encodeCbor(shardPayload({ threshold: 1, shareCount: 1, secretLen: 1, shareHex: "00".repeat(16) })),
      docId,
    })
  );

  assert.equal(parseAutoPayload(state, main0), 1);
  assert.equal(parseAutoPayload(state, main0Dup), 1);
  assert.equal(parseAutoPayload(state, main0Conflict), 1);
  assert.equal(parseAutoPayload(state, foreignDoc), 1);
  assert.equal(parseAutoPayload(state, keyFrame), 1);

  assert.equal(state.duplicates, 1);
  assert.equal(state.conflicts, 1);
  assert.equal(state.ignored, 2);
  assert.deepEqual(listMissing(state.total, state.mainFrames), [1]);

  const main1 = toUnpaddedBase64(buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(6), index: 1, total: 2, docId }));
  assert.equal(parseAutoPayload(state, main1), 1);
  const firstHash = ensureCiphertextAndHash(state);
  const secondHash = ensureCiphertextAndHash(state);
  assert.ok(firstHash instanceof Uint8Array);
  assert.deepEqual(Array.from(firstHash), Array.from(secondHash));
});

test("parseAutoPayload supports fallback sections and handles invalid auth fallback", () => {
  const state = createInitialState();
  const main = buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(7), total: 1 });
  const badAuth = Uint8Array.of(0x41, 0x50, 0x01);
  const text = [
    "Main Frame:",
    encodeZBase32(main),
    "Auth Frame:",
    encodeZBase32(badAuth),
  ].join("\n");

  const added = parseAutoPayload(state, text);
  assert.equal(added, 1);
  assert.equal(state.mainFrames.size, 1);
  assert.equal(state.authErrors, 1);
});

test("parseAutoPayload rejects malformed frame encodings", () => {
  const badFrames = [
    Uint8Array.of(0x41, 0x50, 0x01),
    (() => {
      const frame = buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(1) });
      frame[0] = 0x00;
      return frame;
    })(),
    (() => {
      const frame = buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(1) });
      frame[2] = 0x02;
      return frame;
    })(),
    (() => {
      const frame = buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(1), total: 4097 });
      return frame;
    })(),
    mutateFrameCrc(buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(1) })),
  ];

  for (const frame of badFrames) {
    const state = createInitialState();
    assert.throws(
      () => parseAutoPayload(state, toUnpaddedBase64(frame)),
      /(bad magic|unsupported frame version|non-canonical varint|crc mismatch|neither valid QR payloads nor valid fallback text)/
    );
  }
});

test("parseAutoShard handles duplicates, conflicts, and fallback", () => {
  const state = createInitialState();
  const docId = Uint8Array.of(4, 4, 4, 4, 4, 4, 4, 4);
  const first = buildFrame({
    frameType: FRAME_TYPE_KEY,
    data: encodeCbor(shardPayload({ shareIndex: 1, shareHex: FIXTURE_SHARES.share1 })),
    docId,
  });
  const duplicate = buildFrame({
    frameType: FRAME_TYPE_KEY,
    data: encodeCbor(shardPayload({ shareIndex: 1, shareHex: FIXTURE_SHARES.share1 })),
    docId,
  });
  const conflictSameIndex = buildFrame({
    frameType: FRAME_TYPE_KEY,
    data: encodeCbor(shardPayload({ shareIndex: 1, shareHex: FIXTURE_SHARES.share2 })),
    docId,
  });
  const conflictDoc = buildFrame({
    frameType: FRAME_TYPE_KEY,
    data: encodeCbor(shardPayload({ shareIndex: 2, shareHex: FIXTURE_SHARES.share2 })),
    docId: Uint8Array.of(8, 8, 8, 8, 8, 8, 8, 8),
  });

  assert.equal(parseAutoShard(state, toUnpaddedBase64(first)), 1);
  assert.equal(parseAutoShard(state, toUnpaddedBase64(duplicate)), 1);
  assert.equal(parseAutoShard(state, toUnpaddedBase64(conflictSameIndex)), 1);
  assert.equal(parseAutoShard(state, toUnpaddedBase64(conflictDoc)), 1);
  assert.equal(state.shardFrames.size, 1);
  assert.equal(state.shardDuplicates, 1);
  assert.equal(state.shardConflicts, 2);

  const fallbackState = createInitialState();
  const fallbackText = ["Shard Frame:", encodeZBase32(first)].join("\n");
  assert.equal(parseAutoShard(fallbackState, fallbackText), 1);

  assert.throws(
    () => parseAutoShard(createInitialState(), "Shard Frame:\nnot-zbase32!!!"),
    /no shard fallback lines found/
  );
});

test("ciphertext helpers enforce limits and missing frames", () => {
  const missingState = createInitialState();
  missingState.total = 1;
  assert.throws(() => reassembleCiphertext(missingState), /missing frames/);

  const syncState = createInitialState();
  syncState.total = 1;
  syncState.mainFrames.set(0, { data: new Uint8Array(MAX_CIPHERTEXT_BYTES + 1) });
  syncCollectedCiphertext(syncState);
  assert.equal(syncState.ciphertext, null);
});

test("recoverSecretFromShards reconstructs known passphrase and rejects mismatches", () => {
  const makeShare = (index, hex) => ({
    keyType: SHARD_KEY_PASSPHRASE,
    threshold: 2,
    shareCount: 3,
    shareIndex: index,
    secretLen: FIXTURE_PASSPHRASE.length,
    share: hexToBytes(hex),
  });

  const recovered = recoverSecretFromShards([
    makeShare(1, FIXTURE_SHARES.share1),
    makeShare(2, FIXTURE_SHARES.share2),
  ]);
  assert.equal(new TextDecoder().decode(recovered), FIXTURE_PASSPHRASE);

  assert.throws(
    () => recoverSecretFromShards([]),
    /no shard payloads provided/
  );
  assert.throws(
    () => recoverSecretFromShards([makeShare(1, FIXTURE_SHARES.share1)]),
    /need at least 2 shard\(s\) to recover secret/
  );
  assert.throws(
    () => recoverSecretFromShards([
      makeShare(1, FIXTURE_SHARES.share1),
      { ...makeShare(2, FIXTURE_SHARES.share2), keyType: SHARD_KEY_SIGNING_SEED },
    ]),
    /key types do not match/
  );
  assert.throws(
    () => recoverSecretFromShards([
      makeShare(1, FIXTURE_SHARES.share1),
      { ...makeShare(2, FIXTURE_SHARES.share2), shareIndex: 1 },
    ]),
    /duplicate shard index/
  );
  assert.throws(
    () => recoverSecretFromShards([
      makeShare(1, FIXTURE_SHARES.share1),
      { ...makeShare(2, FIXTURE_SHARES.share2), share: hexToBytes("aa".repeat(15)) },
    ]),
    /multiple of block size/
  );
});

test("autoRecoverShardSecret enforces gating and supports both secret types", () => {
  const baseCipher = Uint8Array.of(1, 2, 3);
  const baseHashHex = bytesToHex(blake2b256(baseCipher));

  const missingHashState = createInitialState();
  missingHashState.shardThreshold = 1;
  missingHashState.shardFrames.set(1, {
    keyType: SHARD_KEY_PASSPHRASE,
    threshold: 1,
    shareCount: 1,
    shareIndex: 1,
    secretLen: 1,
    share: new Uint8Array(16),
  });
  assert.equal(autoRecoverShardSecret(missingHashState), false);
  assert.equal(missingHashState.shardStatus.type, "error");

  const missingCipherState = createInitialState();
  missingCipherState.shardThreshold = 1;
  missingCipherState.shardDocHashHex = baseHashHex;
  missingCipherState.shardFrames.set(1, {
    keyType: SHARD_KEY_PASSPHRASE,
    threshold: 1,
    shareCount: 1,
    shareIndex: 1,
    secretLen: 1,
    share: new Uint8Array(16),
  });
  assert.equal(autoRecoverShardSecret(missingCipherState), false);
  assert.equal(missingCipherState.shardStatus.type, "warn");

  const passphraseState = createInitialState();
  passphraseState.total = 1;
  passphraseState.mainFrames.set(0, { data: baseCipher });
  passphraseState.shardKeyType = SHARD_KEY_PASSPHRASE;
  passphraseState.shardThreshold = 2;
  passphraseState.shardDocHashHex = baseHashHex;
  passphraseState.shardFrames.set(1, {
    keyType: SHARD_KEY_PASSPHRASE,
    threshold: 2,
    shareCount: 3,
    shareIndex: 1,
    secretLen: FIXTURE_PASSPHRASE.length,
    share: hexToBytes(FIXTURE_SHARES.share1),
  });
  passphraseState.shardFrames.set(2, {
    keyType: SHARD_KEY_PASSPHRASE,
    threshold: 2,
    shareCount: 3,
    shareIndex: 2,
    secretLen: FIXTURE_PASSPHRASE.length,
    share: hexToBytes(FIXTURE_SHARES.share2),
  });
  assert.equal(autoRecoverShardSecret(passphraseState), true);
  assert.equal(passphraseState.recoveredShardSecret, FIXTURE_PASSPHRASE);
  assert.equal(passphraseState.agePassphrase, FIXTURE_PASSPHRASE);

  const seed = hexToBytes("11".repeat(32));
  const signingState = createInitialState();
  signingState.total = 1;
  signingState.mainFrames.set(0, { data: baseCipher });
  signingState.shardKeyType = SHARD_KEY_SIGNING_SEED;
  signingState.shardThreshold = 1;
  signingState.shardDocHashHex = baseHashHex;
  signingState.shardFrames.set(1, {
    keyType: SHARD_KEY_SIGNING_SEED,
    threshold: 1,
    shareCount: 1,
    shareIndex: 1,
    secretLen: 32,
    share: seed,
  });
  assert.equal(autoRecoverShardSecret(signingState), true);
  assert.equal(signingState.recoveredShardSecret, bytesToHex(seed));
});

test("autoRecoverShardSecret reports ciphertext reassembly failures as shardStatus errors", () => {
  const state = createInitialState();
  state.total = 2;
  state.mainFrames.set(0, { data: new Uint8Array(MAX_CIPHERTEXT_BYTES) });
  state.mainFrames.set(1, { data: Uint8Array.of(1) });
  state.shardThreshold = 1;
  state.shardDocHashHex = "00".repeat(32);
  state.shardFrames.set(1, {
    keyType: SHARD_KEY_PASSPHRASE,
    threshold: 1,
    shareCount: 1,
    shareIndex: 1,
    secretLen: 1,
    share: new Uint8Array(16),
  });

  assert.equal(autoRecoverShardSecret(state), false);
  assert.equal(state.shardStatus.type, "error");
  assert.match(state.shardStatus.lines.join("\n"), /Shard recovery blocked:/);
  assert.match(state.shardStatus.lines.join("\n"), /MAX_CIPHERTEXT_BYTES/);
});
