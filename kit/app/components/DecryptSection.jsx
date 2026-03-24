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

import { ActionsRow, Field, StatusBlock } from "./common.jsx";

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
      disabledReason: passphrase.trim()
        ? "Add backup data first (Step 1)."
        : "Enter your passphrase to unlock.",
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
      <div
        class={isComplete && !passphrase.trim() ? "step-section input-collapsed" : "step-section"}
      >
        <Field
          id="passphrase-input"
          label="Passphrase"
          value={passphrase}
          placeholder="Enter your passphrase here..."
          onInput={onPassphraseChange}
          type="password"
          autoComplete="off"
          spellCheck="false"
        />
        <ActionsRow actions={decryptActions} />
      </div>
      <div class="step-section">
        <div class="step-section-label">Status</div>
        <ActionsRow actions={envelopeActions} className="actions-secondary" />
        <StatusBlock status={decryptStatus} />
      </div>
      <div class="step-section">{children}</div>
    </div>
  );
}
