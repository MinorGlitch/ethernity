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

import { RecoveryError } from "../lib/errors.js";
import { setStatus } from "./state/initial.js";

export function dispatchPatch(dispatch, getState, patch) {
  const current = getState();
  dispatch({ type: "PATCH_STATE", patch, baseRevision: current.revision });
}

export function setLineStatus(state, key, line, type = "") {
  setStatus(state, key, [line], type);
}

export function setErrorStatus(
  state,
  key,
  error,
  message = error instanceof Error ? error.message : String(error),
) {
  setLineStatus(state, key, message, "error");
  const detail = error instanceof Error ? error.message : String(error);
  if (detail !== message) state[key].details = [detail];
  if (error instanceof RecoveryError) {
    state[key].code = error.code;
    state[key].stage = error.stage;
  }
}

export function clearRecoveryResult(state) {
  state.extractedFiles = [];
  state.decryptedBackup = null;
  setStatus(state, "extractStatus", []);
  setStatus(state, "decryptStatus", []);
}
