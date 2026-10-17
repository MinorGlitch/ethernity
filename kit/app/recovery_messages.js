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

const recoveryErrors = {
  PASSPHRASE_AUTH_FAILED:
    "The passphrase did not unlock this backup. Check the words, spaces, and letter case.",
  RECOVERY_RESOURCE_LIMIT:
    "This recovery exceeds the kit's size or processing limits. Try recovering it with the Ethernity app.",
  SCRYPT_UNAVAILABLE: "This browser could not start recovery. Try another browser or computer.",
  CANCELLED: "Recovery cancelled.",
  AUTH_DOC_HASH_MISMATCH:
    "The verification data does not match the backup. Check that the AUTH and MAIN sections belong together.",
  ROOT_SIGNING_KEY_MISMATCH:
    "The pages use different signing keys. Check that the original backup and updates belong to the same set.",
  AUTH_SIGNATURE_INVALID:
    "A page's signature is invalid. Its contents cannot be verified. Try another copy of the matching page.",
  AUTH_VERIFICATION_FAILED:
    "The kit could not check the page signatures. Try another browser before using these pages.",
  AUTH_CONFLICT:
    "Two AUTH sections contain different verification data for the same backup. Start over with one matching page set.",
  AUTH_PAYLOAD_INVALID:
    "An AUTH section could not be read. Start over and scan or paste it again from the matching backup.",
  DOCUMENT_INVALID:
    "The backup data is invalid or uses a format this kit cannot read. Try an intact copy of the pages or a kit that supports this backup.",
  DOCUMENT_INTEGRITY_FAILED:
    "The backup failed an integrity check. Try an undamaged copy of the matching pages.",
  SUPPLIED_DOCUMENT_FAILED:
    "Some of the added documents could not be read or unlocked. Check that they belong together and use the same passphrase.",
  SELECTED_DOCUMENT_FAILED:
    "The version you chose could not be read, unlocked, or verified. Check its fingerprint and try another copy of its pages.",
  INPUT_REQUIRED: "Add the backup pages before unlocking them.",
};

export function recoveryErrorMessage(error) {
  return recoveryErrors[error?.code] ?? (error instanceof Error ? error.message : String(error));
}

export function recoveryResultStatus(result) {
  const index = result.selectedExtensionIndex;
  const lines = [
    index === null
      ? "Recovered the original backup."
      : result.replayTarget === "latest"
        ? `Recovered update ${index}, the newest update among the pages you added.`
        : `Recovered update ${index}.`,
  ];
  if (result.trustBasis === "matched_expected_head") {
    lines.push(
      result.signingKeyVerified
        ? "The fingerprint you supplied matches. It verifies the original backup, signing key, and selected version."
        : "The fingerprint you supplied matches. It verifies the backup, but not its signing key.",
      "A matching fingerprint does not rule out a newer update.",
    );
  } else {
    lines.push(
      "The pages passed their checks, but were not matched to a separately kept fingerprint.",
      "Newer updates may exist outside the pages you added.",
    );
  }
  const details = [];
  if (result.selectedExtensionDocHash) {
    details.push(`Selected update fingerprint: ${result.selectedExtensionDocHash}`);
  }
  if (result.updateMode) details.push(`Update mode: ${result.updateMode}`);
  return { lines, details, type: "ok" };
}

export function cameraErrorMessage(error) {
  switch (error?.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Camera access is blocked. Allow it in your browser and device settings, or paste the backup text.";
    case "NotFoundError":
      return "No camera was found. Connect one or paste the backup text.";
    case "NotReadableError":
      return "The camera could not be opened. Close other apps using it and try again, or paste the text.";
    default:
      return "Scanning stopped. Try Scan QR again, or paste the text from the page.";
  }
}
