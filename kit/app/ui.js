import { SHARD_KEY_PASSPHRASE, SHARD_KEY_SIGNING_SEED } from "./constants.js";
import { listMissing } from "./frames.js";

const UI_IDS = {
  elements: {
    payloadText: "payload-text",
    shardPayloadText: "shard-payload-text",
    resetButton: "reset-button",
    downloadCipherButton: "download-cipher",
    frameStatus: "frame-status",
    frameDiagnostics: "frame-diagnostics",
    copyResultButton: "copy-result",
    recoveredLabel: "recovered-label",
    recoveredSecret: "recovered-secret",
    shardStatus: "shard-status",
    shardDocHash: "shard-doc-hash",
    shardDocId: "shard-doc-id",
    shardSignPub: "shard-sign-pub",
    shardDiagnostics: "shard-diagnostics",
    ciphertextSourceLabel: "ciphertext-source-label",
    ciphertextSourceDetail: "ciphertext-source-detail",
    passphraseInput: "passphrase-input",
    decryptButton: "decrypt-button",
    decryptStatus: "decrypt-status",
    envelopeSourceLabel: "envelope-source-label",
    envelopeSourceDetail: "envelope-source-detail",
    extractButton: "extract-button",
    downloadEnvelopeButton: "download-envelope",
    outputSubtitle: "output-subtitle",
    clearOutputButton: "clear-output",
    downloadZipButton: "download-zip",
    extractStatus: "extract-status",
    outputTableBody: "output-table-body",
  },
};

export const INPUT_BINDINGS = [
  ["payloadText", "payloadText"],
  ["shardPayloadText", "shardPayloadText"],
  ["passphraseInput", "agePassphrase"],
];

export const INPUT_VALUE_BINDINGS = [
  ...INPUT_BINDINGS,
  ["recoveredSecret", "recoveredShardSecret"],
];

export const STATUS_BINDINGS = [
  ["frameStatus", "frameStatus"],
  ["shardStatus", "shardStatus"],
  ["decryptStatus", "decryptStatus"],
  ["extractStatus", "extractStatus"],
];

export const RESET_INPUT_KEYS = [
  "payloadText",
  "shardPayloadText",
];

export function formatBytes(value) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unitIdx = 0;
  while (size >= 1024 && unitIdx < units.length - 1) {
    size /= 1024;
    unitIdx += 1;
  }
  const precision = size >= 100 || unitIdx === 0 ? 0 : size >= 10 ? 1 : 2;
  return `${size.toFixed(precision)} ${units[unitIdx]}`;
}

