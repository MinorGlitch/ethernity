import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { waitForPageState } from "./support.mjs";
import { checkScannerImages } from "./scanner.mjs";
import { checkOfflineTransitions } from "./network.mjs";
import { checkRecoveryEntry } from "./recovery_entry.mjs";

async function checkBundleInteractions(backups) {
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
  const check = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const click = async (label) => {
    const button = Array.from(document.querySelectorAll("button")).find(
      (item) => item.textContent.trim() === label,
    );
    check(button, `Missing button: ${label}`);
    check(!button.disabled, `Disabled button: ${label}: ${button.title}`);
    button.click();
    await tick();
  };
  await click("Use while online");
  check(document.getElementById("payload-text"), "Online entry requires another confirmation");
  const input = document.getElementById("payload-text");
  const details = document.getElementById("recovery-options");
  const video = document.querySelector("video");
  const stream = video ? new MediaStream() : null;
  if (video) video.srcObject = stream;
  details.open = true;
  input.focus();
  input.value = "invalid text";
  input.setSelectionRange(1, 3);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await tick();
  check(document.getElementById("payload-text") === input, "Input was replaced");
  check(
    document.activeElement === input && input.selectionStart === 1 && input.selectionEnd === 3,
    "Focus or selection moved",
  );
  check(
    document.getElementById("recovery-options") === details && details.open,
    "Details collapsed",
  );
  if (video)
    check(
      document.querySelector("video") === video && video.srcObject === stream,
      "Camera preview was replaced",
    );
  await click("Add backup");
  check(
    document
      .getElementById("app")
      .textContent.includes(
        "Some text could not be read. Copy the complete backup text and try again.",
      ),
    "Updated event handler did not read current input",
  );
  check(document.querySelectorAll(".status.error").length === 1, "Expected one error message");
  check(
    document.querySelectorAll(".diag-row.error").length === 0,
    "Duplicate error counter remains",
  );
  const sheetInput = document.getElementById("shard-payload-text");
  sheetInput.value = "invalid text";
  sheetInput.dispatchEvent(new Event("input", { bubbles: true }));
  await tick();
  await click("Add sheets");
  check(
    document.querySelectorAll(".status.error").length === 2,
    "Expected one error per collector",
  );
  check(
    document.querySelectorAll(".diag-row.error").length === 0,
    "Duplicate sheet error counter remains",
  );
  await click("Start over");
  check(input.value === "", "Reset did not update the existing input");
  check(
    !Array.from(document.querySelectorAll("button")).some(
      (button) => button.textContent.trim() === "Extract files",
    ),
    "Duplicate extraction action remains",
  );
  const setInput = async (element, value) => {
    element.value = value;
    element.dispatchEvent(new Event("input", { bubbles: true }));
    await tick();
  };
  for (const backup of backups) {
    await setInput(input, backup.payload);
    await click("Add backup");
    if (backup.shards) {
      await setInput(sheetInput, backup.shards);
      await click("Add sheets");
      for (
        let attempt = 0;
        attempt < 200 && document.getElementById("recovered-secret").value !== backup.passphrase;
        attempt++
      ) {
        await new Promise((resolve) => setTimeout(resolve, 25));
      }
      check(
        document.getElementById("recovered-secret").value === backup.passphrase,
        "Recovery sheets did not restore the passphrase",
      );
      check(
        document.getElementById("passphrase-input").value === backup.passphrase,
        "Recovered passphrase did not reach the unlock form",
      );
    }
    // Consecutive edits must both reach the state read by the action.
    const passphrase = document.getElementById("passphrase-input");
    passphrase.value = backup.passphrase;
    passphrase.dispatchEvent(new Event("input", { bubbles: true }));
    document.getElementById("freshness-unknown-acknowledgement").click();
    await tick();
    await click("Unlock backup");
    for (let attempt = 0; attempt < 2400; attempt += 1) {
      if (document.querySelector("tbody")?.textContent.includes(backup.path)) break;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    check(
      document.querySelector("tbody")?.textContent.includes(backup.path),
      `Recovery did not extract the file: ${document.getElementById("app").textContent}`,
    );
    check(
      document.getElementById("app").textContent.split("Recovery complete").length === 2,
      "Recovery result is missing or duplicated",
    );
    if (backup.updateMode) {
      check(
        document.querySelector("tbody")?.textContent.includes("update.txt"),
        "Missing updated file",
      );
      check(
        document.getElementById("app").textContent.includes("Recovered update 2"),
        "Wrong update selected",
      );
    }
    await click("Start over");
    check(
      !document.querySelector("tbody")?.textContent.includes(backup.path),
      "Reset retained recovered files",
    );
  }
  return "ui-ok";
}

export async function smokeBundle(browser, bundlePath, backups, isPrintedKit = false) {
  const loaderHtml = await readFile(bundlePath, "utf8");
  if (!isPrintedKit && !/name="ethernity-kit-compression" content="gzip"/u.test(loaderHtml)) {
    throw new Error(`${bundlePath} is not the default gzip recovery kit`);
  }
  await waitForPageState(browser, pathToFileURL(bundlePath).href, {
    attempts: 300,
    isReady: ({ html }) => html.includes(">Use while online</button>"),
    failureForState: ({ text }) =>
      text.includes("Recovery kit cannot open here")
        ? `${bundlePath} rendered the unsupported-loader fallback`
        : null,
    timeoutMessage: `${bundlePath} did not boot the recovery app`,
    async onReady(page) {
      const result = await page.evaluate(checkBundleInteractions, backups);
      if (result !== "ui-ok") throw new Error(`Kit interaction check failed: ${result}`);
      if (bundlePath.includes(".scanner.")) await checkScannerImages(page);
      await checkRecoveryEntry(page);
      await checkOfflineTransitions(page);
    },
  });
}
