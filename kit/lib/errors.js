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

// Codes describe recovery failures; messages are presentation only.
const stages = {
  PASSPHRASE_AUTH_FAILED: "unlock",
  RECOVERY_RESOURCE_LIMIT: "unlock",
  SCRYPT_UNAVAILABLE: "unlock",
  CANCELLED: "unlock",
  AUTH_REQUIRED: "authentication",
  AUTH_DOC_HASH_MISMATCH: "authentication",
  ROOT_SIGNING_KEY_MISMATCH: "authentication",
  AUTH_SIGNATURE_INVALID: "authentication",
  AUTH_VERIFICATION_FAILED: "authentication",
  AUTH_CONFLICT: "authentication",
  AUTH_PAYLOAD_INVALID: "authentication",
  RECOVERY_TARGET_INVALID: "selection",
  SELECTED_DOCUMENT_FAILED: "selection",
  DOCUMENT_INVALID: "source",
  DOCUMENT_INTEGRITY_FAILED: "source",
  SUPPLIED_DOCUMENT_FAILED: "source",
  INPUT_REQUIRED: "source",
};

export class RecoveryError extends Error {
  constructor(code, message, options = {}) {
    super(message, options);
    this.name = "RecoveryError";
    this.code = code;
    this.stage = stages[code] ?? "source";
  }
}

export function asRecoveryError(error, code = "DOCUMENT_INVALID") {
  return error instanceof RecoveryError
    ? error
    : new RecoveryError(
        error?.name === "AbortError" ? "CANCELLED" : code,
        error instanceof Error ? error.message : String(error),
        {
          cause: error,
        },
      );
}

export function isPassphraseAuthenticationFailure(error) {
  return error instanceof RecoveryError && error.code === "PASSPHRASE_AUTH_FAILED";
}
