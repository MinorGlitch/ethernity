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

import { inspectEncryptedDownload } from "./recovery_input.js";
import { makeZip } from "../lib/zip.js";
import { reassembleCiphertext } from "./frames_cipher.js";
import { downloadBlob, downloadBytes } from "./io.js";
import { dispatchPatch, setErrorStatus, setLineStatus } from "./state_actions.js";

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
  const current = getState();
  const patch = {};
  try {
    const { record, error } = inspectEncryptedDownload(current);
    if (error) throw new Error(error);
    const ciphertext = reassembleCiphertext(record);
    downloadBytes(ciphertext, "ciphertext.age");
    setLineStatus(patch, "frameStatus", "Download started: ciphertext.age.", "ok");
  } catch (err) {
    setErrorStatus(patch, "frameStatus", err);
  }
  dispatchPatch(dispatch, getState, patch);
}

export function downloadDecryptedBackup(_dispatch, getState) {
  const current = getState();
  if (!current.decryptedBackup) return;
  downloadBytes(current.decryptedBackup, "decrypted_backup.bin");
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
  const current = getState();
  const patch = {};
  if (!current.extractedFiles.length) return;
  try {
    const zipBlob = makeZip(current.extractedFiles);
    downloadBlob(zipBlob, "recovered_files.zip");
    setLineStatus(patch, "extractStatus", "Download started: recovered_files.zip.", "ok");
  } catch (err) {
    setErrorStatus(
      patch,
      "extractStatus",
      err,
      "The ZIP could not be created. Try downloading the files individually.",
    );
  }
  dispatchPatch(dispatch, getState, patch);
}
