import { useEffect, useReducer, useRef, useState } from "preact/hooks";

import {
  addPayloads,
  addShardPayloads,
  clearOutput,
  copyRecoveredSecret,
  decryptCiphertext,
  downloadCipher,
  downloadEnvelope,
  downloadExtract,
  downloadZip,
  extractEnvelope,
  resetAll,
  updateField,
} from "./actions.js";
import { StatusStrip } from "./components/StatusStrip.jsx";
import { StepNav } from "./components/StepNav.jsx";
import { StepShell } from "./components/StepShell.jsx";
import { reducer, initialState } from "./state/reducer.js";
import {
  selectActionState,
  selectFrameDiagnostics,
  selectOutputSummary,
  selectRecoveredLabel,
  selectShardDiagnostics,
  selectShardInputs,
  selectStatusItemsForStep,
} from "./state/selectors.js";
import { STEPS } from "./steps.jsx";

export function App() {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const [stepIndex, setStepIndex] = useState(0);
  const stateRef = useRef(state);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const getState = () => stateRef.current;

  const frameDiagnostics = selectFrameDiagnostics(state);
  const shardDiagnostics = selectShardDiagnostics(state);
  const shardInputs = selectShardInputs(state);
  const outputSummary = selectOutputSummary(state);
  const actionState = selectActionState(state);
  const recoveredLabel = selectRecoveredLabel(state);

  const frameStep = state.total && state.mainFrames.size === state.total
    ? { label: "Ready", tone: "ok" }
    : state.mainFrames.size
      ? { label: "Collecting", tone: "progress" }
      : { label: "Needs input", tone: "idle" };
  const shardStep = state.recoveredShardSecret
    ? { label: "Complete", tone: "ok" }
    : state.shardThreshold && state.shardFrames.size >= state.shardThreshold
      ? { label: "Ready", tone: "progress" }
      : state.shardFrames.size
        ? { label: "Collecting", tone: "progress" }
        : { label: "Needs input", tone: "idle" };
  const decryptStep = state.extractedFiles.length
    ? { label: "Complete", tone: "ok" }
    : state.decryptedEnvelope
      ? { label: "Decrypted", tone: "progress" }
      : actionState.canDecryptCiphertext
        ? { label: "Ready", tone: "progress" }
        : { label: "Needs input", tone: "idle" };
  const stepStates = STEPS.map((step) => {
    if (step.id === "frames") return frameStep;
    if (step.id === "shards") return shardStep;
    if (step.id === "decrypt") return decryptStep;
    return { label: "Pending", tone: "idle" };
  });

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
  const handlePrev = () => setStepIndex((current) => Math.max(0, current - 1));
  const handleNext = () => setStepIndex((current) => Math.min(STEPS.length - 1, current + 1));
  const handleJump = (value) => setStepIndex(() => Math.min(STEPS.length - 1, Math.max(0, value)));

  const stepContext = {
    state,
    frameDiagnostics,
    shardDiagnostics,
    shardInputs,
    outputSummary,
    actionState,
    recoveredLabel,
    onPayloadChange: handlePayloadChange,
    onShardPayloadChange: handleShardPayloadChange,
    onPassphraseChange: handlePassphraseChange,
    onAddPayloads: handleAddPayloads,
    onAddShardPayloads: handleAddShardPayloads,
    onReset: handleReset,
    onDownloadCipher: handleDownloadCipher,
    onCopyResult: handleCopyResult,
    onDecrypt: handleDecrypt,
    onExtract: handleExtract,
    onDownloadEnvelope: handleDownloadEnvelope,
    onClearOutput: handleClearOutput,
    onDownloadZip: handleDownloadZip,
    onDownloadFile: handleDownloadFile,
  };
  const currentStep = STEPS[stepIndex] ?? STEPS[0];
  const statusItems = selectStatusItemsForStep(state, currentStep.id);

  return (
    <main class="shell">
      <div class="app-layout">
        <aside class="panel rail">
          <StepNav
            steps={STEPS}
            stepIndex={stepIndex}
            stepStates={stepStates}
            onPrev={handlePrev}
            onNext={handleNext}
            onJump={handleJump}
          />
        </aside>
        <section class="workspace">
          <StatusStrip items={statusItems} />
          <StepShell
            step={currentStep}
            stepIndex={stepIndex}
            total={STEPS.length}
          >
            {currentStep.render(stepContext)}
          </StepShell>
        </section>
      </div>
    </main>
  );
}
