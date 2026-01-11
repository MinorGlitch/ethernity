import { ActionsRow, Card, Field, StatusBlock } from "./common.jsx";

export function DecryptSection({
  passphrase,
  decryptStatus,
  onPassphraseChange,
  onDecrypt,
  canDecrypt,
  isComplete,
  isDecrypting,
  onExtract,
  onDownloadEnvelope,
  canExtract,
  canDownloadEnvelope,
  children,
}) {
  const decryptActions = [
    {
      label: isDecrypting ? "Unlocking..." : "Unlock & extract",
      onClick: onDecrypt,
      disabled: !canDecrypt || isDecrypting,
      disabledReason: passphrase.trim() ? "Add backup data first (Step 1)." : "Enter your passphrase to unlock.",
    },
  ];
  const envelopeActions = [
    {
      label: "Extract files",
      onClick: onExtract,
      disabled: !canExtract,
      disabledReason: "Unlock the backup first.",
    },
    {
      label: "Download raw data",
      className: "secondary",
      onClick: onDownloadEnvelope,
      disabled: !canDownloadEnvelope,
      disabledReason: "Unlock the backup first.",
    },
  ];
  return (
    <div class="step-layout">
      <Card
        title="Enter passphrase"
        className={isComplete && !passphrase.trim() ? "step-input input-collapsed" : "step-input"}
      >
        <Field
          id="passphrase-input"
          label="Passphrase"
          value={passphrase}
          placeholder="Enter your passphrase here..."
          onInput={onPassphraseChange}
          type="password"
        />
        <ActionsRow actions={decryptActions} />
      </Card>
      <Card title="Decryption status" className="step-status">
        <ActionsRow actions={envelopeActions} className="actions-secondary" />
        <StatusBlock status={decryptStatus} />
      </Card>
      <div class="step-output">
        {children}
      </div>
    </div>
  );
}
