import { ActionsRow, Card, Field, SourceSummary, StatusBlock } from "./common.jsx";

export function DecryptSection({
  ciphertextSource,
  passphrase,
  decryptStatus,
  onPassphraseChange,
  onDecrypt,
  canDecrypt,
  envelopeSource,
  onExtract,
  onDownloadEnvelope,
  canExtract,
  canDownloadEnvelope,
  children,
}) {
  const decryptActions = [
    { label: "Decrypt & extract", onClick: onDecrypt, disabled: !canDecrypt },
  ];
  const envelopeActions = [
    { label: "Extract files", onClick: onExtract, disabled: !canExtract },
    { label: "Download envelope", className: "secondary", onClick: onDownloadEnvelope, disabled: !canDownloadEnvelope },
  ];
  return (
    <div class="step-layout">
      <Card title="Unlock ciphertext" className="step-input">
        <div class="label">Ciphertext source</div>
        <SourceSummary label={ciphertextSource.label} detail={ciphertextSource.detail} />
        <Field
          id="passphrase-input"
          label="Passphrase"
          value={passphrase}
          placeholder="Passphrase..."
          onInput={onPassphraseChange}
          type="password"
        />
      </Card>
      <div class="action-bar step-actions">
        <div class="label">Actions</div>
        <ActionsRow actions={decryptActions} />
        <ActionsRow actions={envelopeActions} />
      </div>
      <Card title="Envelope status" className="step-status">
        <div class="label">Envelope source</div>
        <SourceSummary label={envelopeSource.label} detail={envelopeSource.detail} />
        <StatusBlock status={decryptStatus} />
      </Card>
      <div class="step-output">
        {children}
      </div>
    </div>
  );
}
