import { concatByteParts as concatBytes } from "../lib/bytes.js";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

import { chacha20poly1305 } from "@noble/ciphers/chacha.js";
import { hmac } from "@noble/hashes/hmac.js";
import { hkdf } from "@noble/hashes/hkdf.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { scrypt } from "@noble/hashes/scrypt.js";
import { minify as terserMinify } from "terser";
import { chromium, firefox, webkit } from "playwright";
import { FRAME_TYPE_AUTH, FRAME_TYPE_MAIN } from "../app/constants.js";
import { blake2b256 } from "../lib/blake2b.js";
import { encodeCbor } from "../lib/cbor.js";
import { buildFrame, signAuthPayload, toUnpaddedBase64 } from "../tests/protocol_test_data.mjs";
import { gzipCases } from "../tests/gzip_test_data.mjs";
import {
  buildRootPlaintext,
  buildExtensionPlaintext,
  ROOT_SIGNING_SEED,
  ROOT_SIGN_PUB,
} from "../tests/extension_test_data.mjs";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const kitDir = resolve(scriptDir, "..");
const printedKitDirectory = process.env.ETHERNITY_KIT_PRINTED_SMOKE_DIR;
const bundleDirectory =
  printedKitDirectory ?? resolve(kitDir, "..", "src", "ethernity", "resources", "kit");
const bundlePaths = [
  resolve(bundleDirectory, "recovery_kit.bundle.html"),
  resolve(bundleDirectory, "recovery_kit.scanner.bundle.html"),
];
const textEncoder = new TextEncoder();

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

function smokeBackup(updateMode = null) {
  const path = "generated-kit-smoke.txt";
  const passphrase = "generated-kit-smoke";
  const data = textEncoder.encode("recovered in browser");
  const rootFiles = [{ path, data }];
  const ciphertexts = [buildFastAgeCiphertext(buildRootPlaintext(rootFiles), passphrase)];
  if (updateMode) {
    const rootDocHash = blake2b256(ciphertexts[0]);
    for (let index = 1; index <= 2; index += 1) {
      ciphertexts.push(
        buildFastAgeCiphertext(
          buildExtensionPlaintext({
            index,
            rootDocHash,
            parentDocHash:
              updateMode === "cumulative" ? rootDocHash : blake2b256(ciphertexts[index - 1]),
            updateMode,
            files: [
              { path, data, inline: false },
              { path: "update.txt", data: textEncoder.encode(`update ${index}`) },
            ],
          }),
          passphrase,
        ),
      );
    }
  }
  const payload = ciphertexts
    .flatMap((ciphertext) => {
      const hash = blake2b256(ciphertext);
      const docId = hash.slice(0, 8);
      return [
        buildFrame({ frameType: FRAME_TYPE_MAIN, docId, data: ciphertext }),
        buildFrame({
          frameType: FRAME_TYPE_AUTH,
          docId,
          data: encodeCbor({
            version: 1,
            hash,
            pub: ROOT_SIGN_PUB,
            sig: signAuthPayload(hash, ROOT_SIGN_PUB, ROOT_SIGNING_SEED),
          }),
        }),
      ];
    })
    .map(toUnpaddedBase64)
    .join("\n");
  return { path, passphrase, payload, updateMode };
}

async function smokeUiLifecycle(browser) {
  const workDir = await mkdtemp(resolve(tmpdir(), "ethernity-ui-smoke-"));
  try {
    const output = resolve(workDir, "ui.js");
    requireSuccessfulCommand(
      spawnSync(
        "npx",
        [
          "--no-install",
          "esbuild",
          resolve(kitDir, "tests", "browser_ui_entry.mjs"),
          "--bundle",
          "--format=iife",
          "--platform=browser",
          "--target=es2020",
          "--minify",
          `--outfile=${output}`,
        ],
        { cwd: kitDir, encoding: "utf8" },
      ),
      "UI lifecycle check build",
    );
    const htmlPath = resolve(workDir, "ui.html");
    await writeFile(
      htmlPath,
      `<!doctype html><body>waiting<script>${await readFile(output, "utf8")}</script></body>`,
    );
    await waitForPageState(browser, pathToFileURL(htmlPath).href, {
      attempts: 100,
      isReady: ({ text }) => text === "ui-lifecycle-ok",
      failureForState: ({ text }) => (text.startsWith("ui-lifecycle-error:") ? text : null),
      timeoutMessage: "UI lifecycle checks timed out",
    });
  } finally {
    await rm(workDir, { recursive: true, force: true, maxRetries: 3 });
  }
}

