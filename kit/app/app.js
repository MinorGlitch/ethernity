/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */
import {
  addPayloads,
  addScannedPayload,
  addScannedShardPayload,
  addShardPayloads,
  copyRecoveredSecret,
  resetAll,
  updateField,
} from "./actions_collect.js";
import {
  downloadCipher,
  downloadDecryptedBackup,
  downloadExtract,
  downloadZip,
} from "./actions_export.js";
import { cancelActiveDecryptWork, clearOutput, decryptCiphertext } from "./actions_recover.js";
import { createInitialState } from "./state/initial.js";
import { reducer } from "./state/reducer.js";
import { createScanner, SCANNER_ENABLED } from "#kit-scanner";
import { connectCollector } from "./ui/collector_input.js";
import { createView } from "./ui/view.js";

export function mountApp(root) {
  let state = createInitialState();
  let allowOnline = false;
  let disposed = false;
  const getState = () => state;
  const view = createView(root, (index) => downloadExtract(dispatch, getState, index));
  function dispatch(action) {
    if (disposed) return;
    state = reducer(state, action);
    view.update(state);
  }
  const backup = connectCollector(
    view.get("payload-text"),
    view.get("backup-hint"),
    view.get("backup-add"),
    {
      change: (text) => updateField(dispatch, getState, "payloadText", text),
      add: () => addPayloads(dispatch, getState),
      scanned: (payload) => addScannedPayload(dispatch, getState, payload),
      addLabel: "Add backup",
    },
  );
  const sheets = connectCollector(
    view.get("shard-payload-text"),
    view.get("sheets-hint"),
    view.get("sheets-add"),
    {
      change: (text) => updateField(dispatch, getState, "shardPayloadText", text),
      add: () => addShardPayloads(dispatch, getState),
      scanned: (payload) => addScannedShardPayload(dispatch, getState, payload),
      addLabel: "Add sheets",
    },
  );
  const scanners = SCANNER_ENABLED
    ? [
        createScanner(view.get("backup-scanner"), backup.scan),
        createScanner(view.get("sheets-scanner"), sheets.scan),
      ]
    : [];
  const stopScanners = () => {
    for (const scanner of scanners) scanner.stop();
  };
  for (const [id, key] of [
    ["passphrase-input", "agePassphrase"],
    ["extension-target-input", "extensionTargetText"],
    ["expected-head-doc-hash-input", "expectedHeadDocHashText"],
  ]) {
    const input = view.get(id);
    input.oninput = () => updateField(dispatch, getState, key, input.value);
  }
  const acknowledgement = view.get("freshness-unknown-acknowledgement");
  acknowledgement.onchange = () =>
    updateField(dispatch, getState, "freshnessUnknownAcknowledged", acknowledgement.checked);
  for (const [id, action] of [
    ["download-cipher", downloadCipher],
    ["copy-secret", copyRecoveredSecret],
    ["decrypt", decryptCiphertext],
    ["download-raw", downloadDecryptedBackup],
    ["clear-output", clearOutput],
    ["download-zip", downloadZip],
  ])
    view.get(id).onclick = () => action(dispatch, getState);
  view.get("decrypt-root").onclick = () =>
    decryptCiphertext(dispatch, getState, { extensionTarget: "root" });
  view.get("reset").onclick = () => {
    stopScanners();
    backup.clearHint();
    sheets.clearHint();
    resetAll(dispatch);
  };
  function syncNetwork() {
    if (!navigator.onLine) allowOnline = false;
    const locked = navigator.onLine && !allowOnline;
    if (locked) stopScanners();
    view.lock(locked);
  }
  view.get("use-online").onclick = () => {
    allowOnline = true;
    syncNetwork();
  };
  window.addEventListener("online", syncNetwork);
  window.addEventListener("offline", syncNetwork);
  window.addEventListener("pagehide", stopScanners);
  view.update(state);
  syncNetwork();
  return function dispose() {
    disposed = true;
    cancelActiveDecryptWork();
    window.removeEventListener("online", syncNetwork);
    window.removeEventListener("offline", syncNetwork);
    window.removeEventListener("pagehide", stopScanners);
    for (const scanner of scanners) scanner.dispose();
    root.replaceChildren();
  };
}
