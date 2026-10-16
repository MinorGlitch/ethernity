/*
 * Copyright (C) 2026 Alex Stoyanov
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

import { decryptAgePassphrase, SCRYPT_WORKER_UNAVAILABLE } from "../lib/age_scrypt.js";
import { RecoveryError, asRecoveryError } from "../lib/errors.js";
import { recoverLatestFromEncryptedDocuments } from "./extensions/recovery.js";

export const SCRYPT_WORKER_WALL_TIME_MS = 120_000;
let workerSource = "";

// The page and worker run the same compiled script. Crypto dependencies are included once
// in the offline HTML, rather than embedded again inside a separately compiled worker.
export function configureRecoveryWorker(source) {
  workerSource = source;
}

export function recoverDocuments(documents, passphrase, decrypt, options) {
  if (typeof window === "undefined") {
    return recoverLatestFromEncryptedDocuments(documents, passphrase, decrypt, options);
  }
  return recoverInWorker(documents, passphrase, options);
}

export function recoverInWorker(documents, passphrase, { signal, ...options } = {}) {
  return new Promise((resolve, reject) => {
    let worker;
    let workerUrl;
    let timer;
    let settled = false;
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      worker?.terminate();
      if (workerUrl) URL.revokeObjectURL(workerUrl);
      if (error) reject(error);
      else resolve(result);
    };
    const unavailable = () =>
      finish(new RecoveryError("SCRYPT_UNAVAILABLE", SCRYPT_WORKER_UNAVAILABLE));
    const abort = () => finish(new RecoveryError("CANCELLED", "recovery was cancelled"));
    const watchScrypt = (active) => {
      clearTimeout(timer);
      if (active) {
        timer = setTimeout(
          () =>
            finish(
              new RecoveryError(
                "RECOVERY_RESOURCE_LIMIT",
                "scrypt worker exceeded its wall-time limit",
              ),
            ),
          SCRYPT_WORKER_WALL_TIME_MS,
        );
      }
    };
    if (signal?.aborted) {
      abort();
      return;
    }
    try {
      if (!workerSource) {
        unavailable();
        return;
      }
      workerUrl = URL.createObjectURL(new Blob([workerSource], { type: "text/javascript" }));
      worker = new Worker(workerUrl);
      // Also bound startup; once ready, the existing time limit applies to each KDF,
      // not the combined duration of a multi-document recovery.
      timer = setTimeout(unavailable, SCRYPT_WORKER_WALL_TIME_MS);
      worker.onmessage = ({ data }) => {
        if (settled) return;
        switch (data?.type) {
          case "ready":
            clearTimeout(timer);
            break;
          case "scrypt":
            watchScrypt(data.active);
            break;
          case "result":
            finish(null, data.result);
            break;
          case "error":
            finish(new RecoveryError(data.code, data.message));
            break;
          default:
            unavailable();
        }
      };
      worker.onerror = unavailable;
      worker.onmessageerror = unavailable;
      signal?.addEventListener("abort", abort, { once: true });
      worker.postMessage({
        documents,
        passphrase,
        options: {
          extensionTarget: options.extensionTarget,
          freshnessUnknownAcknowledged: options.freshnessUnknownAcknowledged,
        },
      });
    } catch {
      unavailable();
    }
  });
}

export function serveRecoveryWorker() {
  const decrypt = (ciphertext, passphrase) =>
    decryptAgePassphrase(ciphertext, passphrase, {
      onScrypt: (active) => globalThis.postMessage({ type: "scrypt", active }),
    });
  decrypt.preflightBatch = decryptAgePassphrase.preflightBatch;
  globalThis.onmessage = async ({ data }) => {
    // One recovery per worker. Terminating it cancels all expensive work and discards keys.
    globalThis.onmessage = null;
    try {
      const result = await recoverLatestFromEncryptedDocuments(
        data.documents,
        data.passphrase,
        decrypt,
        data.options,
      );
      const buffers = new Set(result.files.map((file) => file.data.buffer));
      if (result.decryptedBackup) buffers.add(result.decryptedBackup.buffer);
      globalThis.postMessage({ type: "result", result }, [...buffers]);
    } catch (err) {
      const error = asRecoveryError(err);
      globalThis.postMessage({ type: "error", code: error.code, message: error.message });
    }
  };
  globalThis.postMessage({ type: "ready" });
}