function sumFrameBytes(frames) {
  let total = 0;
  for (const frame of frames.values()) {
    total += frame.data.length;
  }
  return total;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setStatusElement(element, status) {
  const text = status.lines.length ? status.lines.join("\n") : "";
  const className = status.type ? `status ${status.type}` : "status";
  element.className = className;
  element.textContent = text;
}

function setInputValue(element, value, force = false) {
  if (!element) return;
  if (force || document.activeElement !== element) {
    const safeValue = value ?? "";
    if (element.value !== safeValue) {
      element.value = safeValue;
    }
  }
}

function renderDiagnostics(container, items) {
  const list = el("div", "diag-list");
  for (const item of items) {
    const row = el("div", "diag-row");
    row.append(
      el("div", "diag-label", item.label),
      el("div", "diag-value", item.value ?? "-")
    );
    list.appendChild(row);
  }
  container.innerHTML = "";
  container.appendChild(list);
}

function renderOutputTable(ui, files) {
  const tbody = ui.outputTableBody;
  tbody.innerHTML = "";
  if (!files.length) {
    const row = el("tr", "empty-row");
    const cell = el("td", null, "No files extracted yet.");
    cell.colSpan = 3;
    row.appendChild(cell);
    tbody.appendChild(row);
    return;
  }
  files.forEach((file, index) => {
    const row = el("tr");
    row.append(
      el("td", null, file.path),
      el("td", null, formatBytes(file.data.length))
    );
    const actionCell = el("td");
    const button = el("button", "secondary", "Download");
    button.dataset.downloadIndex = String(index);
    actionCell.appendChild(button);
    row.appendChild(actionCell);
    tbody.appendChild(row);
  });
}

export function bindUI() {
  const get = (id) => {
    const node = document.getElementById(id);
    if (!node) {
      throw new Error(`Missing element #${id}`);
    }
    return node;
  };

  const mapIds = (ids) => Object.fromEntries(Object.entries(ids).map(([key, id]) => [key, get(id)]));

  const ui = {};
  Object.entries(UI_IDS.elements).forEach(([key, id]) => {
    ui[key] = get(id);
  });
  return ui;
}

export function updateUI(state, ui) {
  const missing = state.total ? listMissing(state.total, state.mainFrames) : [];
  const shardMatch = state.docIdHex && state.shardDocIdHex
    ? (state.docIdHex === state.shardDocIdHex ? "yes" : "no")
    : "-";
  const shardKeyLabel = state.shardKeyType === SHARD_KEY_PASSPHRASE
    ? "passphrase"
    : state.shardKeyType === SHARD_KEY_SIGNING_SEED
      ? "signing key"
      : "-";
  const shardDocIdInput = state.shardDocIdHex || state.docIdHex || state.authDocIdHex || "";
  const shardDocHashInput = state.shardDocHashHex || state.authDocHashHex || state.cipherDocHashHex || "";
  const shardSignPubInput = state.shardSignPubHex || state.authSignPubHex || "";
  const canRecoverShard = state.shardThreshold && state.shardFrames.size >= state.shardThreshold;
  const canDownloadCipher = state.total && state.mainFrames.size === state.total;
  const collectedCiphertextAvailable = Boolean(state.ciphertext)
    || (state.total && state.mainFrames.size === state.total);
  const collectedCiphertextSize = collectedCiphertextAvailable
    ? (state.ciphertext ? state.ciphertext.length : sumFrameBytes(state.mainFrames))
    : 0;
  const canDecryptCiphertext = state.agePassphrase.trim().length > 0
    && collectedCiphertextAvailable;
  const decryptedEnvelopeAvailable = Boolean(state.decryptedEnvelope);
  const canExtractEnvelope = decryptedEnvelopeAvailable;
  const ciphertextSource = {
    label: "Collected ciphertext",
    detail: collectedCiphertextAvailable
      ? `${formatBytes(collectedCiphertextSize)}  |  ${state.mainFrames.size}/${state.total ?? "?"} frames`
      : `Waiting for frames (${state.mainFrames.size}/${state.total ?? "?"})`,
  };
  const envelopeSource = decryptedEnvelopeAvailable
    ? {
      label: "Decrypted envelope",
      detail: `${state.decryptedEnvelopeSource || "From decrypted ciphertext"}  |  ${formatBytes(state.decryptedEnvelope.length)}`,
    }
    : {
      label: "Decrypted envelope",
      detail: "No decrypted envelope yet",
    };
  INPUT_VALUE_BINDINGS.forEach(([uiKey, stateKey]) => {
    setInputValue(ui[uiKey], state[stateKey]);
  });

  ui.recoveredLabel.textContent = state.shardKeyType === SHARD_KEY_SIGNING_SEED
    ? "Recovered signing key (hex)"
    : state.shardKeyType === SHARD_KEY_PASSPHRASE
      ? "Recovered passphrase"
      : "Recovered secret";

  [
    [ui.shardDocHash, shardDocHashInput],
    [ui.shardDocId, shardDocIdInput],
    [ui.shardSignPub, shardSignPubInput],
  ].forEach(([element, value]) => setInputValue(element, value, true));

  STATUS_BINDINGS.forEach(([uiKey, stateKey]) => {
    setStatusElement(ui[uiKey], state[stateKey]);
  });

  renderDiagnostics(ui.frameDiagnostics, [
    { label: "Doc ID", value: state.docIdHex ?? "(unknown)" },
    { label: "Frames", value: `${state.mainFrames.size}/${state.total ?? "?"}` },
    { label: "Missing", value: missing.length ? missing.join(", ") : "-" },
    { label: "Duplicates", value: `${state.duplicates}` },
    { label: "Conflicts", value: `${state.conflicts}` },
    { label: "Ignored", value: `${state.ignored}` },
    { label: "Errors", value: `${state.errors}` },
    { label: "Auth status", value: state.authStatus },
  ]);

  renderDiagnostics(ui.shardDiagnostics, [
    { label: "Key type", value: shardKeyLabel },
    { label: "Quorum", value: `${state.shardThreshold ?? "?"} of ${state.shardShares ?? "?"}` },
    { label: "Collected", value: `${state.shardFrames.size}` },
    { label: "Main doc match", value: shardMatch },
    { label: "Duplicates", value: `${state.shardDuplicates}` },
    { label: "Conflicts", value: `${state.shardConflicts}` },
    { label: "Errors", value: `${state.shardErrors}` },
  ]);

  ui.copyResultButton.disabled = !state.recoveredShardSecret;
  ui.downloadCipherButton.disabled = !canDownloadCipher;
  ui.decryptButton.disabled = !canDecryptCiphertext;
  ui.extractButton.disabled = !canExtractEnvelope;
  ui.downloadEnvelopeButton.disabled = !decryptedEnvelopeAvailable;
  ui.clearOutputButton.disabled = !state.extractedFiles.length;
  ui.downloadZipButton.disabled = !state.extractedFiles.length;

  ui.ciphertextSourceLabel.textContent = ciphertextSource.label;
  ui.ciphertextSourceDetail.textContent = ciphertextSource.detail;
  ui.envelopeSourceLabel.textContent = envelopeSource.label;
  ui.envelopeSourceDetail.textContent = envelopeSource.detail;

  const count = state.extractedFiles.length;
  const totalBytes = state.extractedFiles.reduce((sum, file) => sum + file.data.length, 0);
  ui.outputSubtitle.textContent = count
    ? `${count} file(s)  |  ${formatBytes(totalBytes)}`
    : "No files extracted yet";
  renderOutputTable(ui, state.extractedFiles);
}
