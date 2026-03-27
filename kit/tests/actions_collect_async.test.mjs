import assert from "node:assert/strict";
import test from "node:test";

import { MAX_CIPHERTEXT_BYTES } from "../app/constants.js";
import { addPayloads, resetAll } from "../app/actions_collect.js";
import { updateAuthStatus } from "../app/auth.js";
import { createInitialState } from "../app/state/initial.js";
import { reducer } from "../app/state/reducer.js";

const MAIN_QR_PAYLOAD_SINGLE_FRAME = "QVABRAAAAAAAAAAAAAEBYSBj2P8";

function createStore() {
  let state = createInitialState();
  return {
    dispatch(action) {
      state = reducer(state, action);
    },
    getState() {
      return state;
    },
  };
}

test("updateAuthStatus clears pending guard after ciphertext errors", async () => {
  const state = createInitialState();
  state.authPayload = {
    signPub: new Uint8Array(32),
    signature: new Uint8Array(64),
    docHash: new Uint8Array(32),
  };
  state.total = 1;
  state.mainFrames.set(0, { data: new Uint8Array(MAX_CIPHERTEXT_BYTES + 1) });

  await updateAuthStatus(state);
  assert.equal(state.authStatus, "ciphertext error");

  state.mainFrames.set(0, { data: new Uint8Array([1, 2, 3]) });
  state.ciphertext = null;
  state.cipherDocHashHex = null;
  state.authDocHashHex = null;

  await updateAuthStatus(state);
  assert.notEqual(state.authStatus, "ciphertext error");
});

test("updateAuthStatus degrades cleanly when crypto is unavailable", async () => {
  const original = globalThis.crypto;
  const state = createInitialState();
  state.authPayload = {
    signPub: new Uint8Array(32),
    signature: new Uint8Array(64),
    docHash: new Uint8Array(32),
  };
  state.total = 1;
  state.mainFrames.set(0, { data: new Uint8Array([1, 2, 3]) });

  try {
    delete globalThis.crypto;
    await updateAuthStatus(state);
  } finally {
    if (original) {
      globalThis.crypto = original;
    }
  }

  assert.equal(state.authStatus, "doc_hash matches; signature not verified");
});

test("async main followups do not overwrite reset state", async () => {
  const store = createStore();
  const state = store.getState();
  state.payloadText = MAIN_QR_PAYLOAD_SINGLE_FRAME;
  state.authPayload = {
    signPub: new Uint8Array(32),
    signature: new Uint8Array(64),
    docHash: new Uint8Array(32),
  };
  state.authDocHashHex = null;

  const pending = addPayloads(store.dispatch.bind(store), store.getState.bind(store));
  resetAll(store.dispatch.bind(store));
  await pending;

  const finalState = store.getState();
  assert.equal(finalState.mainFrames.size, 0);
  assert.equal(finalState.ciphertext, null);
  assert.equal(finalState.cipherDocHashHex, null);
  assert.equal(finalState.authStatus, "missing");
  assert.equal(finalState.frameStatus.lines[0], "State cleared.");
});
