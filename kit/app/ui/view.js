/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */
import { SCANNER_ENABLED } from "#kit-scanner";
import { formatBytes } from "../format.js";
import {
  selectActionState,
  selectFrameCollectionComplete,
  selectFrameDiagnostics,
  selectOutputSummary,
  selectRecoveredLabel,
  selectShardDiagnostics,
  selectShardInputs,
} from "../state/selectors.js";
import {
  button,
  field,
  setButton,
  setText,
  setValue,
  statusMarkup,
  updateDiagnostics,
  updateStatus,
} from "./controls.js";

function step(title, summary, body) {
  return `<section class="panel step-shell"><div class="step-head">
    <h2 class="step-heading">${title}</h2>${summary ? `<p class="step-summary">${summary}</p>` : ""}
    </div><div class="step-content"><div class="step-layout">${body}</div></div></section>`;
}

function collector(id, inputId, label, action, extra = "") {
  return `<div id="${id}-input" class="step-section">
    ${field(inputId, label, { textarea: true })}<div id="${id}-hint" class="hint" hidden></div>
    <div class="collector-controls"><div class="row">${button(`${id}-add`, action)}</div>
      ${SCANNER_ENABLED ? `<div id="${id}-scanner" class="scan-panel"></div>` : ""}</div>${extra}</div>`;
}

