import { ActionsRow, Card, DiagnosticsList, Field, StatusBlock } from "./common.jsx";

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
  return (
    <div class="step-layout step-layout--compact">
      <Card title="Payload inputs" className="step-input">
        <Field
          id="payload-text"
          label="Payload text"
          value={payloadText}
          placeholder="Paste main frames and optional auth frame text here..."
          onInput={onPayloadChange}
          as="textarea"
        />
        <div class="helper">
          <div class="helper-title">Optional but recommended</div>
          <div class="helper-body">
            Include the auth frame to verify signature status. Recovery works without it.
          </div>
        </div>
      </Card>
      <div class="action-bar step-actions">
        <div class="label">Actions</div>
        <ActionsRow actions={actions} />
      </div>
      <Card title="Status &amp; validation" className="step-status">
        <StatusBlock status={frameStatus} />
        <div class="label">Validation</div>
        <DiagnosticsList items={frameDiagnostics} />
      </Card>
    </div>
  );
}