async function smokeBundle(browser, bundlePath, backups) {
  const loaderHtml = await readFile(bundlePath, "utf8");
  if (
    !printedKitDirectory &&
    !/name="ethernity-kit-compression" content="gzip"/u.test(loaderHtml)
  ) {
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
      await checkOfflineTransitions(page);
    },
  });
}

async function checkPrintedMetadata(browser, bundlePath) {
  const valid = {
    capability: "ethernity-unanchored-rescue",
    version: 1,
    supported_document_versions: [1, 2],
  };
  for (const [metadata, errorText] of [
    [valid, null],
    [{ ...valid, capability: "unknown" }, "unsupported recovery kit capability"],
    [
      { ...valid, supported_document_versions: [1] },
      "recovery kit does not support document version 2",
    ],
  ]) {
    const page = await browser.newPage();
    try {
      await page.addInitScript((value) => {
        globalThis.__ETHERNITY_KIT_METADATA__ = value;
      }, metadata);
      const error = errorText ? page.waitForEvent("pageerror") : null;
      await page.goto(pathToFileURL(bundlePath).href);
      if (error) {
        const actual = await error;
        if (!actual.message.includes(errorText)) throw actual;
      } else {
        await page.getByRole("button", { name: "Use while online", exact: true }).click();
        await page.locator("#payload-text").waitFor({ state: "visible" });
        await page.locator("#shard-payload-text").waitFor({ state: "visible" });
      }
    } finally {
      await page.close();
    }
  }
}

async function checkScannerImages(page) {
  const frames = [];
  for (const name of ["v1-main", "v1-text", "v2-shard"]) {
    const png = await readFile(resolve(kitDir, "tests", "fixtures", `scanner-${name}.png`));
    frames.push({ name, image: `data:image/png;base64,${png.toString("base64")}` });
  }
  const text = (
    await readFile(
      resolve(
        kitDir,
        "..",
        "tests",
        "fixtures",
        "v1_0",
        "golden",
        "base64",
        "file_no_shard",
        "main_payloads.txt",
      ),
      "utf8",
    )
  ).split(/\r?\n/)[0];
  await page.evaluate(
    async ({ frames, text }) => {
      const originalMedia = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
      const originalPlay = HTMLMediaElement.prototype.play;
      const originalDraw = CanvasRenderingContext2D.prototype.drawImage;
      let image;
      let stops = 0;
      Object.defineProperty(navigator, "mediaDevices", {
        configurable: true,
        value: {
          async getUserMedia() {
            const stream = new MediaStream();
            stream.getTracks = () => [
              {
                stop() {
                  stops += 1;
                },
              },
            ];
            return stream;
          },
        },
      });
      HTMLMediaElement.prototype.play = async function () {
        Object.defineProperty(this, "videoWidth", { configurable: true, value: image.width });
        Object.defineProperty(this, "videoHeight", { configurable: true, value: image.height });
      };
      CanvasRenderingContext2D.prototype.drawImage = function (source, ...args) {
        return originalDraw.call(
          this,
          source instanceof HTMLVideoElement ? image : source,
          ...args,
        );
      };
      const check = (condition, message) => {
        if (!condition) throw new Error(message);
      };
      try {
        for (const frame of frames) {
          document.getElementById("reset").click();
          image = new Image();
          image.src = frame.image;
          await image.decode();
          const panel = document.getElementById(
            frame.name === "v2-shard" ? "sheets-scanner" : "backup-scanner",
          );
          const video = panel.querySelector("video");
          panel.querySelector("button").click();
          for (
            let attempt = 0;
            attempt < 100 && !panel.textContent.includes("Scan complete");
            attempt++
          ) {
            await new Promise((resolve) => setTimeout(resolve, 20));
          }
          check(
            panel.textContent.includes("Scan complete"),
            `Could not scan ${frame.name}: ${panel.textContent}`,
          );
          check(
            !video.srcObject && panel.querySelector(".scan-preview").hidden,
            "Completed scan kept the camera running",
          );
          if (frame.name === "v1-text") {
            check(
              document.getElementById("payload-text").value === text,
              "Base64 QR text was changed",
            );
            document.getElementById("backup-add").click();
          }
          await new Promise((resolve) => setTimeout(resolve, 0));
          const status = document.getElementById(
            frame.name === "v2-shard" ? "sheets-status" : "backup-status",
          );
          check(
            !status.hidden && !status.querySelector(".status.error"),
            `Scanned ${frame.name} was rejected: ${status.textContent}`,
          );
          if (frame.name === "v2-shard")
            check(status.textContent.includes("1 of 2 needed"), "Shard was not collected");
        }
        check(stops === frames.length, "Scanner leaked or stopped a camera more than once");
        document.getElementById("reset").click();
      } finally {
        HTMLMediaElement.prototype.play = originalPlay;
        CanvasRenderingContext2D.prototype.drawImage = originalDraw;
        if (originalMedia) Object.defineProperty(navigator, "mediaDevices", originalMedia);
        else delete navigator.mediaDevices;
      }
    },
    { frames, text },
  );
}

