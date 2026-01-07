import { decryptAgePassphrase } from "../lib/age_scrypt.js";
import {
  parseAutoPayload,
  parseAutoShard,
  reassembleCiphertext,
  syncCollectedCiphertext,
} from "./frames.js";
import { updateAuthStatus } from "./auth.js";
import { extractFiles } from "./envelope.js";
import { downloadBlob, downloadBytes } from "./io.js";
import { setStatus, resetState, bumpError } from "./state.js";
import { autoRecoverShardSecret } from "./shards.js";
import { INPUT_BINDINGS, RESET_INPUT_KEYS, formatBytes } from "./ui.js";
import { makeZip } from "../lib/zip.js";

function parseTextWithErrors(state, text, parseFn, errorKey) {
  let added = 0;
  try {
    added += parseFn(state, text);
  } catch (err) {
    bumpError(state, errorKey);
  }
  return added;
}

function clearInputValues(ui, keys) {
  for (const key of keys) {
    if (ui[key]) ui[key].value = "";
  }
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

async function finalizeMainCollection(state, updateUI, statusLines) {
  setStatus(state, "frameStatus", statusLines);
  await updateAuthStatus(state);
  syncCollectedCiphertext(state);
  updateUI();
}

function finalizeShardCollection(state, updateUI, statusLines) {
  const recovered = autoRecoverShardSecret(state, statusLines);
  if (!recovered) {
    setStatus(state, "shardStatus", statusLines);
  }
  updateUI();
}

export function createHandlers({ state, ui, updateUI }) {
  async function handleAddPayloads() {
    const addedFromText = parseTextWithErrors(state, state.payloadText, parseAutoPayload, "errors");
    await finalizeMainCollection(state, updateUI, [
      `Added ${addedFromText} input(s).`,
      state.total ? "Ready to download when all frames are collected." : "Waiting for more frames.",
    ]);
  }

  async function handleAddShardPayloads() {
    const addedFromText = parseTextWithErrors(state, state.shardPayloadText, parseAutoShard, "shardErrors");
    const statusLines = [
      `Added ${addedFromText} shard input(s).`,
      state.shardThreshold ? "Ready to recover when enough shards are collected." : "Waiting for shard metadata.",
    ];
    finalizeShardCollection(state, updateUI, statusLines);
  }

  async function handleCopyPassphrase() {
    const text = state.recoveredShardSecret;
    if (!text) return;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        setStatus(state, "shardStatus", ["Result copied to clipboard."], "ok");
        updateUI();
        return;
      }
    } catch (err) {
      // fall back to selection
    }
    ui.recoveredSecret.focus();
    ui.recoveredSecret.select();
    setStatus(state, "shardStatus", ["Select and copy the result manually."], "warn");
    updateUI();
  }

  function handleDownloadCipher() {
    try {
      const ciphertext = reassembleCiphertext(state);
      state.ciphertext = ciphertext;
      downloadBytes(ciphertext, "ciphertext.age");
      setStatus(state, "frameStatus", ["Ciphertext downloaded as ciphertext.age"], "ok");
    } catch (err) {
      setStatus(state, "frameStatus", [String(err)], "error");
    }
    updateUI();
  }

  async function handleDecryptCiphertext() {
    if (!state.agePassphrase.trim()) {
      setStatus(state, "decryptStatus", ["Passphrase is required."], "warn");
      updateUI();
      return;
    }
    clearRecoveredOutput(state);
    clearDecryptedEnvelope(state);
    setStatus(state, "decryptStatus", ["Decrypting ciphertext..."]);
    updateUI();
    try {
      if (!state.ciphertext && state.total && state.mainFrames.size === state.total) {
        state.ciphertext = reassembleCiphertext(state);
      }
      const bytes = state.ciphertext;
      if (!bytes) {
        throw new Error("Collected ciphertext not available yet.");
      }
      const sourceLabel = "Collected ciphertext";
      const plaintext = await decryptAgePassphrase(bytes, state.agePassphrase);
      state.decryptedEnvelope = plaintext;
      state.decryptedEnvelopeSource = sourceLabel;
      const result = await extractFiles(plaintext);
      applyExtractResult(state, result);
      setStatus(state, "decryptStatus", [
        `Decrypted ${formatBytes(plaintext.length)} envelope.`,
        `Extracted ${result.files.length} file(s).`,
      ], "ok");
    } catch (err) {
      setStatus(state, "decryptStatus", [String(err)], "error");
    }
    updateUI();
  }

  function handleDownloadEnvelope() {
    if (!state.decryptedEnvelope) return;
    downloadBytes(state.decryptedEnvelope, "decrypted_envelope.bin");
  }

  async function handleExtract() {
    try {
      clearRecoveredOutput(state);
      if (!state.decryptedEnvelope) {
        throw new Error("No decrypted envelope available yet.");
      }
      const bytes = state.decryptedEnvelope;
      setStatus(state, "extractStatus", ["Extracting files..."]);
      updateUI();
      const result = await extractFiles(bytes);
      applyExtractResult(state, result);
    } catch (err) {
      setStatus(state, "extractStatus", [String(err)], "error");
    }
    updateUI();
  }

  function handleReset() {
    resetState(state);
    clearInputValues(ui, RESET_INPUT_KEYS);
    updateUI();
  }

  function handleDownloadExtract(event) {
    const button = event.target.closest("button[data-download-index]");
    if (!button) return;
    const index = Number(button.dataset.downloadIndex);
    const file = state.extractedFiles[index];
    if (file) {
      downloadBytes(file.data, file.path);
    }
  }

  function handleDownloadZip() {
    if (!state.extractedFiles.length) return;
    try {
      const zipBlob = makeZip(state.extractedFiles);
      downloadBlob(zipBlob, "recovered_files.zip");
      setStatus(state, "extractStatus", [
        `Downloaded ${state.extractedFiles.length} file(s) as ZIP.`,
      ], "ok");
    } catch (err) {
      setStatus(state, "extractStatus", [String(err)], "error");
    }
    updateUI();
  }

  function bind() {
    INPUT_BINDINGS.forEach(([uiKey, stateKey]) => {
      ui[uiKey].addEventListener("input", () => {
        state[stateKey] = ui[uiKey].value;
      });
    });

    [
      ["add-payloads", handleAddPayloads],
      ["add-shard-payloads", handleAddShardPayloads],
    ].forEach(([id, handler]) => {
      const node = document.getElementById(id);
      if (!node) throw new Error(`Missing element #${id}`);
      node.addEventListener("click", handler);
    });

    [
      [ui.resetButton, "click", handleReset],
      [ui.downloadCipherButton, "click", handleDownloadCipher],
      [ui.copyResultButton, "click", handleCopyPassphrase],
      [ui.decryptButton, "click", handleDecryptCiphertext],
      [ui.extractButton, "click", handleExtract],
      [ui.downloadEnvelopeButton, "click", handleDownloadEnvelope],
      [ui.downloadZipButton, "click", handleDownloadZip],
    ].forEach(([element, event, handler]) => {
      element.addEventListener(event, handler);
    });

    ui.clearOutputButton.addEventListener("click", () => {
      clearRecoveredOutput(state);
      updateUI();
    });
    ui.outputTableBody.addEventListener("click", handleDownloadExtract);
  }

  return { bind };
}
