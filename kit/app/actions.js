import { decryptAgePassphrase } from "../lib/age_scrypt.js";
import { makeZip } from "../lib/zip.js";
import { updateAuthStatus } from "./auth.js";
import { extractFiles } from "./envelope.js";
import {
  parseAutoPayload,
  parseAutoShard,
  reassembleCiphertext,
  syncCollectedCiphertext,
} from "./frames.js";
import { downloadBlob, downloadBytes } from "./io.js";
import { autoRecoverShardSecret } from "./shards.js";
import { bumpError, cloneState, createInitialState, setStatus } from "./state/initial.js";
import { formatBytes } from "./state/selectors.js";

function dispatchState(dispatch, state) {
  dispatch({ type: "REPLACE", state });
}

function parseTextWithErrors(state, text, parseFn, errorKey) {
  let added = 0;
  try {
    added += parseFn(state, text);
  } catch (err) {
    bumpError(state, errorKey);
  }
  return added;
}

function clearRecoveredOutput(state) {
  state.extractedFiles = [];
  setStatus(state, "extractStatus", []);
}

function clearDecryptedEnvelope(state) {
  state.decryptedEnvelope = null;
  state.decryptedEnvelopeSource = "";
}

function applyExtractResult(state, result) {
  state.extractedFiles = result.files;
  setStatus(state, "extractStatus", [`Extracted ${result.files.length} file(s).`], "ok");
}

export function updateField(dispatch, getState, key, value) {
  const next = cloneState(getState());
  next[key] = value;
  dispatchState(dispatch, next);
}

export function resetAll(dispatch) {
  dispatchState(dispatch, createInitialState());
}

export async function addPayloads(dispatch, getState) {
  const base = cloneState(getState());
  const added = parseTextWithErrors(base, base.payloadText, parseAutoPayload, "errors");
  setStatus(base, "frameStatus", [
    `Added ${added} input(s).`,
    base.total
      ? "Ready to download when all frames are collected."
      : "Waiting for more frames.",
  ]);
  dispatchState(dispatch, base);

  const next = cloneState(base);
  await updateAuthStatus(next);
  syncCollectedCiphertext(next);
  dispatchState(dispatch, next);
}

export function addShardPayloads(dispatch, getState) {
  let added = 0;
  const next = cloneState(getState());
  added = parseTextWithErrors(next, next.shardPayloadText, parseAutoShard, "shardErrors");
  const statusLines = [
    `Added ${added} shard input(s).`,
    next.shardThreshold
      ? "Ready to recover when enough shards are collected."
      : "Waiting for shard metadata.",
  ];
  const recovered = autoRecoverShardSecret(next, statusLines);
  if (!recovered) {
    setStatus(next, "shardStatus", statusLines);
  }
  dispatchState(dispatch, next);
}

export async function copyRecoveredSecret(dispatch, getState) {
  const current = getState();
  const text = current.recoveredShardSecret;
  if (!text) {
    return;
  }
  let statusLines = [];
  let statusType = "ok";
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      statusLines = ["Result copied to clipboard."];
    } else {
      statusLines = ["Select and copy the result manually."];
      statusType = "warn";
    }
  } catch (err) {
    statusLines = ["Select and copy the result manually."];
    statusType = "warn";
  }
  const next = cloneState(getState());
  setStatus(next, "shardStatus", statusLines, statusType);
  dispatchState(dispatch, next);
}

export function downloadCipher(dispatch, getState) {
  const next = cloneState(getState());
  try {
    const ciphertext = reassembleCiphertext(next);
    next.ciphertext = ciphertext;
    downloadBytes(ciphertext, "ciphertext.age");
    setStatus(next, "frameStatus", ["Ciphertext downloaded as ciphertext.age"], "ok");
  } catch (err) {
    setStatus(next, "frameStatus", [String(err)], "error");
  }
  dispatchState(dispatch, next);
}

export async function decryptCiphertext(dispatch, getState) {
  const base = cloneState(getState());
  if (!base.agePassphrase.trim()) {
    setStatus(base, "decryptStatus", ["Passphrase is required."], "warn");
    dispatchState(dispatch, base);
    return;
  }
  clearRecoveredOutput(base);
  clearDecryptedEnvelope(base);
  setStatus(base, "decryptStatus", ["Decrypting ciphertext..."]);
  dispatchState(dispatch, base);

  const next = cloneState(base);
  try {
    if (!next.ciphertext && next.total && next.mainFrames.size === next.total) {
      next.ciphertext = reassembleCiphertext(next);
    }
    const bytes = next.ciphertext;
    if (!bytes) {
      throw new Error("Collected ciphertext not available yet.");
    }
    const plaintext = await decryptAgePassphrase(bytes, next.agePassphrase);
    next.decryptedEnvelope = plaintext;
    next.decryptedEnvelopeSource = "Collected ciphertext";
    const result = extractFiles(plaintext);
    applyExtractResult(next, result);
    setStatus(next, "decryptStatus", [
      `Decrypted ${formatBytes(plaintext.length)} envelope.`,
      `Extracted ${result.files.length} file(s).`,
    ], "ok");
  } catch (err) {
    setStatus(next, "decryptStatus", [String(err)], "error");
  }
  dispatchState(dispatch, next);
}

export function downloadEnvelope(dispatch, getState) {
  const current = getState();
  if (!current.decryptedEnvelope) return;
  downloadBytes(current.decryptedEnvelope, "decrypted_envelope.bin");
}

export function extractEnvelope(dispatch, getState) {
  const base = cloneState(getState());
  try {
    clearRecoveredOutput(base);
    if (!base.decryptedEnvelope) {
      throw new Error("No decrypted envelope available yet.");
    }
    setStatus(base, "extractStatus", ["Extracting files..."]);
    dispatchState(dispatch, base);
    const next = cloneState(base);
    const result = extractFiles(next.decryptedEnvelope);
    applyExtractResult(next, result);
    dispatchState(dispatch, next);
  } catch (err) {
    setStatus(base, "extractStatus", [String(err)], "error");
    dispatchState(dispatch, base);
  }
}

export function clearOutput(dispatch, getState) {
  const next = cloneState(getState());
  clearRecoveredOutput(next);
  dispatchState(dispatch, next);
}

export function downloadExtract(dispatch, getState, index) {
  const current = getState();
  const file = current.extractedFiles[index];
  if (file) {
    downloadBytes(file.data, file.path);
  }
}

export function downloadZip(dispatch, getState) {
  const next = cloneState(getState());
  if (!next.extractedFiles.length) return;
  try {
    const zipBlob = makeZip(next.extractedFiles);
    downloadBlob(zipBlob, "recovered_files.zip");
    setStatus(next, "extractStatus", [
      `Downloaded ${next.extractedFiles.length} file(s) as ZIP.`,
    ], "ok");
  } catch (err) {
    setStatus(next, "extractStatus", [String(err)], "error");
  }
  dispatchState(dispatch, next);
}
