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
}) {
  const actions = [
    { label: "Add payloads", onClick: onAddPayloads },
    { label: "Download ciphertext.age", className: "secondary", onClick: onDownloadCipher, disabled: !canDownloadCipher },
    { label: "Reset", className: "ghost", onClick: onReset },
  ];
  const input = {
    title: "Payload inputs",
    body: (
      <Field
        id="payload-text"
        label="Payload text"
        value={payloadText}
        placeholder="Paste main frames and optional auth frame text here..."
        onInput={onPayloadChange}
        as="textarea"
      />
    ),
    actions,
  };
  const status = {
    title: "Status &amp; validation",
    body: (
      <>
        <StatusBlock status={frameStatus} />
        <div class="label">Validation</div>
        <DiagnosticsList items={frameDiagnostics} />
      </>
    ),
  };
  return (
    <CollectorStep className="step-layout--compact" input={input} status={status} />
  );
}
