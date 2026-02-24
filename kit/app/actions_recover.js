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

import { decryptAgePassphrase } from "../lib/age_scrypt.js";
import { extractFiles } from "./envelope.js";
import { reassembleCiphertext } from "./frames_cipher.js";
import { formatBytes } from "./format.js";
import { cloneState } from "./state/initial.js";
import {
  applyExtractResult,
  clearDecryptedEnvelope,
  clearRecoveredOutput,
  cloneLatest,
  dispatchPatch,
  dispatchState,
  setErrorStatus,
  setLineStatus,
} from "./actions_common.js";

export async function decryptCiphertext(dispatch, getState) {
  const base = cloneState(getState());
  if (!base.agePassphrase.trim()) {
    setLineStatus(base, "decryptStatus", "Passphrase required.", "warn");
    dispatchState(dispatch, base);
    return;
  }
  const prep = cloneState(base);
  clearRecoveredOutput(prep);
  clearDecryptedEnvelope(prep);
  let didStartDecrypt = false;
  let finalState = null;
  try {
    if (prep.conflicts > 0) {
      throw new Error("conflicting duplicate frames detected");
    }
    if (!prep.ciphertext && prep.total && prep.mainFrames.size === prep.total) {
      prep.ciphertext = reassembleCiphertext(prep);
    }
    const bytes = prep.ciphertext;
    if (!bytes) {
      throw new Error("Collected ciphertext not available yet.");
    }
    prep.isDecrypting = true;
    setLineStatus(prep, "decryptStatus", "Unlocking backup...");
    dispatchState(dispatch, prep);
    didStartDecrypt = true;

    const plaintext = await decryptAgePassphrase(bytes, prep.agePassphrase);
    const result = extractFiles(plaintext);
    const next = cloneLatest(getState);
    next.decryptedEnvelope = plaintext;
    next.decryptedEnvelopeSource = "Collected ciphertext";
    applyExtractResult(next, result);
    next.isDecrypting = false;
    next.recoveryComplete = true;
    next.decryptStatus = {
      lines: [
        "Recovery complete.",
        `${result.files.length} file(s) recovered (${formatBytes(plaintext.length)}).`,
      ],
      type: "ok",
    };
    if (next.agePassphrase === base.agePassphrase) {
      next.agePassphrase = "";
    }
    finalState = next;
  } catch (err) {
    const next = didStartDecrypt ? cloneLatest(getState) : prep;
    next.isDecrypting = false;
    const errorMsg = String(err);
    const friendlyError = errorMsg.includes("password")
      ? "Incorrect passphrase."
      : errorMsg.includes("decrypt")
        ? "Could not unlock backup. Check passphrase."
        : errorMsg;
    setLineStatus(next, "decryptStatus", friendlyError, "error");
    finalState = next;
  }
  dispatchState(dispatch, finalState);
}

export function extractEnvelope(dispatch, getState) {
  const base = cloneState(getState());
  try {
    clearRecoveredOutput(base);
    if (!base.decryptedEnvelope) {
      throw new Error("No decrypted envelope available yet.");
    }
    const result = extractFiles(base.decryptedEnvelope);
    applyExtractResult(base, result);
    dispatchState(dispatch, base);
  } catch (err) {
    setErrorStatus(base, "extractStatus", err);
    dispatchState(dispatch, base);
  }
}

export function clearOutput(dispatch, getState) {
  dispatchPatch(dispatch, getState, { extractedFiles: [], extractStatus: { lines: [], type: "" } });
}
