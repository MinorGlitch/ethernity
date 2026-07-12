import { constants as fsConstants } from "node:fs";
import { access, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

import { chacha20poly1305 } from "@noble/ciphers/chacha.js";
import { hmac } from "@noble/hashes/hmac.js";
import { hkdf } from "@noble/hashes/hkdf.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { scrypt } from "@noble/hashes/scrypt.js";
import { minify as terserMinify } from "terser";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const kitDir = resolve(scriptDir, "..");
const bundlePaths = [
  resolve(kitDir, "..", "src", "ethernity", "resources", "kit", "recovery_kit.bundle.html"),
  resolve(kitDir, "..", "src", "ethernity", "resources", "kit", "recovery_kit.scanner.bundle.html"),
];
const textEncoder = new TextEncoder();

async function firstExecutable(paths) {
  for (const path of paths.filter(Boolean)) {
    try {
      await access(path, fsConstants.X_OK);
      return path;
    } catch {
      // Try the next supported Chrome location.
    }
  }
  return null;
}

async function smokeBundle(chrome, bundlePath) {
  const loaderHtml = await readFile(bundlePath, "utf8");
  if (!/name="ethernity-kit-compression" content="gzip"/u.test(loaderHtml)) {
    throw new Error(`${bundlePath} is not the canonical gzip recovery kit`);
  }
  const profileDir = await mkdtemp(resolve(tmpdir(), "ethernity-chrome-smoke-"));
  try {
    await waitForPageState(chrome, pathToFileURL(bundlePath).href, profileDir, {
      attempts: 300,
      isReady: ({ html, text }) =>
        text.includes("Recovery Kit Locked") && html.includes('id="app"'),
      failureForState: ({ text }) =>
        text.includes("Recovery kit cannot open here")
          ? `${bundlePath} rendered the unsupported-loader fallback in Chrome`
          : null,
      timeoutMessage: `${bundlePath} did not boot the recovery app in Chrome`,
    });
  } finally {
    await rm(profileDir, { recursive: true, force: true });
  }
}

function concatBytes(parts) {
  const length = parts.reduce((total, part) => total + part.length, 0);
  const result = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    result.set(part, offset);
    offset += part.length;
  }
  return result;
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

function devToolsPipeClient(child) {
  const pending = new Map();
  let nextId = 1;
  let buffered = "";
  child.stdio[4].on("data", (chunk) => {
    buffered += chunk.toString();
    while (buffered.includes("\0")) {
      const separator = buffered.indexOf("\0");
      const rawMessage = buffered.slice(0, separator);
      buffered = buffered.slice(separator + 1);
      if (!rawMessage) continue;
      const message = JSON.parse(rawMessage);
      const request = pending.get(message.id);
      if (!request) continue;
      pending.delete(message.id);
      if (message.error) {
        request.reject(new Error(message.error.message));
      } else {
        request.resolve(message.result);
      }
    }
  });
  child.once("exit", (code) => {
    for (const request of pending.values()) {
      request.reject(new Error(`Chrome DevTools pipe closed (${code})`));
    }
    pending.clear();
  });
  return {
    send(method, params = {}, sessionId = undefined) {
      const id = nextId;
      nextId += 1;
      return new Promise((resolveRequest, rejectRequest) => {
        pending.set(id, { resolve: resolveRequest, reject: rejectRequest });
        child.stdio[3].write(`${JSON.stringify({ id, method, params, sessionId })}\0`);
      });
    },
  };
}

async function waitForPageState(
  chrome,
  pageUrl,
  profileDir,
  { attempts, isReady, failureForState, timeoutMessage },
) {
  const child = spawn(
    chrome,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-sandbox",
      "--allow-file-access-from-files",
      "--remote-debugging-pipe",
      `--user-data-dir=${profileDir}`,
      pageUrl,
    ],
    { stdio: ["ignore", "ignore", "pipe", "pipe", "pipe"] },
  );
  child.stderr.resume();
  const client = devToolsPipeClient(child);
  try {
    let page = null;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      const targets = await client.send("Target.getTargets");
      page = targets.targetInfos.find((target) => target.type === "page" && target.url === pageUrl);
      if (page) break;
      await delay(50);
    }
    if (!page) {
      throw new Error("Chrome page target was not available");
    }
    const attached = await client.send("Target.attachToTarget", {
      targetId: page.targetId,
      flatten: true,
    });
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const result = await client.send(
        "Runtime.evaluate",
        {
          expression:
            "({html: document.body?.innerHTML ?? '', text: document.body?.textContent ?? ''})",
          returnByValue: true,
        },
        attached.sessionId,
      );
      const state = result.result?.value ?? { html: "", text: "" };
      const failure = failureForState(state);
      if (failure) {
        throw new Error(failure);
      }
      if (isReady(state)) {
        return state;
      }
      await delay(100);
    }
    throw new Error(timeoutMessage);
  } finally {
    child.kill("SIGTERM");
    await delay(100);
    if (child.exitCode === null) {
      child.kill("SIGKILL");
    }
  }
}

