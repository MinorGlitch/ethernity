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
import { addAuthDocumentFrame, addMainDocumentFrame } from "./document_store.js";
import { decodeShardPayload } from "./frames_protocol.js";
import { addShardPayloadFrame } from "./shard_store.js";

export function addFrame(state, frame) {
  if (frame.frameType === FRAME_TYPE_AUTH) {
    return addAuthDocumentFrame(state, frame);
  }
  if (frame.frameType !== FRAME_TYPE_MAIN) {
    state.ignored += 1;
    return false;
  }
  return addMainDocumentFrame(state, frame);
}

export function addShardFrame(state, frame) {
  if (frame.frameType !== FRAME_TYPE_KEY) {
    state.shardErrors += 1;
    return false;
  }
  if (frame.total !== 1 || frame.index !== 0) {
    state.shardErrors += 1;
    return false;
  }
  let payload;
  try {
    payload = decodeShardPayload(frame.data);
  } catch {
    state.shardErrors += 1;
    return false;
  }
  return addShardPayloadFrame(state, frame, payload);
}
