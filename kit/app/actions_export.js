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

import { makeZip } from "../lib/zip.js";
import { reassembleCiphertext } from "./frames_cipher.js";
import { downloadBlob, downloadBytes } from "./io.js";
import { cloneState } from "./state/initial.js";
import { dispatchState, setErrorStatus, setLineStatus } from "./actions_common.js";

function basenameForExtractPath(path) {
  const parts = path.split("/").filter(Boolean);
  return parts.at(-1) ?? "recovered.bin";
}

export function resolveExtractDownload(file) {
  const basename = basenameForExtractPath(file.path);
  if (file.path.includes("/")) {
    return {
      kind: "zip",
      filename: `${basename}.zip`,
      blob: makeZip([file]),
    };
  }
  return {
    kind: "raw",
    filename: basename,
    bytes: file.data,
  };
}

export function downloadCipher(dispatch, getState) {
  const next = cloneState(getState());
  try {
    if (next.conflicts > 0) {
      throw new Error("conflicting duplicate frames detected");
    }
    const ciphertext = reassembleCiphertext(next);
    next.ciphertext = ciphertext;
    downloadBytes(ciphertext, "ciphertext.age");
    setLineStatus(next, "frameStatus", "Downloaded ciphertext.age", "ok");
  } catch (err) {
    setErrorStatus(next, "frameStatus", err);
  }
  dispatchState(dispatch, next);
}

export function downloadEnvelope(_dispatch, getState) {
  const current = getState();
  if (!current.decryptedEnvelope) return;
  downloadBytes(current.decryptedEnvelope, "decrypted_envelope.bin");
}

export function downloadExtract(_dispatch, getState, index) {
  const current = getState();
  const file = current.extractedFiles[index];
  if (file) {
    const download = resolveExtractDownload(file);
    if (download.kind === "zip") {
      downloadBlob(download.blob, download.filename);
      return;
    }
    downloadBytes(download.bytes, download.filename);
  }
}

export function downloadZip(dispatch, getState) {
  const next = cloneState(getState());
  if (!next.extractedFiles.length) return;
  try {
    const zipBlob = makeZip(next.extractedFiles);
    downloadBlob(zipBlob, "recovered_files.zip");
    setLineStatus(
      next,
      "extractStatus",
      `Downloaded ${next.extractedFiles.length} file(s) as ZIP.`,
      "ok",
    );
  } catch (err) {
    setErrorStatus(next, "extractStatus", err);
  }
  dispatchState(dispatch, next);
}
