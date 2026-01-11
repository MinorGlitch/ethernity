import { listMissing } from "../frames.js";
import { SHARD_KEY_PASSPHRASE, SHARD_KEY_SIGNING_SEED } from "../constants.js";

export function formatBytes(value) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unitIdx = 0;
  while (size >= 1024 && unitIdx < units.length - 1) {
    size /= 1024;
    unitIdx += 1;
  }
  const precision = size >= 100 || unitIdx === 0 ? 0 : size >= 10 ? 1 : 2;
  return `${size.toFixed(precision)} ${units[unitIdx]}`;
}

function describeMissingFrames(state) {
  if (!state.total) {
    return {
      value: "Waiting for data",
      detail: "Paste backup data to begin.",
      tone: "idle",
    };
  }
  const missingCount = Math.max(0, state.total - state.mainFrames.size);
  if (missingCount === 0) {
    return {
      value: "Complete",
      detail: "All backup data collected.",
      tone: "ok",
    };
  }
  const missingList = listMissing(state.total, state.mainFrames);
  const preview = missingList.slice(0, 8);
  const extra = missingList.length - preview.length;
  const detail = preview.length
    ? `Missing sections: ${preview.join(", ")}${extra > 0 ? ` +${extra} more` : ""}`
    : "";
  return {
    value: `${missingCount} more needed`,
    detail,
    tone: "warn",
  };
}

function describeValidationSummary(state) {
  const hasErrors = state.errors > 0 || state.conflicts > 0;
  const hasFrames = state.mainFrames.size > 0;
  const totalKnown = Boolean(state.total);
  const missingCount = totalKnown ? Math.max(0, state.total - state.mainFrames.size) : null;
  if (hasErrors) {
    return {
      value: "Problem detected",
      detail: "Check the data you pasted - there may be conflicts or formatting issues.",
      tone: "error",
    };
  }
  if (totalKnown && missingCount === 0) {
    return {
      value: "Ready to unlock",
      detail: "All backup data collected. Proceed to Step 3.",
      tone: "ok",
    };
  }
  if (hasFrames) {
    return {
      value: "Collecting data",
      detail: missingCount === null
        ? "Processing your input..."
        : `Add ${missingCount} more section(s) from your recovery document.`,
      tone: "progress",
    };
  }
  return {
    value: "Waiting for data",
    detail: "Paste the text from your recovery document.",
    tone: "idle",
  };
}

function describeAuthStatus(state) {
  const status = state.authStatus || "missing";
  if (status === "verified") {
    return { value: "Verified", detail: "Data integrity confirmed.", tone: "ok" };
  }
  if (status === "missing") {
    return {
      value: "Not included",
      detail: "Include the AUTH section from your document to verify integrity.",
      tone: "idle",
    };
  }
  if (status === "pending") {
    return { value: "Checking...", tone: "progress" };
  }
  if (status === "waiting for main frames") {
    return { value: "Waiting for backup data", tone: "progress" };
  }
  if (status === "doc_hash matches; signature not verified") {
    return {
      value: "Data matches",
      detail: "Integrity check passed. Full signature verification unavailable in browser.",
      tone: "warn",
    };
  }
  if (status === "invalid signature" || status.includes("mismatch") || status.includes("conflict")) {
    return { value: "Verification failed", detail: "The data may have been altered or corrupted.", tone: "error" };
  }
  if (status === "invalid payload") {
    return { value: "Invalid verification data", detail: "The AUTH section appears to be malformed.", tone: "error" };
  }
  return { value: status, tone: "idle" };
}

function sumFrameBytes(frames) {
  let total = 0;
  for (const frame of frames.values()) {
    total += frame.data.length;
  }
  return total;
}

function describeShardReadiness(state) {
  const hasSecret = Boolean(state.recoveredShardSecret);
  if (hasSecret) {
    return { value: "Passphrase recovered", detail: "You can now proceed to Step 3.", tone: "ok" };
  }
  const thresholdKnown = Boolean(state.shardThreshold);
  const collected = state.shardFrames.size;
  if (thresholdKnown && collected >= state.shardThreshold) {
    return { value: "Ready to combine", detail: "Click 'Add shares' to recover your passphrase.", tone: "progress" };
  }
  if (collected) {
    const remaining = thresholdKnown ? Math.max(0, state.shardThreshold - collected) : null;
    return {
      value: "Collecting shares",
      detail: remaining === null ? "Processing shares..." : `Add ${remaining} more share(s) from your shard documents.`,
      tone: "progress",
    };
  }
  return { value: "No shares yet", detail: "Skip this step if you have the full passphrase.", tone: "idle" };
}

