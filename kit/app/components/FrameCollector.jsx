import { useState } from "preact/hooks";

import { DiagnosticsList, Field, StatusBlock } from "./common.jsx";
import { CollectorStep } from "./CollectorStep.jsx";

export function FrameCollector({
  payloadText,
  frameStatus,
  frameDiagnostics,
  onPayloadChange,
  onAddPayloads,
  onReset,
  onDownloadCipher,
  canDownloadCipher,
  isComplete,
}) {
  const showDetails = frameDiagnostics.some((item) => item.tone === "error");
  const [pasteHint, setPasteHint] = useState("");
  const handlePaste = (event) => {
    const text = event.clipboardData?.getData("text/plain") ?? "";
    const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (lines.length) {
      setPasteHint(`Pasted ${lines.length} line(s). Click Add frames.`);
    }
  };
  const handlePayloadChange = (event) => {
    setPasteHint("");
    onPayloadChange(event);
  };
  const handleAddFrames = () => {
    setPasteHint("");
    onAddPayloads();
  };
  const input = {
    title: "Frame inputs",
    body: (
      <>
        <Field
          id="payload-text"
          label="Frame text"
          value={payloadText}
          placeholder="Paste main frames and optional auth frame text here..."
          onInput={handlePayloadChange}
          onPaste={handlePaste}
          as="textarea"
        />
        {pasteHint ? <div class="hint">{pasteHint}</div> : null}
      </>
    ),
    actions: [{ label: "Add frames", onClick: handleAddFrames }],
    secondaryActions: [
      {
        label: "Download ciphertext.age",
        className: "secondary",
        onClick: onDownloadCipher,
        disabled: !canDownloadCipher,
        disabledReason: "Collect all frames to download.",
      },
      { label: "Reset", className: "ghost", onClick: onReset },
    ],
    className: isComplete && !payloadText.trim() ? "input-collapsed" : "",
  };
  const status = {
    title: "Status",
    body: (
      <>
        <StatusBlock status={frameStatus} />
        <details class="details" open={showDetails}>
          <summary>Validation details</summary>
          <DiagnosticsList items={frameDiagnostics} />
        </details>
      </>
    ),
  };
  return (
    <CollectorStep className="step-layout--compact" input={input} status={status} />
  );
}
