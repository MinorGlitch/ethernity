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

import { FRAME_TYPE_AUTH, FRAME_TYPE_KEY, FRAME_TYPE_MAIN } from "./constants.js";
import { bytesEqual, bytesToHex } from "../lib/encoding.js";
import { addAuthDocumentFrame, addMainDocumentFrame } from "./document_store.js";
import { decodeShardPayload } from "./frames_protocol.js";

export function addFrame(state, frame) {
  if (frame.frameType === FRAME_TYPE_AUTH) {
    addAuthDocumentFrame(state, frame);
    return;
  }
  if (frame.frameType !== FRAME_TYPE_MAIN) {
    state.ignored += 1;
    return;
  }
  addMainDocumentFrame(state, frame);
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
    state.shardVersion = payload.version;
    state.shardThreshold = payload.threshold;
    state.shardShares = payload.shareCount;
    state.shardKeyType = payload.keyType;
    state.shardSecretLen = payload.secretLen;
    state.shardDocHashHex = bytesToHex(payload.docHash);
    state.shardSignPubHex = bytesToHex(payload.signPub);
    state.shardSetIdHex = payload.shardSetId ? bytesToHex(payload.shardSetId) : null;
  } else {
    if (state.shardVersion !== payload.version) {
      state.shardConflicts += 1;
      return;
    }
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
    const shardSetIdHex = payload.shardSetId ? bytesToHex(payload.shardSetId) : null;
    if (state.shardSetIdHex !== shardSetIdHex) {
      state.shardConflicts += 1;
      return;
    }
  }

  const existing = state.shardFrames.get(payload.shareIndex);
  if (existing) {
    if (!bytesEqual(existing.share, payload.share)) {
      state.shardConflicts += 1;
    } else if (!bytesEqual(existing.signature, payload.signature)) {
      state.shardConflicts += 1;
      state.shardFrames.set(payload.shareIndex, payload);
    } else {
      state.shardDuplicates += 1;
    }
    return;
  }
  state.shardFrames.set(payload.shareIndex, payload);
}