async function setOfflineAndWaitForEvent(page, offline) {
  await page.evaluate(
    (eventName) => {
      window.networkChangeObserved = false;
      window.addEventListener(
        eventName,
        () => {
          window.networkChangeObserved = true;
        },
        { once: true },
      );
    },
    offline ? "offline" : "online",
  );
  await page.context().setOffline(offline);
  await page.waitForFunction(() => window.networkChangeObserved);
}

async function checkOfflineTransitions(page) {
  await setOfflineAndWaitForEvent(page, true);
  const input = page.locator("#payload-text");
  await input.fill("offline draft");
  await setOfflineAndWaitForEvent(page, false);
  await page.locator("#offline-guard-title").waitFor({ state: "visible" });
  await page.getByRole("button", { name: "Use while online", exact: true }).click();
  await input.waitFor({ state: "visible" });
  if ((await input.inputValue()) !== "offline draft") {
    throw new Error("Network changes discarded recovery input");
  }
  await setOfflineAndWaitForEvent(page, true);
  await setOfflineAndWaitForEvent(page, false);
  await page.locator("#offline-guard-title").waitFor({ state: "visible" });
  await setOfflineAndWaitForEvent(page, true);
  await input.waitFor({ state: "visible" });
  if ((await input.inputValue()) !== "offline draft") {
    throw new Error("Automatic offline entry discarded recovery input");
  }
}

function base64NoPad(bytes) {
  return Buffer.from(bytes).toString("base64").replaceAll("=", "");
}

function buildFastAgeCiphertext(plaintext, passphrase) {
  const salt = new Uint8Array(16).fill(0x11);
  const fileKey = new Uint8Array(16).fill(0x22);
  const labelScrypt = textEncoder.encode("age-encryption.org/v1/scrypt");
  const labelAndSalt = concatBytes([labelScrypt, salt]);
  const wrappingKey = scrypt(passphrase, labelAndSalt, {
    N: 2,
    r: 8,
    p: 1,
    dkLen: 32,
  });
  const wrappedFileKey = chacha20poly1305(wrappingKey, new Uint8Array(12)).encrypt(fileKey);
  const headerPrefix = textEncoder.encode(
    `age-encryption.org/v1\n-> scrypt ${base64NoPad(salt)} 1\n${base64NoPad(wrappedFileKey)}\n---`,
  );
  const hmacKey = hkdf(sha256, fileKey, undefined, textEncoder.encode("header"), 32);
  const headerMac = hmac(sha256, hmacKey, headerPrefix);
  const header = concatBytes([headerPrefix, textEncoder.encode(` ${base64NoPad(headerMac)}\n`)]);
  const nonce = new Uint8Array(16).fill(0x33);
  const streamKey = hkdf(sha256, fileKey, nonce, textEncoder.encode("payload"), 32);
  const finalNonce = new Uint8Array(12);
  finalNonce[11] = 1;
  const payload = chacha20poly1305(streamKey, finalNonce).encrypt(plaintext);
  return concatBytes([header, nonce, payload]);
}

function requireSuccessfulCommand(result, label) {
  if (result.status !== 0) {
    throw new Error(
      `${label} failed: ${[result.stdout, result.stderr].filter(Boolean).join("\n").trim()}`,
    );
  }
}

async function waitForPageState(
  browser,
  pageUrl,
  { attempts, isReady, failureForState, timeoutMessage, onReady },
) {
  const page = await browser.newPage();
  try {
    // Local-file loading is intentional: WebKit workers have different Blob behavior here.
    await page.goto(pageUrl);
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const state = await page.evaluate(() => ({
        html: document.body?.innerHTML ?? "",
        text: document.body?.textContent ?? "",
      }));
      const failure = failureForState(state);
      if (failure) throw new Error(failure);
      if (isReady(state)) {
        await onReady?.(page);
        return;
      }
      await delay(100);
    }
    throw new Error(timeoutMessage);
  } finally {
    await page.close();
  }
}

