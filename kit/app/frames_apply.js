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

import { bytesEqual, bytesToHex } from "../lib/encoding.js";
import { FRAME_TYPE_AUTH, FRAME_TYPE_KEY, FRAME_TYPE_MAIN } from "./constants.js";
import { decodeAuthPayload, decodeShardPayload } from "./frames_protocol.js";

export function addFrame(state, frame) {
  if (frame.frameType === FRAME_TYPE_AUTH) {
    addAuthFrame(state, frame);
    return;
  }
  if (frame.frameType !== FRAME_TYPE_MAIN) {
    state.ignored += 1;
    return;
  }
  const docIdHex = bytesToHex(frame.docId);
  if (!state.docIdHex) {
    state.docIdHex = docIdHex;
  } else if (state.docIdHex !== docIdHex) {
    state.ignored += 1;
    return;
  }
  if (state.total === null) {
    state.total = frame.total;
  } else if (state.total !== frame.total) {
    state.conflicts += 1;
    return;
  }
  if (state.mainFrames.has(frame.index)) {
    const existing = state.mainFrames.get(frame.index);
    if (!bytesEqual(existing.data, frame.data) || existing.total !== frame.total) {
      state.conflicts += 1;
    } else {
      state.duplicates += 1;
    }
    return;
  }
  state.mainFrames.set(frame.index, frame);
  state.ciphertext = null;
  state.cipherDocHashHex = null;
}

export function addAuthFrame(state, frame) {
  if (frame.frameType !== FRAME_TYPE_AUTH) {
    state.authErrors += 1;
    return;
  }
  if (frame.total !== 1 || frame.index !== 0) {
    state.authErrors += 1;
    return;
  }
  const docIdHex = bytesToHex(frame.docId);
  if (state.authDocIdHex && state.authDocIdHex !== docIdHex) {
    state.authConflicts += 1;
    return;
  }
  if (state.docIdHex && state.docIdHex !== docIdHex) {
    state.authConflicts += 1;
    return;
  }
  let payload;
  try {
    payload = decodeAuthPayload(frame.data);
  } catch {
    state.authErrors += 1;
    state.authStatus = "invalid payload";
    return;
  }
  if (state.authPayload) {
    if (!bytesEqual(state.authPayload.signature, payload.signature)) {
      state.authConflicts += 1;
      state.authStatus = "conflicting auth payloads";
      return;
    }
    state.authDuplicates += 1;
    return;
  }
  state.authPayload = payload;
  state.authDocIdHex = docIdHex;
  state.authDocHashHex = bytesToHex(payload.docHash);
  state.authSignPubHex = bytesToHex(payload.signPub);
  state.authSignatureHex = bytesToHex(payload.signature);
  state.authStatus = "pending";
}

export function addShardFrame(state, frame) {
  if (frame.frameType !== FRAME_TYPE_KEY) {
    state.shardErrors += 1;
    return;
  }
  if (frame.total !== 1 || frame.index !== 0) {
    state.shardErrors += 1;
    return;
  }
  const docIdHex = bytesToHex(frame.docId);
  if (state.docIdHex && state.docIdHex !== docIdHex) {
    state.shardConflicts += 1;
    return;
  }
  if (!state.shardDocIdHex) {
    state.shardDocIdHex = docIdHex;
  } else if (state.shardDocIdHex !== docIdHex) {
    state.shardConflicts += 1;
    return;
  }
  let payload;
  try {
    payload = decodeShardPayload(frame.data);
  } catch {
    state.shardErrors += 1;
    return;
  }
  if (state.shardThreshold === null) {
    state.shardThreshold = payload.threshold;
    state.shardShares = payload.shareCount;
    state.shardKeyType = payload.keyType;
    state.shardSecretLen = payload.secretLen;
    state.shardDocHashHex = bytesToHex(payload.docHash);
    state.shardSignPubHex = bytesToHex(payload.signPub);
  } else {
    if (state.shardThreshold !== payload.threshold || state.shardShares !== payload.shareCount) {
      state.shardConflicts += 1;
      return;
    }
    if (state.shardKeyType !== payload.keyType || state.shardSecretLen !== payload.secretLen) {
      state.shardConflicts += 1;
      return;
    }
    if (state.shardDocHashHex !== bytesToHex(payload.docHash)) {
      state.shardConflicts += 1;
      return;
    }
    if (state.shardSignPubHex !== bytesToHex(payload.signPub)) {
      state.shardConflicts += 1;
      return;
    }
  }

  const existing = state.shardFrames.get(payload.shareIndex);
  if (existing) {
    if (!bytesEqual(existing.share, payload.share)) {
      state.shardConflicts += 1;
    } else {
      state.shardDuplicates += 1;
    }
    return;
  }
  state.shardFrames.set(payload.shareIndex, payload);
}