async function waitForWorkerResult(chrome, htmlPath, profileDir) {
  await waitForPageState(chrome, pathToFileURL(htmlPath).href, profileDir, {
    attempts: 150,
    isReady: ({ text }) => text.trim() === "worker-ok",
    failureForState: ({ text }) =>
      text.trim().startsWith("worker-error:")
        ? `Chrome scrypt worker failed: ${text.trim()}`
        : null,
    timeoutMessage: "Chrome scrypt worker did not complete within 15 seconds",
  });
}

async function smokeScryptWorker(chrome) {
  const workDir = await mkdtemp(resolve(tmpdir(), "ethernity-scrypt-smoke-"));
  try {
    const workerOutput = resolve(workDir, "worker.js");
    requireSuccessfulCommand(
      spawnSync(
        "npx",
        [
          "--no-install",
          "esbuild",
          resolve(kitDir, "lib", "age_scrypt_worker.js"),
          "--bundle",
          "--format=iife",
          "--platform=browser",
          "--target=es2020",
          "--minify",
          `--outfile=${workerOutput}`,
        ],
        { cwd: kitDir, encoding: "utf8" },
      ),
      "scrypt worker build",
    );
    const workerSource = await readFile(workerOutput, "utf8");
    const appOutput = resolve(workDir, "app.js");
    requireSuccessfulCommand(
      spawnSync(
        "npx",
        [
          "--no-install",
          "esbuild",
          resolve(kitDir, "scripts", "browser_scrypt_smoke_entry.js"),
          "--bundle",
          "--format=iife",
          "--platform=browser",
          "--target=es2020",
          "--minify",
          `--define:__ETHERNITY_SCRYPT_WORKER_SOURCE__=${JSON.stringify(workerSource)}`,
          "--define:__ETHERNITY_SYNC_SCRYPT_ENABLED__=false",
          `--outfile=${appOutput}`,
        ],
        { cwd: kitDir, encoding: "utf8" },
      ),
      "scrypt smoke app build",
    );
    const plaintext = textEncoder.encode("worker-ok");
    const passphrase = "browser-worker-smoke";
    const ciphertext = buildFastAgeCiphertext(plaintext, passphrase);
    const bundledAppSource = await readFile(appOutput, "utf8");
    const minifiedApp = await terserMinify(bundledAppSource, {
      compress: { passes: 2, toplevel: true },
      mangle: { toplevel: true },
    });
    if (!minifiedApp.code) {
      throw new Error("terser produced no scrypt smoke app output");
    }
    const htmlPath = resolve(workDir, "index.html");
    await writeFile(
      htmlPath,
      `<!doctype html><body data-ciphertext="${Buffer.from(ciphertext).toString("base64")}" data-passphrase="${passphrase}">waiting<script>${minifiedApp.code}</script></body>`,
      "utf8",
    );
    await waitForWorkerResult(chrome, htmlPath, resolve(workDir, "chrome-profile"));
  } finally {
    await rm(workDir, { recursive: true, force: true });
  }
}

const chrome = await firstExecutable([
  process.env.CHROME_BIN,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
]);
if (!chrome) {
  throw new Error(
    "Chrome executable not found; set CHROME_BIN to run the generated-kit smoke test",
  );
}
const bundleSmokeCount =
  process.env.ETHERNITY_KIT_BROWSER_SMOKE_WORKER_ONLY === "1" ? 0 : bundlePaths.length;
if (bundleSmokeCount) {
  for (const bundlePath of bundlePaths) {
    process.stdout.write(`Booting ${bundlePath} in Chrome...\n`);
    await smokeBundle(chrome, bundlePath);
  }
}
process.stdout.write("Running the Chrome scrypt Worker smoke...\n");
await smokeScryptWorker(chrome);
process.stdout.write(
  `Generated gzip recovery kits booted in Chrome: ${bundleSmokeCount}; scrypt worker passed\n`,
);