async function frozenBackups() {
  const fixtures = resolve(kitDir, "..", "tests", "fixtures");
  const cases = [];
  for (const [release, scenario] of [
    ["v1_0", "file_no_shard"],
    ["v1_1", "sharded_embedded"],
  ]) {
    const directory = resolve(fixtures, release, "golden", "raw", scenario);
    const snapshot = JSON.parse(await readFile(resolve(directory, "snapshot.json"), "utf8"));
    cases.push({
      path: Object.keys(snapshot.expected_file_sha256)[0],
      payload: await readFile(resolve(directory, "main_payloads.txt"), "utf8"),
      passphrase: snapshot.passphrase,
      shards:
        scenario === "sharded_embedded"
          ? await readFile(resolve(directory, "shard_payloads_threshold.txt"), "utf8")
          : null,
      expectedHashes: snapshot.expected_file_sha256,
    });
  }
  const directory = resolve(
    fixtures,
    "v1_2",
    "extension_golden",
    "base64",
    "gzip_replacement_chain",
  );
  const snapshot = JSON.parse(await readFile(resolve(directory, "snapshot.json"), "utf8"));
  cases.push({
    path: "alpha.txt",
    payload: await readFile(resolve(directory, "chain_payloads.txt"), "utf8"),
    passphrase: snapshot.passphrase,
    expectedHashes: snapshot.states.extension_01,
  });
  return cases;
}

async function smokeRecoveryWorker(browser, cases) {
  const workDir = await mkdtemp(resolve(tmpdir(), "ethernity-recovery-smoke-"));
  try {
    const appOutput = resolve(workDir, "app.js");
    requireSuccessfulCommand(
      spawnSync(
        "npx",
        [
          "--no-install",
          "esbuild",
          resolve(kitDir, "tests", "browser_recovery_worker_entry.mjs"),
          "--bundle",
          "--format=iife",
          "--platform=browser",
          "--target=es2020",
          "--minify",
          `--outfile=${appOutput}`,
        ],
        { cwd: kitDir, encoding: "utf8" },
      ),
      "recovery smoke app build",
    );
    const fixtures = Buffer.from(JSON.stringify(cases)).toString("base64");
    const gzipFixtures = Buffer.from(JSON.stringify(gzipCases())).toString("base64");
    const bundledAppSource = await readFile(appOutput, "utf8");
    const minifiedApp = await terserMinify(bundledAppSource, {
      compress: { passes: 2, toplevel: true },
      mangle: { toplevel: true },
    });
    if (!minifiedApp.code) {
      throw new Error("terser produced no recovery smoke app output");
    }
    const htmlPath = resolve(workDir, "index.html");
    await writeFile(
      htmlPath,
      `<!doctype html><body data-fixtures="${fixtures}" data-gzip="${gzipFixtures}">waiting<script>${minifiedApp.code}</script></body>`,
      "utf8",
    );
    await waitForPageState(browser, pathToFileURL(htmlPath).href, {
      attempts: 1200,
      isReady: ({ text }) => text.trim() === "worker-ok",
      failureForState: ({ text }) => (text.trim().startsWith("worker-error:") ? text.trim() : null),
      timeoutMessage: "Recovery worker did not complete within 120 seconds",
    });
  } finally {
    await rm(workDir, { recursive: true, force: true, maxRetries: 3 });
  }
}

const engines = { chromium, firefox, webkit };
const requestedBrowsers = process.argv.slice(2);
const browserNames = requestedBrowsers.length ? requestedBrowsers : ["chromium", "webkit"];
for (const name of browserNames) {
  if (!Object.hasOwn(engines, name)) throw new Error(`Unknown browser: ${name}`);
}
const backups = [
  ...[null, "incremental", "cumulative"].map(smokeBackup),
  ...(await frozenBackups()),
];
const bundleSmokeCount =
  process.env.ETHERNITY_KIT_BROWSER_SMOKE_WORKER_ONLY === "1" ? 0 : bundlePaths.length;
for (const name of browserNames) {
  const browser = await engines[name].launch({ headless: true });
  try {
    if (bundleSmokeCount) {
      for (const bundlePath of bundlePaths) {
        process.stdout.write(`Booting ${bundlePath} in ${name}...\n`);
        await smokeBundle(browser, bundlePath, backups);
        await checkPrintedMetadata(browser, bundlePath);
      }
    }
    await smokeUiLifecycle(browser);
    process.stdout.write(
      `${name}: DOM identity, UI disposal, and camera lifecycle checks passed.\n`,
    );
    await smokeRecoveryWorker(browser, backups);
    process.stdout.write(
      `${name}: ${printedKitDirectory ? "reconstructed printed" : "generated gzip"} kits passed: ${bundleSmokeCount}; recovery worker passed\n`,
    );
  } finally {
    await browser.close();
  }
}
