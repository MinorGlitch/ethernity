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

import { useEffect, useReducer, useRef, useState } from "microact/hooks";

import {
  addPayloads,
  addShardPayloads,
  copyRecoveredSecret,
  resetAll,
  updateField,
} from "./actions_collect.js";
import { clearOutput, decryptCiphertext, extractEnvelope } from "./actions_recover.js";
import { downloadCipher, downloadEnvelope, downloadExtract, downloadZip } from "./actions_export.js";
import { DecryptSection } from "./components/DecryptSection.jsx";
import { FrameCollector } from "./components/FrameCollector.jsx";
import { RecoveredFiles } from "./components/RecoveredFiles.jsx";
import { ShardCollector } from "./components/ShardCollector.jsx";
import { StepShell } from "./components/StepShell.jsx";
import { reducer, initialState } from "./state/reducer.js";
import {
  selectActionState,
  selectFrameDiagnostics,
  selectOutputSummary,
  selectRecoveredLabel,
  selectShardDiagnostics,
  selectShardInputs,
} from "./state/selectors.js";

export function App() {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const [isOnline, setIsOnline] = useState(() => {
    if (typeof navigator === "undefined") return false;
    return Boolean(navigator.onLine);
  });
  const [onlineOverrideStep, setOnlineOverrideStep] = useState(0);
  const stateRef = useRef(state);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const sync = () => setIsOnline(Boolean(navigator.onLine));
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);

  useEffect(() => {
    if (!isOnline && onlineOverrideStep !== 0) {
      setOnlineOverrideStep(0);
    }
  }, [isOnline, onlineOverrideStep]);

  const getState = () => stateRef.current;

  const frameDiagnostics = selectFrameDiagnostics(state);
  const shardDiagnostics = selectShardDiagnostics(state);
  const shardInputs = selectShardInputs(state);
  const outputSummary = selectOutputSummary(state);
  const actionState = selectActionState(state);
  const recoveredLabel = selectRecoveredLabel(state);

  const handlePayloadChange = (event) =>
    updateField(dispatch, getState, "payloadText", event.currentTarget.value);
  const handleShardPayloadChange = (event) =>
    updateField(dispatch, getState, "shardPayloadText", event.currentTarget.value);
  const handlePassphraseChange = (event) =>
    updateField(dispatch, getState, "agePassphrase", event.currentTarget.value);

  const handleAddPayloads = () => addPayloads(dispatch, getState);
  const handleAddShardPayloads = () => addShardPayloads(dispatch, getState);
  const handleReset = () => resetAll(dispatch);
  const handleDownloadCipher = () => downloadCipher(dispatch, getState);
  const handleCopyResult = () => copyRecoveredSecret(dispatch, getState);
  const handleDecrypt = () => decryptCiphertext(dispatch, getState);
  const handleExtract = () => extractEnvelope(dispatch, getState);
  const handleDownloadEnvelope = () => downloadEnvelope(dispatch, getState);
  const handleClearOutput = () => clearOutput(dispatch, getState);
  const handleDownloadZip = () => downloadZip(dispatch, getState);
  const handleDownloadFile = (index) => downloadExtract(dispatch, getState, index);
  const onlineOverrideActive = isOnline && onlineOverrideStep >= 3;

  if (isOnline && !onlineOverrideActive) {
    return (
      <main class="shell shell--blocked">
        <section class="offline-guard-screen">
          <div class="offline-guard-card">
            <div class="offline-guard-kicker">Recovery Kit Locked</div>
            <h1 class="offline-guard-title">Disconnect from the Internet</h1>
            <p class="offline-guard-subtitle">
              This recovery tool is intended for offline use only.
            </p>
            <div class="status warn offline-guard-status">
              This device appears to be online. Disconnect all network connections before using the
              recovery kit.
              {"\n"}
              {"\n"}
              After disconnecting, keep this page open and wait for the warning to clear.
            </div>
            <div class="offline-guard-note">
              The page will unlock automatically when the browser reports offline status.
            </div>
            <div class="offline-guard-actions">
              {onlineOverrideStep === 0 ? (
                <button type="button" class="secondary" onClick={() => setOnlineOverrideStep(1)}>
                  Emergency override
                </button>
              ) : null}
              {onlineOverrideStep === 1 ? (
                <div class="offline-guard-confirm">
                  <div class="offline-guard-confirm-text">
                    Proceeding while online increases the risk of exposing recovery secrets.
                  </div>
                  <div class="row">
                    <button type="button" class="ghost" onClick={() => setOnlineOverrideStep(0)}>
                      Cancel
                    </button>
                    <button type="button" class="secondary" onClick={() => setOnlineOverrideStep(2)}>
                      I understand the risk
                    </button>
                  </div>
                </div>
              ) : null}
              {onlineOverrideStep === 2 ? (
                <div class="offline-guard-confirm">
                  <div class="offline-guard-confirm-text">
                    Confirm you want to unlock the recovery kit while this browser reports an active
                    network connection.
                  </div>
                  <div class="row">
                    <button type="button" class="ghost" onClick={() => setOnlineOverrideStep(0)}>
                      Cancel
                    </button>
                    <button type="button" onClick={() => setOnlineOverrideStep(3)}>
                      Continue while online
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main class="shell">
      <header class="app-header">
        <div class="app-title-block">
          <h1 class="app-title">Recovery Kit</h1>
          <p class="app-subtitle">Offline recovery tool for decryption and extraction.</p>
        </div>
      </header>
      {onlineOverrideActive ? (
        <section class="panel online-override-banner">
          <div class="row row-between">
            <div>
              <div class="offline-guard-kicker">Danger: Online Override Active</div>
              <div class="sub">
                Browser reports an active network connection. You are recovering at your own risk
                while online, and any secrets entered here may be exposed. Disconnect immediately to
                return to safer offline mode.
              </div>
            </div>
          </div>
        </section>
      ) : null}
      <section class="workspace">
        <StepShell
          title="Enter backup data"
          summary="Paste backup text or scanned QR payloads. Include AUTH if available."
        >
          <FrameCollector
            payloadText={state.payloadText}
            frameStatus={state.frameStatus}
            frameDiagnostics={frameDiagnostics}
            onPayloadChange={handlePayloadChange}
            onAddPayloads={handleAddPayloads}
            isComplete={Boolean(state.total && state.mainFrames.size === state.total)}
            onReset={handleReset}
            onDownloadCipher={handleDownloadCipher}
            canDownloadCipher={actionState.canDownloadCipher}
          />
        </StepShell>
        <StepShell
          title="Combine recovery shares"
          summary="Paste shard documents to reconstruct a split passphrase, or skip if you have it."
        >
          <ShardCollector
            shardPayloadText={state.shardPayloadText}
            shardStatus={state.shardStatus}
            shardDiagnostics={shardDiagnostics}
            recoveredLabel={recoveredLabel}
            recoveredSecret={state.recoveredShardSecret}
            shardDocHash={shardInputs.docHashHex}
            shardDocId={shardInputs.docIdHex}
            shardSignPub={shardInputs.signPubHex}
            onShardPayloadChange={handleShardPayloadChange}
            onAddShardPayloads={handleAddShardPayloads}
            isComplete={Boolean(state.recoveredShardSecret)}
            onCopyResult={handleCopyResult}
            canCopyResult={actionState.canCopyResult}
          />
        </StepShell>
        <StepShell
          title="Unlock & download"
          summary="Enter your passphrase to unlock and download recovered files."
        >
          <DecryptSection
            passphrase={state.agePassphrase}
            decryptStatus={state.decryptStatus}
            onPassphraseChange={handlePassphraseChange}
            onDecrypt={handleDecrypt}
            canDecrypt={actionState.canDecryptCiphertext}
            isComplete={actionState.hasOutput || Boolean(state.decryptedEnvelope)}
            isDecrypting={state.isDecrypting}
            onExtract={handleExtract}
            onDownloadEnvelope={handleDownloadEnvelope}
            canExtract={actionState.canExtractEnvelope}
            canDownloadEnvelope={actionState.canDownloadEnvelope}
          >
            <RecoveredFiles
              extractStatus={state.extractStatus}
              outputSubtitle={outputSummary.subtitle}
              files={state.extractedFiles}
              onClearOutput={handleClearOutput}
              onDownloadZip={handleDownloadZip}
              onDownloadFile={handleDownloadFile}
              hasOutput={actionState.hasOutput}
              recoveryComplete={state.recoveryComplete}
            />
          </DecryptSection>
        </StepShell>
      </section>
    </main>
  );
}