function selectFrameStatusItems(state) {
  const validationSummary = describeValidationSummary(state);
  const authInfo = describeAuthStatus(state);
  const framesTone = state.total && state.mainFrames.size === state.total
    ? "ok"
    : state.mainFrames.size
      ? "progress"
      : "idle";
  const missingCount = state.total ? Math.max(0, state.total - state.mainFrames.size) : null;
  const readyToDecrypt = Boolean(state.total)
    && missingCount === 0
    && state.errors === 0
    && state.conflicts === 0;
  const authMissing = authInfo.value?.toLowerCase?.().includes("not included");
  const authItem = readyToDecrypt && authMissing
    ? {
      label: "Verification",
      value: "Skipped",
      subLabel: "Ready to unlock. Include AUTH section for integrity check.",
      tone: "warn",
    }
    : {
      label: "Verification",
      value: authInfo.value,
      subLabel: authInfo.detail,
      tone: authInfo.tone,
    };
  const framesDetail = state.total
    ? missingCount === 0
      ? `${state.total} sections collected`
      : `${missingCount} more needed`
    : "Waiting for data";
  return [
    {
      label: "Status",
      value: validationSummary.value,
      subLabel: validationSummary.detail,
      tone: validationSummary.tone,
    },
    {
      label: "Progress",
      value: `${state.mainFrames.size}/${state.total ?? "?"}`,
      subLabel: framesDetail,
      tone: framesTone,
    },
    authItem,
  ];
}

export function selectFrameDiagnostics(state) {
  const missingInfo = describeMissingFrames(state);
  return [
    { label: "Missing", value: missingInfo.value, detail: missingInfo.detail, tone: missingInfo.tone },
    { label: "Conflicts", value: `${state.conflicts}`, tone: state.conflicts > 0 ? "error" : "ok" },
    { label: "Errors", value: `${state.errors}`, tone: state.errors > 0 ? "error" : "ok" },
    { label: "Duplicates", value: `${state.duplicates}`, tone: state.duplicates > 0 ? "warn" : "ok" },
    { label: "Ignored", value: `${state.ignored}`, tone: state.ignored > 0 ? "warn" : "ok" },
    { label: "Doc ID", value: state.docIdHex ?? "(unknown)", tone: state.docIdHex ? "ok" : "idle", code: true },
  ];
}

export function selectShardKeyLabel(state) {
  if (state.shardKeyType === SHARD_KEY_PASSPHRASE) return "passphrase";
  if (state.shardKeyType === SHARD_KEY_SIGNING_SEED) return "signing key";
  return "-";
}

export function selectRecoveredLabel(state) {
  if (state.shardKeyType === SHARD_KEY_SIGNING_SEED) {
    return "Recovered signing key (hex)";
  }
  if (state.shardKeyType === SHARD_KEY_PASSPHRASE) {
    return "Recovered passphrase";
  }
  return "Recovered secret";
}

export function selectShardMatch(state) {
  if (state.docIdHex && state.shardDocIdHex) {
    return state.docIdHex === state.shardDocIdHex ? "yes" : "no";
  }
  return "-";
}

export function selectShardInputs(state) {
  return {
    docIdHex: state.shardDocIdHex || state.docIdHex || state.authDocIdHex || "",
    docHashHex: state.shardDocHashHex || state.authDocHashHex || state.cipherDocHashHex || "",
    signPubHex: state.shardSignPubHex || state.authSignPubHex || "",
  };
}

function selectShardStatusItems(state) {
  const readiness = describeShardReadiness(state);
  const shardMatch = selectShardMatch(state);
  const matchTone = shardMatch === "yes" ? "ok" : shardMatch === "no" ? "error" : "idle";
  const quorumValue = state.shardThreshold
    ? `${state.shardThreshold} of ${state.shardShares ?? "?"}`
    : "Unknown";
  const collectedValue = state.shardThreshold
    ? `${state.shardFrames.size}/${state.shardThreshold}`
    : `${state.shardFrames.size}`;
  return [
    {
      label: "Readiness",
      value: readiness.value,
      subLabel: readiness.detail,
      tone: readiness.tone,
    },
    {
      label: "Quorum",
      value: quorumValue,
      subLabel: state.shardThreshold ? `Collected ${collectedValue}` : "Waiting for shard metadata.",
      tone: state.shardThreshold ? "ok" : "idle",
    },
    {
      label: "Doc match",
      value: shardMatch,
      subLabel: shardMatch === "-" ? "Waiting for doc IDs." : undefined,
      tone: matchTone,
    },
  ];
}

