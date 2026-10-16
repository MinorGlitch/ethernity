import { documentCounts } from "../app/documents/store.js";
import assert from "node:assert/strict";
import test from "node:test";
import { FRAME_TYPE_AUTH, FRAME_TYPE_MAIN } from "../app/constants.js";
import { addFrame } from "../app/frames_apply.js";
import { collectedRecoveryDocuments } from "../app/frames_cipher.js";
import { decodeFrame } from "../app/frames_protocol.js";
import { parseAutoPayload } from "../app/frames_parse.js";
import { createInitialState } from "../app/state/initial.js";
import {
  selectActionState,
  selectFrameCollectionComplete,
  selectFrameDiagnostics,
} from "../app/state/selectors.js";
import { encodeCbor } from "../lib/cbor.js";
import { blake2b256 } from "../lib/blake2b.js";
import { bytesToHex } from "../lib/bytes.js";
import { buildFrame } from "./protocol_test_data.mjs";
import {
  EXT1_DOC_ID,
  ROOT_SIGN_PUB,
  SIGNATURE,
  addSingleFrameDocument,
} from "./extension_test_data.mjs";

test("browser action state blocks latest recovery for AUTH-only extension records", () => {
  const state = createInitialState();
  state.agePassphrase = "pw";
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0x38) });
  addFrame(
    state,
    decodeFrame(
      buildFrame({
        frameType: FRAME_TYPE_AUTH,
        docId: EXT1_DOC_ID,
        data: encodeCbor({
          version: 1,
          hash: new Uint8Array(32).fill(0xaa),
          pub: ROOT_SIGN_PUB,
          sig: SIGNATURE,
        }),
      }),
    ),
  );

  assert.equal(selectActionState(state).canDecryptCiphertext, false);
  state.expectedHeadDocHashText = "aa".repeat(32);
  state.extensionTargetText = "root";
  assert.equal(selectActionState(state).canDecryptCiphertext, true);
  state.extensionTargetText = "1";
  assert.equal(selectActionState(state).canDecryptCiphertext, true);
});

test("browser frame diagnostics report invalid AUTH payloads", () => {
  const state = createInitialState();
  const frame = buildFrame({
    frameType: FRAME_TYPE_AUTH,
    docId: EXT1_DOC_ID,
    data: Uint8Array.of(0xff),
  });

  const added = parseAutoPayload(state, Buffer.from(frame).toString("base64").replace(/=+$/, ""));
  const diagnostics = selectFrameDiagnostics(state);

  assert.equal(added, 0);
  assert.equal(documentCounts(state).authErrors, 1);
  assert.equal(diagnostics.find((item) => item.label === "AUTH errors")?.value, "1");
});

test("collected recovery documents reject frame doc_id not derived from ciphertext", () => {
  const state = createInitialState();
  const ciphertext = Uint8Array.of(0x99);
  const fakeDocId = Uint8Array.from([1, 2, 3, 4, 5, 6, 7, 8]);

  addFrame(
    state,
    decodeFrame(buildFrame({ frameType: FRAME_TYPE_MAIN, docId: fakeDocId, data: ciphertext })),
  );

  assert.throws(() => collectedRecoveryDocuments(state), /doc_id/);
});

test("collected recovery documents reject AUTH frames without MAIN documents", () => {
  const state = createInitialState();
  const ciphertext = Uint8Array.of(0x9a);
  addSingleFrameDocument(state, { ciphertext });
  addFrame(
    state,
    decodeFrame(
      buildFrame({
        frameType: FRAME_TYPE_AUTH,
        docId: EXT1_DOC_ID,
        data: encodeCbor({
          version: 1,
          hash: new Uint8Array(32).fill(0xab),
          pub: ROOT_SIGN_PUB,
          sig: SIGNATURE,
        }),
      }),
    ),
  );

  assert.throws(() => collectedRecoveryDocuments(state), /AUTH frame\(s\) without MAIN/);
});

test("encrypted file download is disabled for multi-document scans", () => {
  const state = createInitialState();
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0xa1) });
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0xa2) });

  const actionState = selectActionState(state);

  assert.equal(actionState.canDownloadCipher, false);
  assert.equal(
    actionState.downloadCipherDisabledReason,
    "Encrypted file download is only available for one backup document.",
  );
});

test("browser action state requires an explicit latest freshness decision", () => {
  const state = createInitialState();
  state.agePassphrase = "pw";
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0xa0) });

  const blocked = selectActionState(state);
  assert.equal(blocked.canDecryptCiphertext, false);
  assert.equal(
    blocked.decryptDisabledReason,
    "latest recovery requires an expected head hash or explicit freshness-unknown acknowledgement",
  );

  state.freshnessUnknownAcknowledged = true;
  assert.equal(selectActionState(state).canDecryptCiphertext, true);
});

test("browser action state accepts the inline latest head hash", () => {
  const state = createInitialState();
  state.agePassphrase = "pw";
  state.extensionTargetText = `latest:${"ab".repeat(32)}`;
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0xa1) });

  const actionState = selectActionState(state);

  assert.equal(actionState.freshnessDecisionReady, true);
  assert.equal(actionState.canDecryptCiphertext, true);
});

test("multi-document collection waits for incomplete extensions before latest recovery", () => {
  const state = createInitialState();
  state.agePassphrase = "pw";
  addSingleFrameDocument(state, { ciphertext: Uint8Array.of(0xa3) });
  addFrame(
    state,
    decodeFrame(
      buildFrame({
        frameType: FRAME_TYPE_MAIN,
        docId: EXT1_DOC_ID,
        index: 0,
        total: 2,
        data: Uint8Array.of(0xa4),
      }),
    ),
  );

  state.expectedHeadDocHashText = bytesToHex(blake2b256(Uint8Array.of(0xa3)));
  const latestActionState = selectActionState(state);
  assert.equal(selectFrameCollectionComplete(state), false);
  assert.equal(latestActionState.canDecryptCiphertext, false);
  assert.equal(latestActionState.canDecryptRootOnly, true);

  state.extensionTargetText = "root";
  assert.equal(selectActionState(state).canDecryptCiphertext, true);
});
