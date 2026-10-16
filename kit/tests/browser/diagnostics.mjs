import { createView } from "../../app/ui/view.js";
import { cloneState, createInitialState } from "../../app/state/initial.js";
import { reducer } from "../../app/state/reducer.js";
import { updateField } from "../../app/actions_collect.js";
import { addMainDocumentFrame } from "../../app/documents/store.js";
import { addShardPayloadFrame } from "../../app/shard_store.js";
import { SHARD_KEY_PASSPHRASE, SHARD_KEY_SIGNING_SEED } from "../../app/constants.js";

function check(condition, message) {
  if (!condition) throw new Error(message);
}

export function checkDiagnosticUpdates(root) {
  const view = createView(root, () => {});
  let state = createInitialState();
  const frame = (id, index = 0) => ({
    docId: new Uint8Array(8).fill(id),
    total: 2,
    index,
    data: new Uint8Array([index]),
  });
  addMainDocumentFrame(state, frame(1));
  addMainDocumentFrame(state, frame(2));
  const shard = {
    version: 2,
    threshold: 2,
    shareCount: 3,
    secretLen: 32,
    shareIndex: 1,
    share: new Uint8Array([1]),
    signature: new Uint8Array(64),
    docHash: new Uint8Array(32),
    signPub: new Uint8Array(32),
    shardSetId: new Uint8Array(16),
  };
  addShardPayloadFrame(state, frame(1), { ...shard, keyType: SHARD_KEY_PASSPHRASE });
  addShardPayloadFrame(state, frame(1), { ...shard, keyType: SHARD_KEY_SIGNING_SEED });
  const [passphraseSet, signingSet] = state.shardSets.keys();
  state.activeShardSetKey = passphraseSet;
  state.frameStatus = { lines: ["Added backup parts."], type: "" };
  state.shardStatus = { lines: ["Added recovery sheets."], type: "" };
  view.update(state);
  view.lock(false);

  const dispatch = (action) => {
    state = reducer(state, action);
    view.update(state);
  };
  const publish = (patch) => dispatch({ type: "PATCH_STATE", patch, baseRevision: state.revision });
  const rows = () => Array.from(root.querySelectorAll(".diag-row"));
  const value = (section, label) =>
    Array.from(view.get(section).querySelectorAll(".diag-row"))
      .find((row) => row.querySelector(".diag-label").textContent === label)
      ?.querySelector(".diag-value").firstChild.textContent;
  const originalRows = rows();
  const details = view.get("backup-status").querySelector("details");
  details.open = true;
  for (const [key, text] of [
    ["payloadText", "draft backup"],
    ["shardPayloadText", "draft sheet"],
    ["agePassphrase", "edited"],
    ["extensionTargetText", "root"],
    ["expectedHeadDocHashText", "ab".repeat(32)],
    ["freshnessUnknownAcknowledged", true],
  ]) {
    updateField(dispatch, () => state, key, text);
  }
  publish({
    frameStatus: { lines: ["Try another copy."], type: "error" },
    shardStatus: { lines: ["Copied to clipboard."], type: "ok" },
  });
  const unchangedRows = rows();
  check(
    unchangedRows.length === originalRows.length &&
      unchangedRows.every((row, index) => row === originalRows[index]),
    "Text edits or status updates rebuilt collection diagnostics",
  );
  check(details.open, "Unrelated updates closed technical details");
  check(
    view.get("backup-status").querySelector(".status").textContent === "Try another copy." &&
      view.get("sheets-status").querySelector(".status").textContent === "Copied to clipboard.",
    "Preserving diagnostics prevented new status messages",
  );

  const collected = cloneState(state);
  addMainDocumentFrame(collected, frame(1, 1));
  addMainDocumentFrame(collected, frame(1, 1));
  publish({ documents: collected.documents });
  check(
    value("backup-status", "Backup data") === "1 missing" &&
      value("backup-status", "Repeated parts") === "1",
    "New backup data did not update progress and duplicate counts",
  );
  const sheetRows = Array.from(view.get("sheets-status").querySelectorAll(".diag-row"));
  check(
    sheetRows.every((row) => originalRows.includes(row)),
    "Backup collection rebuilt sheet diagnostics",
  );
  const secondId = Array.from(state.documents.keys())[1];
  publish({ primaryDocIdHex: secondId });
  check(
    value("backup-status", "Document ID") === secondId,
    "Primary document change was not displayed",
  );
  const complete = cloneState(state);
  addMainDocumentFrame(complete, frame(2, 1));
  publish({ documents: complete.documents, payloadText: "" });
  check(
    view.get("backup-input").classList.contains("input-collapsed"),
    "Completed backup did not collapse input",
  );
  updateField(dispatch, () => state, "payloadText", "another part");
  check(
    !view.get("backup-input").classList.contains("input-collapsed"),
    "Typing did not reopen completed input",
  );

  const sheets = cloneState(state);
  addShardPayloadFrame(sheets, frame(1), {
    ...shard,
    keyType: SHARD_KEY_PASSPHRASE,
    shareIndex: 2,
  });
  publish({ shardSets: sheets.shardSets });
  check(
    value("sheets-status", "Passphrase sheets") === "2 of 2 needed",
    "New sheet did not update progress",
  );
  publish({ activeShardSetKey: signingSet });
  check(
    value("sheets-status", "Key type") === "signing key",
    "Active sheet set change was not displayed",
  );
  publish({ recoveredShardSecret: "recovered" });
  check(
    view.get("sheets-status").querySelector(".prominent").hidden &&
      !view.get("secret-output").hidden,
    "Recovered secret did not move sheet progress into technical details",
  );

  dispatch({ type: "RESET" });
  check(
    view.get("backup-status").hidden &&
      view.get("sheets-status").hidden &&
      value("backup-status", "Documents") === "Waiting" &&
      !root.textContent.includes("2 of 2 needed") &&
      !view.get("backup-input").classList.contains("input-collapsed") &&
      view.get("secret-output").hidden,
    "Reset retained old collection diagnostics",
  );
}