export function createView(root, downloadFile) {
  root.innerHTML = `<main class="shell shell--blocked" id="offline-guard">
    <section class="offline-guard-screen" aria-labelledby="offline-guard-title"><div class="offline-guard-card">
      <h1 id="offline-guard-title" class="offline-guard-title">Recover files offline</h1>
      <p>Turn off Wi-Fi and mobile data, and unplug any network cable.</p>
      <p>Keep this tab open. It will continue when you're offline.</p>
      ${button("use-online", "Use while online", "secondary")}</div></section></main>
    <main class="shell" id="workspace" hidden><h1 class="app-title">Recovery Kit</h1><section class="workspace">
    ${step(
      "Add backup",
      SCANNER_ENABLED
        ? "Scan the QR codes or paste the text from your backup pages."
        : "Paste the text from your backup pages.",
      collector(
        "backup",
        "payload-text",
        "Backup text",
        "Add backup",
        `<div class="row actions-secondary">${button("download-cipher", "Download encrypted file", "secondary")}${button("reset", "Start over", "ghost")}</div>`,
      ) + statusMarkup("backup-status", { collection: true }),
    )}
    ${step(
      "Recovery sheets",
      "Use these to recover a passphrase or signing key. Skip this step if you already have your passphrase.",
      collector("sheets", "shard-payload-text", "Recovery sheet text", "Add sheets") +
        statusMarkup("sheets-status", {
          collection: true,
          fields:
            field("shard-doc-hash", "Backup fingerprint", { readOnly: true }) +
            field("shard-doc-id", "Document ID", { readOnly: true }) +
            field("shard-sign-pub", "Signing public key", { readOnly: true }),
        }) +
        `<div id="secret-output" class="step-section" hidden>${field("recovered-secret", "Recovered secret", { readOnly: true, textarea: true })}<div class="row">${button("copy-secret", "Copy secret", "secondary")}</div></div>`,
    )}
    ${step(
      "Recover files",
      "",
      `<div id="decrypt-input" class="step-section">
      ${field("passphrase-input", "Passphrase", { type: "password" })}
      <details id="recovery-options" class="details"><summary>Choose a version or check a fingerprint</summary><div class="step-section">
        ${field("extension-target-input", "Version to recover", { hint: "Use latest for the newest version added, root for the original, an update number, or a full fingerprint." })}
        ${field("expected-head-doc-hash-input", "Expected backup fingerprint", { hint: "Enter the full 64-character fingerprint from a record you kept separately to check the version." })}
      </div></details><div><label class="freshness-acknowledgement" for="freshness-unknown-acknowledgement"><input id="freshness-unknown-acknowledgement" type="checkbox"><span>I understand these pages may not include the newest update.</span></label></div>
      <div class="row">${button("decrypt", "Unlock backup")}${button("decrypt-root", "Recover original backup", "secondary")}</div></div>
      <div id="decrypt-result" class="step-section" hidden>${statusMarkup("decrypt-status")}<div id="raw-download" class="row actions-secondary" hidden>${button("download-raw", "Download raw data", "secondary")}</div></div>
      <div id="files-output" class="step-section" hidden><div id="files-heading" class="row row-between"><div><div class="step-section-label">Recovery complete</div><div id="output-summary" class="sub"></div></div><div class="row">${button("clear-output", "Clear", "ghost")}${button("download-zip", "Download ZIP", "secondary")}</div></div>
        ${statusMarkup("extract-status")}<table id="files-table"><thead><tr><th>Path</th><th>Size</th><th>Download</th></tr></thead><tbody></tbody></table></div>`,
    )}
    </section></main>`;
  const nodes = new Map(Array.from(root.querySelectorAll("[id]"), (node) => [node.id, node]));
  const get = (id) => nodes.get(id);
  const table = root.querySelector("tbody");
  let previous = {};
  let collectionComplete = false;

  function update(state) {
    // Collection patches replace these records. Text edits and status messages
    // keep them, so neither needs to rebuild the diagnostic rows.
    const documentsChanged =
      state.documents !== previous.documents || state.primaryDocIdHex !== previous.primaryDocIdHex;
    const shardsChanged =
      state.shardSets !== previous.shardSets ||
      state.activeShardSetKey !== previous.activeShardSetKey;
    if (documentsChanged) {
      collectionComplete = selectFrameCollectionComplete(state);
      updateDiagnostics(get("backup-status"), selectFrameDiagnostics(state));
    }
    if (shardsChanged || state.recoveredShardSecret !== previous.recoveredShardSecret) {
      updateDiagnostics(get("sheets-status"), selectShardDiagnostics(state));
    }
    const actions = selectActionState(state);
    setValue(get("payload-text"), state.payloadText);
    setValue(get("shard-payload-text"), state.shardPayloadText);
    setValue(get("passphrase-input"), state.agePassphrase);
    setValue(get("extension-target-input"), state.extensionTargetText);
    setValue(get("expected-head-doc-hash-input"), state.expectedHeadDocHashText);
    get("freshness-unknown-acknowledgement").checked = state.freshnessUnknownAcknowledged;
    get("backup-input").classList.toggle(
      "input-collapsed",
      collectionComplete && !state.payloadText.trim(),
    );
    get("sheets-input").classList.toggle(
      "input-collapsed",
      Boolean(state.recoveredShardSecret) && !state.shardPayloadText.trim(),
    );
    get("decrypt-input").classList.toggle(
      "input-collapsed",
      (actions.hasOutput || Boolean(state.decryptedBackup)) && !state.agePassphrase.length,
    );
    setButton(
      get("backup-add"),
      !state.isAddingFrames,
      "",
      state.isAddingFrames ? "Adding..." : "Add backup",
    );
    setButton(
      get("sheets-add"),
      !state.isAddingShards,
      "",
      state.isAddingShards ? "Adding..." : "Add sheets",
    );
    setButton(
      get("download-cipher"),
      actions.canDownloadCipher,
      actions.downloadCipherDisabledReason,
    );
    updateStatus(get("backup-status"), state.frameStatus);
    updateStatus(get("sheets-status"), state.shardStatus);
    const shard = selectShardInputs(state);
    setValue(get("shard-doc-hash"), shard.docHashHex);
    setValue(get("shard-doc-id"), shard.docIdHex);
    setValue(get("shard-sign-pub"), shard.signPubHex);
    get("secret-output").hidden = !state.recoveredShardSecret;
    setValue(get("recovered-secret"), state.recoveredShardSecret);
    setText(root.querySelector('label[for="recovered-secret"]'), selectRecoveredLabel(state));
    setButton(get("copy-secret"), actions.canCopyResult, "Add enough recovery sheets first.");
    setButton(
      get("decrypt"),
      actions.canDecryptCiphertext && !state.isDecrypting,
      actions.decryptDisabledReason,
      state.isDecrypting ? "Unlocking..." : "Unlock backup",
    );
    get("decrypt-root").hidden = !actions.hasMultipleDocuments;
    setButton(
      get("decrypt-root"),
      actions.canDecryptRootOnly && !state.isDecrypting,
      actions.rootOnlyDisabledReason,
      state.isDecrypting ? "Unlocking..." : "Recover original backup",
    );
    get("decrypt-result").hidden =
      !state.decryptStatus.lines.length && !actions.canDownloadDecryptedBackup;
    updateStatus(get("decrypt-status"), state.decryptStatus);
    get("raw-download").hidden = !actions.canDownloadDecryptedBackup;
    setButton(get("download-raw"), actions.canDownloadDecryptedBackup, "Unlock the backup first.");
    get("files-output").hidden = !actions.hasOutput && !state.extractStatus.lines.length;
    get("files-heading").hidden = !actions.hasOutput;
    get("files-table").hidden = !actions.hasOutput;
    setButton(get("clear-output"), actions.hasOutput);
    setButton(get("download-zip"), actions.hasOutput);
    updateStatus(get("extract-status"), state.extractStatus);
    if (state.extractedFiles !== previous.extractedFiles) {
      setText(get("output-summary"), selectOutputSummary(state));
      table.replaceChildren(
        ...state.extractedFiles.map((file, index) => {
          const row = document.createElement("tr");
          for (const text of [file.path, formatBytes(file.data.length)]) {
            const cell = document.createElement("td");
            cell.textContent = text;
            row.append(cell);
          }
          const cell = document.createElement("td");
          const download = document.createElement("button");
          download.type = "button";
          download.className = "secondary";
          download.textContent = "Download";
          download.onclick = () => downloadFile(index);
          cell.append(download);
          row.append(cell);
          return row;
        }),
      );
    }
    previous = { ...state };
  }
  function lock(locked) {
    get("offline-guard").hidden = !locked;
    get("workspace").hidden = locked;
  }
  return { get, update, lock };
}