export function selectShardDiagnostics(state) {
  const shardKeyLabel = selectShardKeyLabel(state);
  return [
    {
      label: "Key type",
      value: shardKeyLabel === "-" ? "Unknown" : shardKeyLabel,
      tone: shardKeyLabel === "-" ? "idle" : "ok",
    },
    { label: "Conflicts", value: `${state.shardConflicts}`, tone: state.shardConflicts > 0 ? "error" : "ok" },
    { label: "Errors", value: `${state.shardErrors}`, tone: state.shardErrors > 0 ? "error" : "ok" },
    { label: "Duplicates", value: `${state.shardDuplicates}`, tone: state.shardDuplicates > 0 ? "warn" : "ok" },
  ];
}

export function selectCiphertextSource(state) {
  const available = Boolean(state.ciphertext)
    || (state.total && state.mainFrames.size === state.total);
  const size = available
    ? (state.ciphertext ? state.ciphertext.length : sumFrameBytes(state.mainFrames))
    : 0;
  const detail = available
    ? `${formatBytes(size)}  |  ${state.mainFrames.size}/${state.total ?? "?"} frames`
    : `Waiting for frames (${state.mainFrames.size}/${state.total ?? "?"})`;
  return {
    label: "Collected ciphertext",
    detail,
    available,
  };
}

export function selectEnvelopeSource(state) {
  if (state.decryptedEnvelope) {
    return {
      label: "Decrypted envelope",
      detail: `${state.decryptedEnvelopeSource || "From decrypted ciphertext"}  |  ${formatBytes(state.decryptedEnvelope.length)}`,
      available: true,
    };
  }
  return {
    label: "Decrypted envelope",
    detail: "No decrypted envelope yet",
    available: false,
  };
}

export function selectOutputSummary(state) {
  const count = state.extractedFiles.length;
  const totalBytes = state.extractedFiles.reduce((sum, file) => sum + file.data.length, 0);
  const subtitle = count
    ? `${count} file(s)  |  ${formatBytes(totalBytes)}`
    : "No files extracted yet";
  return { count, totalBytes, subtitle };
}

function selectDecryptStatusItems(state) {
  const ciphertextSource = selectCiphertextSource(state);
  const envelopeSource = selectEnvelopeSource(state);
  const outputSummary = selectOutputSummary(state);
  const actionState = selectActionState(state);
  const passphraseProvided = state.agePassphrase.trim().length > 0;
  const ready = ciphertextSource.available && passphraseProvided;
  const readinessTone = ready
    ? "ok"
    : ciphertextSource.available || passphraseProvided
      ? "warn"
      : "idle";
  let readinessDetail = "Complete Step 1 and enter your passphrase.";
  if (ciphertextSource.available && !passphraseProvided) {
    readinessDetail = "Enter your passphrase to unlock.";
  } else if (!ciphertextSource.available && passphraseProvided) {
    readinessDetail = "Go back to Step 1 to add backup data.";
  } else if (ready) {
    readinessDetail = "Click 'Unlock & extract' to recover your files.";
  }
  const envelopeTone = state.decryptedEnvelope
    ? "ok"
    : actionState.canDecryptCiphertext
      ? "progress"
      : "idle";
  const outputTone = outputSummary.count
    ? "ok"
    : state.decryptedEnvelope
      ? "progress"
      : "idle";
  const outputDetail = outputSummary.count
    ? formatBytes(outputSummary.totalBytes)
    : "Your files will appear here after unlocking.";
  return [
    {
      label: "Status",
      value: ready ? "Ready to unlock" : "Waiting",
      subLabel: readinessDetail,
      tone: readinessTone,
    },
    {
      label: "Backup",
      value: state.decryptedEnvelope ? "Unlocked" : "Locked",
      subLabel: envelopeSource.detail,
      tone: envelopeTone,
    },
    {
      label: "Files",
      value: outputSummary.count ? `${outputSummary.count} recovered` : "None yet",
      subLabel: outputDetail,
      tone: outputTone,
    },
  ];
}

export function selectActionState(state) {
  const ciphertextSource = selectCiphertextSource(state);
  const decryptedEnvelopeAvailable = Boolean(state.decryptedEnvelope);
  return {
    canDownloadCipher: state.total && state.mainFrames.size === state.total,
    canDecryptCiphertext: state.agePassphrase.trim().length > 0 && ciphertextSource.available,
    canExtractEnvelope: decryptedEnvelopeAvailable,
    canDownloadEnvelope: decryptedEnvelopeAvailable,
    canCopyResult: Boolean(state.recoveredShardSecret),
    hasOutput: state.extractedFiles.length > 0,
  };
}

export function selectStatusItemsForStep(state, stepId) {
  if (stepId === "frames") return selectFrameStatusItems(state);
  if (stepId === "shards") return selectShardStatusItems(state);
  if (stepId === "decrypt") return selectDecryptStatusItems(state);
  return [];
}
